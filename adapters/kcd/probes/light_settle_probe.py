"""How long the scene's light takes to settle after the camera arrives at a pose (BACKLOG: KCD, the
scene's light settling over a take). With the eye held (r_HDREyeAdaptationSpeed 0 after a short fast
adaptation), the world runs in increments of --run-step seconds at one view, is held, and one frame
is read each time: what changes is the scene's light (ambient, the voxel GI), not exposure.

    uv run --project . python -m adapters.kcd.probes.light_settle_probe --location kcd-talmberg-001
        [--target medium] [--total 30] [--run-step 1] [--steps-too 30]

--steps-too N: after the run, N time steps of 1/30 s as a take makes them (the same increments the
takes saw). Writes out/probes/kcd_light_settle/<stamp>/report.json and the frames.
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


def stats(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return float(a.mean()), float(a[a < np.percentile(a, 30)].mean()), float(a[a > np.percentile(a, 70)].mean())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="kcd-talmberg-001")
    ap.add_argument("--target", default="medium")
    ap.add_argument("--clock", default="12:00")
    ap.add_argument("--total", type=float, default=30.0)
    ap.add_argument("--run-step", type=float, default=1.0)
    ap.add_argument("--steps-too", type=int, default=0)
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "kcd_light_settle", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    ad = KcdAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    s = ad.sess
    speed0 = float((s.cmd("cvar", "r_HDREyeAdaptationSpeed").data or ["3"])[0]) or 3.0
    report = {"location": a.location, "target": a.target, "run_step_s": a.run_step, "rows": []}
    try:
        loc = locations.get(capture_paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.set_clock(a.clock)
        st = ad.subject_state()
        view = u.views(ad, st)[a.target]
        s.cmd("hud", 0)
        s.cmd("ghost", 1)
        ad._pose(view["pos"], view["fwd"], view["up"], view["vfov_deg"])
        s.cmd("cvar", "r_HDREyeAdaptationSpeed", 30)      # the eye adapts fast at the new view, then is held
        time.sleep(2.0)
        s.cmd("cvar", "r_HDREyeAdaptationSpeed", 0)
        t_run = 0.0
        while t_run <= a.total + 1e-6:
            s.cmd("freeze")
            p = os.path.join(out, "run_%05.1f.bmp" % t_run)
            ad._shoot(p, 20)
            m, lo, hi = stats(p)
            Image.open(p).resize((640, 360)).save(p[:-4] + ".jpg", quality=85)
            os.remove(p)
            report["rows"].append({"run_s": round(t_run, 2), "mean": round(m, 2), "dark30": round(lo, 2), "bright30": round(hi, 2)})
            print("after %5.1f s running: mean %.2f, darkest 30%% %.2f, brightest 30%% %.2f" % (t_run, m, lo, hi), flush=True)
            s.cmd("unfreeze")
            time.sleep(a.run_step)
            t_run += a.run_step
        s.cmd("freeze")
        if a.steps_too:
            ad.frozen = True
            ad._step_debt = 0.0
            vals = []
            for k in range(a.steps_too):
                ad.advance(1.0 / 30)
                p = os.path.join(out, "step_%02d.bmp" % (k + 1))
                ad._shoot(p, 20)
                vals.append(round(stats(p)[0], 2))
                os.remove(p)
            report["steps"] = vals
            print("then %d steps of 1/30 s: %s (last/first %.4f)" % (a.steps_too, " ".join("%.2f" % v for v in vals[::5]),
                                                                    vals[-1] / vals[0]), flush=True)
    finally:
        try:
            s.cmd("cvar", "r_HDREyeAdaptationSpeed", speed0)
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
