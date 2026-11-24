"""Does game time creep while the world is held through many shots? The game's clocks are single-
precision floats (System.GetCurrTime steps 1.95 ms at 27,000 s, and one clip frame of a ring take
read two values one step apart), so the test is people's positions instead: printed to 0.1 mm, a
walker at 1.4 m/s moves 0.1 mm in 0.07 ms.

    uv run --project . python -m adapters.kcd.probes.creep_probe [--location <id>] [--shots 40]

The world is held right after people were walking; everyone within 25 m is located, then --shots
shots are taken the way a take takes them (a pose about the spot, 20 frames of settle, two frames),
and everyone located again; then the same after 30 even steps, for scale. Reported: how many people
moved more than 0.1 mm while held, the most any moved, and the game timer before and after.
"""
import argparse
import json
import math
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, vec


def people(s, c, r=25.0):
    out = {}
    for line in s.cmd("people", c[0], c[1], c[2], r).data:
        parts = line.split()
        out[parts[0]] = np.array(vec(parts[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="kcd-rattay-pillory-001")
    ap.add_argument("--shots", type=int, default=40)
    ap.add_argument("--pause", action="store_true", help="the game's own pause on top (CryAction.PauseGame) while held")
    ap.add_argument("--long", type=float, default=0.0, help="instead: hold one pose this many seconds; the same frame at both ends")
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    c = [float(v) for v in loc["position"]]
    s = Session()
    ex = paths.exchange()
    rep = {}
    s.cmd("unfreeze")
    s.cmd("teleport", c[0], c[1], c[2] + 0.1, 0)
    time.sleep(8)
    try:
        s.cmd("hud", 0)
        s.cmd("ghost", 1)
        s.cmd("freeze")
        if a.pause:
            s.cmd("eval", "CryAction.PauseGame(true)")
        t0 = s.state()["time"]
        p0 = people(s, c)
        if a.long > 0:
            from PIL import Image
            import os

            def frame(name):
                r = frames.shoot(ex, "creep/" + name, after=20)
                with Image.open(r["path"]) as im:
                    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
                os.remove(r["path"])
                return arr
            s.cmd("pose", c[0], c[1] - 3, c[2] + 1.6, -10.0, 0.0, 0.0, 60.0)
            time.sleep(s.console_clear_in())
            f0 = frame("long0")
            w0 = time.time()
            while time.time() - w0 < a.long:
                time.sleep(20)
                s.cmd("state")                     # commands keep coming, as in a take
            f1 = frame("long1")
            t1 = s.state()["time"]
            p1 = people(s, c)
            moved = [float(np.linalg.norm(p1[i] - p)) for i, p in p0.items() if i in p1]
            rep["long"] = {"seconds": a.long, "frame_mean_diff": round(float(np.abs(f0 - f1).mean()), 4),
                           "pixels_over_12_pct": round(100 * float((np.abs(f0 - f1).max(axis=2) > 12).mean()), 4),
                           "people": len(moved), "moved_over_0.1mm": sum(m > 1e-4 for m in moved),
                           "max_moved_mm": round(1000 * max(moved), 2) if moved else None, "timer": [t0, t1]}
            print("held one pose %.0f s: %s" % (a.long, json.dumps(rep["long"])))
            return rep
        for k in range(a.shots):
            yaw = 360.0 * k / a.shots
            s.cmd("pose", c[0] + 3 * math.sin(math.radians(yaw)), c[1] - 3 * math.cos(math.radians(yaw)), c[2] + 1.6,
                  -10.0, 0.0, yaw, 60.0)
            time.sleep(s.console_clear_in())
            for p in (frames.shoot(ex, "creep/a", after=20)["path"], frames.shoot(ex, "creep/b", after=1)["path"]):
                try:
                    import os
                    os.remove(p)
                except OSError:
                    pass
        t1 = s.state()["time"]
        p1 = people(s, c)
        moved = [float(np.linalg.norm(p1[i] - p)) for i, p in p0.items() if i in p1]
        rep["held"] = {"shots": a.shots, "people": len(moved), "moved_over_0.1mm": sum(m > 1e-4 for m in moved),
                       "max_moved_mm": round(1000 * max(moved), 2) if moved else None, "timer": [t0, t1]}
        print("held%s through %d shots: %s" % (" (with the game's pause)" if a.pause else "", a.shots, json.dumps(rep["held"])))
        if a.pause:
            s.cmd("eval", "CryAction.PauseGame(false)")
        for _ in range(30):
            mark = s.log_size()
            r = s.cmd("step", 1.0 / 30, 8)
            s.wait_line("t", r.seq, mark, timeout=20.0)
        p2 = people(s, c)
        moved = [float(np.linalg.norm(p2[i] - p)) for i, p in p1.items() if i in p2]
        rep["stepped_1s"] = {"people": len(moved), "moved_over_5cm": sum(m > 0.05 for m in moved),
                             "max_moved_m": round(max(moved), 3) if moved else None}
        print("after 30 steps (1 s): %s" % json.dumps(rep["stepped_1s"]))
    finally:
        if a.pause:
            s.cmd("eval", "CryAction.PauseGame(false)")
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("ghost", 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    return rep


if __name__ == "__main__":
    main()
