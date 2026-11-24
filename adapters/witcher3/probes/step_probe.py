"""What a time step moves, and how exact it is.

    uv run --project . python -m adapters.witcher3.probes.step_probe [--pose x,y,z,pitch,yaw] [--steps 30] [--fps 30] [--wind 1,0]

The world is held at one pose. For each wind setting (the scale of the tree and cloud wind clocks,
cm_wind), the probe takes the average of 8 frames, steps the world `steps` times by 1/fps with a
few frames between steps, takes the average of 8 frames again and prints

    engine time     what each step added (mean, smallest, largest), against 1/fps
    the picture     mean difference of the two averages, and the share of pixels that changed by
                    more than 12, beside the same numbers for two averages with no step between
                    (the renderer's own noise)

so that it shows whether trees and grass move with the steps (they should: 1/30 s of wind between
clip frames) and whether that depends on the wind clocks. Difference maps (x8) are saved under
out/probes/witcher3/step/.
"""
import argparse
import json
import os

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session
from .noise_probe import burst, default_pose, mad


def engine(st):
    return float(st["engine_base"]) + float(st["engine_rel"])


def average(ex, tag, n=8, gap=8):
    return burst(ex, n, gap, tag).mean(axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--wind", default="1,0")
    ap.add_argument("--settle", type=int, default=180)
    a = ap.parse_args()
    from PIL import Image
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "step")
    os.makedirs(out, exist_ok=True)
    st = s.close_menu()
    if st.get("menu") == "1":
        raise SystemExit("the game's menu is open and would not close")
    st = s.cmd("hud", 0).state
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")] if a.pose else default_pose(st)
    dt = 1.0 / a.fps
    report = {"pose": [x, y, z, pitch, yaw], "dt": dt, "steps": a.steps, "runs": []}
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        frames.wait(ex, a.settle)
        for wind in [float(v) for v in a.wind.split(",")]:
            s.cmd("wind", wind, wind)
            frames.wait(ex, 30)
            one = average(ex, "a")
            two = average(ex, "b")
            noise = mad(one, two)
            noise12 = 100 * float((np.abs(one - two).max(axis=2) > 12).mean())
            t = engine(s.state())
            added = []
            for _ in range(a.steps):
                s.cmd("step", dt)
                frames.wait(ex, 3)
                now = engine(s.state())
                added.append(now - t)
                t = now
            frames.wait(ex, 60)
            three = average(ex, "c")
            moved = mad(two, three)
            moved12 = 100 * float((np.abs(two - three).max(axis=2) > 12).mean())
            d = np.clip(np.abs(two - three).max(axis=2) * 8, 0, 255).astype(np.uint8)
            Image.fromarray(d).save(os.path.join(out, "wind%g_diff_x8.png" % wind))
            Image.fromarray(np.clip(three + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(out, "wind%g_after.png" % wind))
            row = {"wind": wind, "step_mean_s": float(np.mean(added)), "step_min_s": float(np.min(added)),
                   "step_max_s": float(np.max(added)), "noise_mean": round(noise, 4), "noise_over_12_pct": round(noise12, 4),
                   "moved_mean": round(moved, 4), "moved_over_12_pct": round(moved12, 4)}
            report["runs"].append(row)
            print("wind clocks at %g: %d steps of %.7f s added %.7f s each (%.7f to %.7f)"
                  % (wind, a.steps, dt, row["step_mean_s"], row["step_min_s"], row["step_max_s"]))
            print("  the picture: mean difference %.3f and %.3f%% of pixels over 12 across the steps; %.3f and %.3f%% with no step"
                  % (moved, moved12, noise, noise12))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
