"""Which instructions write (or read) an address in a running game: a data breakpoint in the CPU's
debug registers, set on every thread of the process, for a few seconds. Each hit gives the
instruction and the registers, so the structure the value came from can be followed back. How Death
Stranding's camera code was found (2026-11-25), with no script layer and no debugger installed.

    python -m adapters.deathstranding.probes.watch_probe 0x44578af3610 --len 8 --seconds 3
    python -m adapters.deathstranding.probes.watch_probe 0x... --access rw    # reads too

The game is attached as by a debugger (DebugActiveProcess) and released afterwards, its debug
registers cleared; it keeps running. Hits are summarised per instruction, with a disassembly when
capstone is available (uv run --with capstone)."""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import struct
import time

from adapters.common import mem

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenThread.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE

DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT, CREATE_THREAD, CREATE_PROCESS, EXIT_THREAD, EXIT_PROCESS, LOAD_DLL = 1, 2, 3, 4, 5, 6
SINGLE_STEP, BREAKPOINT = 0x80000004, 0x80000003
CONTEXT_AMD64 = 0x100000
CONTEXT_FULL_DBG = CONTEXT_AMD64 | 0x1 | 0x2 | 0x10
CONTEXT_SIZE = 1232
REGS = ["rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
OFF_FLAGS, OFF_DR0, OFF_DR6, OFF_DR7, OFF_RAX, OFF_RIP = 0x30, 0x48, 0x68, 0x70, 0x78, 0xF8
OFF_EFLAGS = 0x44
OFF_XMM0 = 0x100 + 0xA0     # FltSave.XmmRegisters


class Ctx:
    """A 16-byte aligned CONTEXT buffer."""
    def __init__(self):
        self.raw = ctypes.create_string_buffer(CONTEXT_SIZE + 16)
        self.addr = (ctypes.addressof(self.raw) + 15) & ~15

    def get(self, h):
        struct.pack_into("<I", (ctypes.c_char * CONTEXT_SIZE).from_address(self.addr), OFF_FLAGS, CONTEXT_FULL_DBG)
        return bool(k32.GetThreadContext(h, ctypes.c_void_p(self.addr)))

    def set(self, h):
        return bool(k32.SetThreadContext(h, ctypes.c_void_p(self.addr)))

    def buf(self):
        return (ctypes.c_char * CONTEXT_SIZE).from_address(self.addr)

    def q(self, off):
        return struct.unpack_from("<Q", self.buf(), off)[0]

    def put_q(self, off, v):
        struct.pack_into("<Q", self.buf(), off, v)

    def regs(self):
        r = {n: self.q(OFF_RAX + 8 * i) for i, n in enumerate(REGS)}
        r["rip"] = self.q(OFF_RIP)
        r["xmm"] = [struct.unpack_from("<4f", self.buf(), OFF_XMM0 + 16 * i) for i in range(16)]
        return r


def dr7_for(length, access):
    lens = {1: 0b00, 2: 0b01, 4: 0b11, 8: 0b10}
    rw = {"w": 0b01, "rw": 0b11, "x": 0b00}[access]
    return 1 | (rw << 16) | (lens[length] << 18)


def arm(handles, addr, dr7):
    """Sets DR0/DR7 on every thread; returns how many read back as set."""
    c = Ctx()
    ok = 0
    for h in handles.values():
        if c.get(h):
            c.put_q(OFF_DR0, addr)
            c.put_q(OFF_DR7, dr7)
            c.put_q(OFF_DR6, 0)
            if c.set(h) and c.get(h) and c.q(OFF_DR7) == dr7 and c.q(OFF_DR0) == addr:
                ok += 1
    return ok


def watch(pid, addr, length=8, access="w", seconds=3.0, max_hits=2000):
    if not k32.DebugActiveProcess(pid):
        raise ctypes.WinError(ctypes.get_last_error())
    k32.DebugSetProcessKillOnExit(False)
    handles, hits, armed, stopping = {}, [], False, False
    hproc = None
    ev = ctypes.create_string_buffer(176)
    dr7 = dr7_for(length, access)
    t_end = None
    ctx = Ctx()
    steps = [0]
    other = collections.Counter()
    try:
        while True:
            # checked on every event: a breakpoint that fires each frame never lets the wait time out
            if armed and not stopping and (time.time() > t_end or len(hits) >= max_hits):
                stopping = True
                k32.DebugBreakProcess(wt.HANDLE(hproc))     # a stop of every thread, to disarm them
            if not k32.WaitForDebugEvent(ev, 200):
                continue
            code, _, tid = struct.unpack_from("<III", ev, 0)
            status = DBG_CONTINUE
            if code == CREATE_PROCESS:
                hfile, hproc, hthread = struct.unpack_from("<QQQ", ev, 16)
                handles[tid] = hthread
                if hfile:
                    k32.CloseHandle(wt.HANDLE(hfile))
            elif code == CREATE_THREAD:
                handles[tid] = struct.unpack_from("<Q", ev, 16)[0]
                if armed and not stopping:
                    arm({tid: handles[tid]}, addr, dr7)
            elif code == EXIT_THREAD:
                handles.pop(tid, None)
            elif code == LOAD_DLL:
                hfile = struct.unpack_from("<Q", ev, 16)[0]
                if hfile:
                    k32.CloseHandle(wt.HANDLE(hfile))
            elif code == EXCEPTION_DEBUG_EVENT:
                exc = struct.unpack_from("<I", ev, 16)[0]
                if exc == BREAKPOINT:
                    if not armed:
                        n = arm(handles, addr, dr7)
                        armed, t_end = True, time.time() + seconds
                        print("armed %d threads" % n, flush=True)
                    elif stopping:
                        arm(handles, 0, 0)
                        k32.ContinueDebugEvent(struct.unpack_from("<I", ev, 4)[0], tid, DBG_CONTINUE)
                        break
                elif exc == SINGLE_STEP and tid in handles:
                    h = handles[tid]
                    steps[0] += 1
                    if ctx.get(h):
                        if not stopping:      # DR6 is not always reported in the context: take every step
                            hits.append(ctx.regs())
                        ctx.put_q(OFF_DR6, 0)
                        if stopping:          # disarm as threads come by, in case the stop is late
                            ctx.put_q(OFF_DR7, 0)
                        if access == "x":     # resume flag: run the instruction instead of breaking on it again
                            fl = struct.unpack_from("<I", ctx.buf(), OFF_EFLAGS)[0]
                            struct.pack_into("<I", ctx.buf(), OFF_EFLAGS, fl | 0x10000)
                        ctx.set(h)
                else:
                    other[hex(exc)] += 1
                    status = DBG_EXCEPTION_NOT_HANDLED
            elif code == EXIT_PROCESS:
                print("the game exited")
                break
            k32.ContinueDebugEvent(struct.unpack_from("<I", ev, 4)[0], tid, status)
    finally:
        k32.DebugActiveProcessStop(pid)
    print("single steps %d, other exceptions %s" % (steps[0], dict(other)))
    return hits


def disasm(proc, rip, before=48, after=16):
    """The instructions around rip (the one that ended at rip is the access)."""
    try:
        import capstone
    except ImportError:
        return None
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for back in range(before, 0, -1):
        code = proc.read(rip - back, back + after)
        if not code:
            continue
        ins = list(md.disasm(code, rip - back))
        ends = [i.address + i.size for i in ins]
        if rip in ends:
            return ["%s%x  %s %s" % ("=>" if i.address + i.size == rip else "  ", i.address, i.mnemonic, i.op_str) for i in ins]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addr")
    ap.add_argument("--exe", default="ds.exe")
    ap.add_argument("--len", type=int, default=8, choices=[1, 2, 4, 8])
    ap.add_argument("--access", default="w", choices=["w", "rw", "x"])
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    addr = int(a.addr, 0)
    proc = mem.Process(exe=a.exe)
    base, size = proc.module(a.exe)
    hits = watch(proc.pid, addr, a.len, a.access, a.seconds)
    print("%d hits in %.1f s" % (len(hits), a.seconds))
    by = collections.defaultdict(list)
    for h in hits:
        by[h["rip"]].append(h)
    for rip, hs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        rel = "%s+%x" % (a.exe, rip - base) if base <= rip < base + size else hex(rip)
        print("\n%d hits after %s" % (len(hs), rel))
        h = hs[-1]
        print("  " + " ".join("%s=%x" % (n, h[n]) for n in REGS))
        print("  xmm0-3 " + " | ".join(" ".join("%.4f" % v for v in x) for x in h["xmm"][:4]))
        lines = disasm(proc, rip)
        if lines:
            print("\n".join("  " + l for l in lines))


if __name__ == "__main__":
    main()
