"""Finds engine values by how they follow a controlled change: snapshot every writable value of a
type, press a key (or wait), keep the values that moved the asked way, repeat. How Death Stranding's
camera and clock values were found (2026-11-25), with no script layer to ask the game.

    python -m adapters.deathstranding.probes.scan_probe --type f64 --steps "E:+,Q:-,_:=,E:+" --hold 0.6

Each step is KEY:SIGN. KEY is a scan-code name of adapters/common/window_win32.SCAN, a hex scan code
(0x11 is W) or _ for no key; SIGN is + (the value grew by at least --min-delta), - (fell by at least
--min-delta), ~ (moved either way by at least --min-delta) or = (unchanged within --eq). The
survivors are printed with their neighbours and kept
in out/probes/deathstranding/scan_<time>.json, which --from takes up again (no fresh snapshot)."""
import argparse
import json
import os
import time

import numpy as np

from adapters.common import mem
from adapters.common import window_win32 as w
from capture import paths

TITLE = "DEATH STRANDING DIRECTOR'S CUT"
EXE = "ds.exe"
CHUNK = 64 << 20


def regions(proc, private_only=True):
    for base, size, prot, typ in proc.regions():
        if private_only and typ != 0x20000:   # MEM_PRIVATE: heaps, not images or mapped files
            continue
        yield base, size


def read_typed(proc, base, size, dtype):
    """The region as an array of dtype (None where unreadable), read in chunks."""
    parts = []
    off = 0
    item = np.dtype(dtype).itemsize
    while off < size:
        n = min(CHUNK, size - off)
        raw = proc.read(base + off, n)
        if not raw or len(raw) < n:
            raw = (raw or b"") + b"\0" * (n - len(raw or b""))
        parts.append(np.frombuffer(raw[: n - n % item], dtype=dtype))
        off += n
    return np.concatenate(parts) if len(parts) > 1 else parts[0]


def plausible(a, lo, hi):
    with np.errstate(invalid="ignore", over="ignore"):
        x = np.abs(a.astype(np.float64))
        return np.isfinite(x) & (x >= lo) & (x <= hi)


def snapshot(proc, dtype, lo, hi, raw=False):
    """Every plausible value (lo <= |v| <= hi) with its place. raw: every value whatever it holds,
    kept as whole regions (as much memory as the game's heaps) and narrowed by the first step."""
    cand = {}
    total = 0
    for base, size in regions(proc):
        a = read_typed(proc, base, size, dtype)
        if raw:
            cand[base] = (size, None, a.copy())
            total += len(a)
            continue
        idx = np.nonzero(plausible(a, lo, hi))[0]
        if len(idx):
            cand[base] = (size, idx.astype(np.int64), a[idx].astype(np.float64))
            total += len(idx)
    return cand, total


def reread(proc, cand, dtype):
    out = {}
    for base, (size, idx, _) in cand.items():
        a = read_typed(proc, base, size, dtype)
        out[base] = a if idx is None else a[idx].astype(np.float64)
    return out


def act(h, key, hold):
    if key == "_":
        time.sleep(hold)
        return
    code = int(key, 16) if key.startswith("0x") else key
    w.focus(h)
    w.press(h, code, hold_s=hold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="f64", choices=["f64", "f32"])
    ap.add_argument("--steps", required=True)
    ap.add_argument("--hold", type=float, default=0.6)
    ap.add_argument("--settle", type=float, default=0.4, help="seconds after a key before reading")
    ap.add_argument("--min-delta", type=float, default=0.02)
    ap.add_argument("--max-delta", type=float, default=50.0)
    ap.add_argument("--eq", type=float, default=1e-7)
    ap.add_argument("--lo", type=float, default=0.5)
    ap.add_argument("--hi", type=float, default=1e5)
    ap.add_argument("--from", dest="src", default=None)
    ap.add_argument("--raw", action="store_true", help="keep every value of the first snapshot (no plausibility filter)")
    ap.add_argument("--show", type=int, default=40)
    a = ap.parse_args()
    dtype = np.float64 if a.type == "f64" else np.float32
    h = w.windows_titled(TITLE)[0]
    proc = mem.Process(exe=EXE)
    t0 = time.time()
    if a.src:
        saved = json.load(open(a.src))
        addrs = np.array(saved["addrs"], dtype=np.int64)
        cand = {}
        for base, size in regions(proc):
            sel = addrs[(addrs >= base) & (addrs < base + size)]
            if len(sel):
                idx = (sel - base) // np.dtype(dtype).itemsize
                cand[base] = (size, idx, np.zeros(len(idx)))
        cur = reread(proc, cand, dtype)
        cand = {b: (s, i, cur[b]) for b, (s, i, _) in cand.items()}
        total = sum(len(v[1]) for v in cand.values())
    else:
        cand, total = snapshot(proc, dtype, a.lo, a.hi, raw=a.raw)
    print("%d candidates (%s) in %.0f s" % (total, a.type, time.time() - t0), flush=True)
    for step in a.steps.split(","):
        key, sign = step.split(":")
        act(h, key, a.hold)
        time.sleep(a.settle)
        now = reread(proc, cand, dtype)
        kept = {}
        n = 0
        for base, (size, idx, old) in cand.items():
            new = now[base]
            if idx is None:      # a raw snapshot: whole regions until the first step narrows them
                idx = np.arange(len(old), dtype=np.int64)
            with np.errstate(invalid="ignore", over="ignore"):
                d = new.astype(np.float64) - old.astype(np.float64)
            with np.errstate(invalid="ignore"):
                if sign == "+":
                    m = (d >= a.min_delta) & (d <= a.max_delta)
                elif sign == "-":
                    m = (-d >= a.min_delta) & (-d <= a.max_delta)
                elif sign == "~":
                    m = (np.abs(d) >= a.min_delta) & (np.abs(d) <= a.max_delta)
                else:
                    m = np.abs(d) <= a.eq
            if m.any():
                kept[base] = (size, idx[m], new[m].astype(np.float64))
                n += int(m.sum())
        cand = kept
        print("step %s: %d left" % (step, n), flush=True)
        if n == 0:
            break
    item = np.dtype(dtype).itemsize
    addrs = sorted(int(b + i * item) for b, (s, idx, v) in cand.items() for i in idx)
    out_dir = os.path.join(paths.OUT, "probes", "deathstranding")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "scan_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"type": a.type, "steps": a.steps, "addrs": addrs}, open(out, "w"))
    print("saved", out)
    for addr in addrs[: a.show]:
        raw = proc.read(addr - 32, 96)
        vals = np.frombuffer(raw, dtype=dtype) if raw else []
        print(hex(addr), " ".join("%.4f" % v for v in vals))


if __name__ == "__main__":
    main()
