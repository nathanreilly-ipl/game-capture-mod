"""How many frames after a camera cut until the picture stops changing, and the renderer's own noise.

    uv run --project . python -m adapters.kcd.probes.settle_probe [--location <id>] [--turn 90] [--counts 1,2,3,5,8,12,20,35,60,100]

The world is held. For each count: the camera settled 120 frames at pose A (pose B turned by --turn
degrees), cut to B, and the frame --count frames after the cut saved. Reference: the average of 4
frames of B taken 300 frames after a cut. Printed per count: the mean difference to the reference and
the share of pixels off by more than 12; beside them the noise floor, one settled frame against the
reference. Temporal anti-aliasing carries history over the cut; the settle is the count where the
curve reaches the floor. out/probes/kcd/settle/report.json.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session


def load(path):
    from PIL import Image
    with Image.open(path) as im:
        a = np.asarray(im.convert("RGB"), dtype=np.float32)
    os.remove(path)
    return a


def diff(a, b):
    d = np.abs(a - b)
    return round(float(d.mean()), 3), round(100 * float((d.max(axis=2) > 12).mean()), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="kcd-rattay-pillory-001")
    ap.add_argument("--turn", type=float, default=90.0)
    ap.add_argument("--counts", default="1,2,3,5,8,12,20,35,60,100")
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    x, y, z = loc["position"][0], loc["position"][1], loc["position"][2] + 1.6
    yaw = float(loc.get("facing_deg", 0.0))
    s = Session()
    ex = paths.exchange()
    report = {"location": a.location, "counts": []}
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, yaw)
    time.sleep(10)
    try:
        s.cmd("hud", 0)
        s.cmd("hide", 1)
        s.cmd("freeze")

        def pose(t):
            s.cmd("pose", x, y, z, -5.0, 0.0, yaw + t, 60.0)
            time.sleep(s.console_clear_in())

        pose(a.turn)
        frames.wait(ex, 120)
        pose(0.0)
        ref = load(frames.shoot(ex, "settle_ref0", after=300)["path"])
        for k in range(3):
            ref += load(frames.shoot(ex, "settle_ref%d" % (k + 1), after=4)["path"])
        ref /= 4.0
        floor = diff(load(frames.shoot(ex, "settle_floor", after=30)["path"]), ref)
        report["noise_floor"] = floor
        print("noise floor (a settled frame against the reference): mean %.3f, %.3f%% over 12" % floor)
        for n in [int(v) for v in a.counts.split(",")]:
            pose(a.turn)
            frames.wait(ex, 120)
            pose(0.0)
            m, o = diff(load(frames.shoot(ex, "settle_%d" % n, after=n)["path"]), ref)
            report["counts"].append({"frames": n, "mean": m, "over_12_pct": o})
            print("%4d frames after the cut: mean %.3f, %.3f%% over 12" % (n, m, o))
    finally:
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    out = os.path.join(capture_paths.OUT, "probes", "kcd", "settle")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
