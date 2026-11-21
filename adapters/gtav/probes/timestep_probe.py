"""Where does GTA V's minimum time step (1/3000 s, so SET_TIME_SCALE(0) still runs the world at
0.33 ms per frame) come from, and can it be lowered so time scale 0 is a real freeze?

Scans GTA5.exe's image for float32 1/3000, then, with the world at time scale 0 through the
session job, sets each candidate to a tiny step for a few frames and reads GET_FRAME_TIME back;
every value is restored right after. Prints the candidates that change the frame time.

    uv run --project . python adapters/gtav/probes/timestep_probe.py [--value 1e-6] [--only writable]
"""
import argparse
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from adapters.common import mem, redlua  # noqa: E402
from adapters.gtav.adapter import EXCHANGE, EXE, SESSION_JOB  # noqa: E402

TARGET = np.float32(1.0 / 3000.0)


def scan(p):
    base, size = p.module(EXE)
    found = []
    for rb, rs, prot, _ in p.regions(writable_only=False):
        if rb + rs <= base or rb >= base + size:
            continue
        raw = p.read(rb, rs)
        if not raw:
            continue
        f = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype=np.float32)
        for i in np.flatnonzero(f == TARGET):
            found.append((rb + 4 * int(i), prot))
    return base, size, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--value", type=float, default=1e-6)
    ap.add_argument("--only", choices=("writable", "all"), default="all")
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    p = mem.Process(mem.find_pid(EXE), write=True)
    base, size, found = scan(p)
    writable = [(addr, pr) for addr, pr in found if pr & 0x44]   # PAGE_READWRITE | PAGE_EXECUTE_READWRITE
    print("GTA5.exe at %#x, %.0f MB; float 1/3000 at %d places (%d writable)" % (base, size / 1e6, len(found), len(writable)))
    order = writable + ([x for x in found if x not in writable] if a.only == "all" else [])
    s = redlua.Session(EXCHANGE, SESSION_JOB, idle_s=300, timeout_s=1800)
    hits = []
    try:
        s.cmd("freeze", "timescale")
        s.cmd("wait", 10)
        ref = float(s.cmd("state")["frame_time"])
        print("frame time at time scale 0: %.7f s" % ref)
        for n, (addr, prot) in enumerate(order[: a.limit]):
            old = p.read(addr, 4)
            restore_prot = None
            try:
                if not prot & 0x44:
                    restore_prot = p.protect(addr, 4, 0x04)
                p.write(addr, struct.pack("<f", a.value))
                s.cmd("wait", 3)
                ft = float(s.cmd("state")["frame_time"])
            finally:
                p.write(addr, old)
                if restore_prot is not None:
                    p.protect(addr, 4, restore_prot)
            mark = "  <-- changes the step" if abs(ft - ref) > ref * 0.2 else ""
            print("%3d %#x (+%#x) prot %#x: frame time %.7f%s" % (n, addr, addr - base, prot, ft, mark), flush=True)
            if mark:
                hits.append(addr - base)
        s.cmd("wait", 5)
        print("after restoring: frame time %.7f" % float(s.cmd("state")["frame_time"]))
    finally:
        try:
            s.cmd("unfreeze")
        except Exception:
            pass
        s.end()
        p.close()
    print("offsets in GTA5.exe that set the step:", ", ".join("%#x" % h for h in hits) or "none")


if __name__ == "__main__":
    main()
