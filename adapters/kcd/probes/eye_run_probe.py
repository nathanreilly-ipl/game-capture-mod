"""How far a short run at the first pose leaves the eye from adapted (for the eye lock's run before
the hold: ghost_run_s, eye_run_speed). For each case the eye first adapts to the player's own view
with the world running (--away seconds), then the camera goes to the target view, the world runs
`run` seconds with r_HDREyeAdaptationSpeed at `speed`, and is held; one frame is read. The longest
run at the game's speed is the adapted reference.

    uv run --project . python -m adapters.kcd.probes.eye_run_probe --location kcd-sasau-bridge-001
        [--cases 3:2,3:15,30:2,3:40] [--target medium] [--away 10]
        [--steps 30 --cases 3:2:lock,3:2:free]

--steps N: after the hold, N time steps of 1/30 s at the same view, a frame after each; a case
ending in :lock sets the speed to 0 at the hold (the eye lock), :free leaves it running.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from capture import locations, paths as capture_paths  # noqa: E402
import upscaler_ab as u  # noqa: E402

from ..adapter import KcdAdapter  # noqa: E402


def luma(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="kcd-sasau-bridge-001")
    ap.add_argument("--cases", default="3:2,3:15,30:2,3:40", help="speed:run_seconds, ...")
    ap.add_argument("--target", default="medium")
    ap.add_argument("--away", type=float, default=10.0, help="seconds the eye adapts to the player's view first")
    ap.add_argument("--clock", default="12:00")
    ap.add_argument("--steps", type=int, default=0)
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "kcd_eye_run", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    ad = KcdAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    s = ad.sess
    speed0 = (s.cmd("cvar", "r_HDREyeAdaptationSpeed").data or ["?"])[0]
    report = {"location": a.location, "target": a.target, "away_s": a.away, "game_speed": speed0, "cases": []}
    print("the game's r_HDREyeAdaptationSpeed:", speed0, flush=True)
    try:
        loc = locations.get(capture_paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.set_clock(a.clock)
        st = ad.subject_state()
        view = u.views(ad, st)[a.target]
        s.cmd("hud", 0)
        s.cmd("ghost", 1)
        for n, case in enumerate(a.cases.split(",")):
            parts = case.split(":")
            speed, run = float(parts[0]), float(parts[1])
            lock = len(parts) > 2 and parts[2] == "lock"
            s.cmd("unfreeze")
            s.cmd("release")                 # the player's own view, world running
            s.cmd("cvar", "r_HDREyeAdaptationSpeed", float(speed0))
            time.sleep(a.away)
            s.cmd("cvar", "r_HDREyeAdaptationSpeed", speed)
            ad._pose(view["pos"], view["fwd"], view["up"], view["vfov_deg"])
            time.sleep(run)
            s.cmd("freeze")
            p = os.path.join(out, "%02d_speed%g_run%g.bmp" % (n, speed, run))
            ad._shoot(p, 20)
            v = luma(p)
            Image.open(p).resize((640, 360)).save(p[:-4] + ".jpg", quality=85)
            os.remove(p)
            row = {"speed": speed, "run_s": run, "brightness": round(v, 2)}
            print("speed %-5g run %4g s: brightness %.2f" % (speed, run, v), flush=True)
            if a.steps:
                if lock:
                    s.cmd("cvar", "r_HDREyeAdaptationSpeed", 0)
                row["lock"] = lock
                ad._step_debt = 0.0
                vals = []
                for k in range(a.steps):
                    ad.advance(1.0 / 30)
                    q = os.path.join(out, "%02d_step%02d.bmp" % (n, k + 1))
                    ad._shoot(q, 20)
                    vals.append(round(luma(q), 2))
                    os.remove(q)
                row["steps"] = vals
                print("   %s, %d steps: %s; last/first %.4f" % ("speed 0 at the hold" if lock else "speed left at %g" % speed,
                      a.steps, " ".join("%.1f" % x for x in vals[::5]), vals[-1] / v), flush=True)
            report["cases"].append(row)
    finally:
        try:
            s.cmd("cvar", "r_HDREyeAdaptationSpeed", float(speed0))
            s.cmd("unfreeze")
            s.cmd("release")
            s.cmd("ghost", 0)
            s.cmd("hide", 0)
            s.cmd("hud", 1)
        finally:
            ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
