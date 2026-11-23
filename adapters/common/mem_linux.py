"""The memory of a running game on Linux (a Windows game under Proton): the same names as
mem_win32.py. Reached through mem.py. Game-agnostic.

The game's address space is the Windows one (the exe and its DLLs are mapped where Windows would
map them), so addresses and offsets found on Windows hold here. It is read and written through
/proc/<pid>/mem, with /proc/<pid>/maps for the regions. With the kernel's ptrace_scope at 1 this
still works from a process that is not the game's parent: measured 2026-11-23 on a CoreWeave node
(maps, /proc/<pid>/mem opened read-write, and process_vm_readv all answered).

Protection flags are reported in Windows' terms (PAGE_*), which is what callers test.
"""
import os
import struct

import numpy as np

from capture import host

PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
PAGE_NOCACHE = 0x200
PAGE_WRITECOMBINE = 0x400
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
MEM_PRIVATE = 0x20000
MEM_IMAGE = 0x1000000


def find_pid(name):
    found = host.pids(name)
    if not found:
        raise RuntimeError(name + " is not running")
    return found[0]


class Process:
    def __init__(self, pid=None, write=False, exe=None):
        if not pid and not exe:
            raise ValueError("Process needs a pid or the game's process name")
        self.pid = pid or find_pid(exe)
        self.fd = os.open("/proc/%d/mem" % self.pid, os.O_RDWR if write else os.O_RDONLY)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _maps(self):
        """(start, end, perms, path) of every mapping."""
        with open("/proc/%d/maps" % self.pid, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split(None, 5)
                a, b = parts[0].split("-")
                yield int(a, 16), int(b, 16), parts[1], parts[5].strip() if len(parts) > 5 else ""

    def regions(self, writable_only=True):
        """Mapped regions as (base, size, protect, type), protect in Windows' PAGE_* terms."""
        for start, end, perms, path in self._maps():
            if "r" not in perms or path.startswith("[v"):     # [vvar], [vsyscall]: not the game's
                continue
            w, x = "w" in perms, "x" in perms
            if writable_only and not w:
                continue
            prot = (PAGE_EXECUTE_READWRITE if x else PAGE_READWRITE) if w else (PAGE_EXECUTE_READ if x else PAGE_READONLY)
            yield start, end - start, prot, MEM_IMAGE if path.lower().endswith((".exe", ".dll")) else MEM_PRIVATE

    def read(self, addr, size):
        try:
            return os.pread(self.fd, size, addr)
        except OSError:
            return None

    def write(self, addr, data):
        return os.pwrite(self.fd, bytes(data), addr)

    def protect(self, addr, size, prot=PAGE_EXECUTE_READWRITE):
        """Nothing to change: writes through /proc/<pid>/mem reach read-only pages too. Returns
        the protection asked for, so restoring "the old one" afterwards is harmless."""
        return prot

    def module(self, name=None):
        """(base, size) of a loaded module (default: the first exe mapped, the game's own)."""
        base = None
        for start, _, _, path in self._maps():
            leaf = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if (leaf == name.lower()) if name else leaf.endswith(".exe"):
                base = start
                break
        if base is None:
            raise RuntimeError("module %s not loaded" % name)
        head = self.read(base, 0x1000) or b""
        if head[:2] != b"MZ":
            raise RuntimeError("module %s: no image header at 0x%x" % (name, base))
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        return base, struct.unpack_from("<I", head, pe + 24 + 56)[0]     # the optional header's SizeOfImage

    def read_floats(self, addr, n):
        raw = self.read(addr, 4 * n)
        if raw is None or len(raw) < 4 * n:
            return None
        return struct.unpack("<%df" % n, raw)

    def write_floats(self, addr, values):
        return self.write(addr, struct.pack("<%df" % len(values), *values))

    def scan_vec3(self, xyz, tol=1e-3, chunk=32 << 20, progress=None):
        """Addresses (4-byte aligned) where three consecutive float32 equal xyz within tol."""
        x, y, z = (np.float32(v) for v in xyz)
        hits = []
        scanned = 0
        for base, size, _, _ in self.regions():
            off = 0
            while off < size:
                n = min(chunk, size - off)
                raw = self.read(base + off, n)
                if raw:
                    usable = len(raw) - len(raw) % 4
                    f = np.frombuffer(raw[:usable], dtype=np.float32)
                    if len(f) >= 3:
                        with np.errstate(invalid="ignore"):
                            m = (np.abs(f[:-2] - x) < tol) & (np.abs(f[1:-1] - y) < tol) & (np.abs(f[2:] - z) < tol)
                        for i in np.nonzero(m)[0]:
                            hits.append(base + off + 4 * int(i))
                    scanned += len(raw)
                # Overlap 8 bytes so a triple across the chunk edge is not missed.
                off += n if n < chunk else n - 8
            if progress:
                progress(scanned)
        return sorted(set(hits)), scanned
