"""Time steps: is each one exactly dt, in even frames, and does the world hold between them?

    uv run --project . python -m adapters.kcd.probes.step_probe [--steps 10] [--frames 8]

Holds the world (t_Scale 0), then runs --steps steps of 1/30 s (CaptureMod step: t_FixedStep of
dt/frames, a per-frame script timer counting frames, held again after the last), reporting what
each step advanced by the sum of its frames' times, the shortest and longest frame, and people within
30 m: how many moved during the steps and while held 2 s after them.
"""
import argparse
import json
import time

import numpy as np

from ..session import Session, parse_kv, vec
from .freeze_probe import people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--dt", type=float, default=1.0 / 30)
    a = ap.parse_args()
    s = Session()
    centre = vec(s.cmd("state").state["player"])
    rows = []
    try:
        s.cmd("freeze")
        p0 = people(s, centre)
        for k in range(a.steps):
            mark = s.log_size()
            r = s.cmd("step", a.dt, a.frames)
            done = s.wait_line("t", r.seq, mark, timeout=20.0)
            if done is None:
                raise SystemExit("a step did not end")
            got = parse_kv(done)
            rows.append({k2: float(v) for k2, v in got.items()})
            print("step %d: %s" % (k, done))
        p1 = people(s, centre)
        time.sleep(2.0)
        p2 = people(s, centre)
        moved = [float(np.linalg.norm(p1[i] - p[:3])) for i, p in p0.items() if i in p1]
        held = [float(np.linalg.norm(p2[i] - p[:3])) for i, p in p1.items() if i in p2]
        adv = [r["advanced"] for r in rows]
        print(json.dumps({"steps": len(rows), "advanced_ms": [round(1000 * min(adv), 4), round(1000 * max(adv), 4)],
                          "frame_ms": [round(1000 * min(r["min"] for r in rows), 4), round(1000 * max(r["max"] for r in rows), 4)],
                          "people": len(moved), "moved_during_steps": sum(m > 0.05 for m in moved),
                          "max_moved_m": round(max(moved), 3) if moved else None,
                          "moved_while_held": sum(m > 0.01 for m in held)}))
    finally:
        s.cmd("unfreeze")


if __name__ == "__main__":
    main()
