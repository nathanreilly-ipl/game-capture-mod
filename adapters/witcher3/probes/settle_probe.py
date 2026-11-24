"""How many frames after a camera cut until the picture stops changing.

    uv run --project . python -m adapters.witcher3.probes.settle_probe [--pose x,y,z,pitch,yaw] [--turn 90] [--runs 3]

The world is held. The camera is settled at pose A turned by --turn degrees, then cut to pose B
(the pose itself), and frames are saved at the given counts after the cut; the reference is the
average of 8 frames taken 300 frames after the cut. For each count the mean difference to the
reference and the share of pixels off by more than 12 are printed, beside the same numbers for one
frame of the settled picture (the renderer's own noise floor). Temporal filters (DLSS, Ray
Reconstruction, the path tracer's denoiser) carry history over the cut; the settle is the count
where the curve reaches the floor. Repeated --runs times; out/probes/witcher3/settle/report.json.
"""
import argparse
import json
import os

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session
from .noise_probe import burst, default_pose, load

COUNTS = (2, 5, 10, 15, 20, 30, 40, 60, 80, 120, 180)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="")
    ap.add_argument("--turn", type=float, default=90.0)
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "settle")
    os.makedirs(out, exist_ok=True)
    st = s.close_menu()
    if st.get("menu") == "1":
        raise SystemExit("the game's menu is open and would not close")
    st = s.cmd("hud", 0).state
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")] if a.pose else default_pose(st)
    report = {"pose": [x, y, z, pitch, yaw], "turn": a.turn, "counts": list(COUNTS), "runs": []}
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        for run in range(a.runs):
            s.cmd("pose", x, y, z, pitch, yaw + a.turn, 0, 60)
            frames.wait(ex, 240)
            s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
            # the first count is taken right after the command; its frame number tells where the cut is
            shots, last = [], 0
            for n in COUNTS:
                shots.append(frames.shoot(ex, "settle/r%d_%03d" % (run, n), after=n - last))
                last = n
            cut = shots[0]["frame"] - COUNTS[0]
            imgs = [load(sh["path"]) for sh in shots]
            frames.wait(ex, 300 - COUNTS[-1])
            ref_set = burst(ex, 8, 4, "settle/ref%d" % run)
            ref = ref_set.mean(axis=0)
            floor = float(np.abs(ref_set[0] - ref).mean())
            floor12 = 100 * float((np.abs(ref_set[0] - ref).max(axis=2) > 12).mean())
            rows = []
            for sh, img in zip(shots, imgs):
                d = np.abs(img - ref)
                rows.append({"after": sh["frame"] - cut, "mean": round(float(d.mean()), 4),
                             "over_12_pct": round(100 * float((d.max(axis=2) > 12).mean()), 4)})
            report["runs"].append({"floor_mean": round(floor, 4), "floor_over_12_pct": round(floor12, 4), "rows": rows})
            print("run %d (noise floor: one frame against the settled average %.3f, %.3f%% over 12)" % (run, floor, floor12))
            print("   " + "  ".join("%d:%.2f/%.1f%%" % (r["after"], r["mean"], r["over_12_pct"]) for r in rows))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
