"""Read, search and write the memory of the running game (RDR2.exe), for finding
engine data such as the render camera. Windows only; uses ctypes and numpy.

Only writable, ordinary memory is searched (no guard, no-cache or write-combined
pages), which is where heap objects such as cameras live.
"""
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess

import numpy as np

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
PAGE_NOCACHE = 0x200
PAGE_WRITECOMBINE = 0x400

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wt.BOOL
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def find_pid(name="RDR2.exe"):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + name, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0].lower() == name.lower():
            return int(parts[1])
    raise RuntimeError(name + " is not running")


class Process:
    def __init__(self, pid=None, write=False):
        self.pid = pid or find_pid()
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if write:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self.handle = kernel32.OpenProcess(access, False, self.pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def regions(self, writable_only=True):
        """Committed regions as (base, size, protect, type)."""
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress, mbi.RegionSize
            if size == 0:
                break
            if mbi.State == MEM_COMMIT:
                p = mbi.Protect
                ok = not (p & (PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE))
                if writable_only:
                    ok = ok and bool(p & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE))
                if ok:
                    yield base, size, p, mbi.Type
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t(0)
        if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[: got.value]

    def write(self, addr, data):
        buf = ctypes.create_string_buffer(data, len(data))
        done = ctypes.c_size_t(0)
        if not kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(done)):
            raise ctypes.WinError(ctypes.get_last_error())
        return done.value

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
