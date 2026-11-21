"""Does the render lose detail when the player is not at the capture location?

    uv run --project . python adapters/rdr2/probes/ghost_probe.py --location rdr2-lakeshore-001 [--height 200]

Captures the same rig views (frame 1 of the ST-DM near and far rings) under several
conditions, each in its own frozen run:
    at_spot       player hidden at the location (what takes do now)
    at_spot_2     the same again: run-to-run noise (the world moves on between runs)
    sky_focus     player parked --height m above the location, no collision, streaming
                  focus held on the location, ghost natives on
    sky_nofocus   parked the same, streaming left to follow the player
Reports per condition: mean difference to at_spot, and image sharpness (mean absolute
Laplacian), which drops when the engine streams lower detail.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.adapter import RDR2Adapter  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture import paths  # noqa: E402
from capture.placement import Placement  # noqa: E402
from capture.providers import find as find_provider  # noqa: E402
from capture.shots import build, select_cameras  # noqa: E402

RIG = find_provider("camrigs").demo_rig_file()  # the camera-rig repository's demo ST-DM rig (rigs/camrigs.py)
CAMERAS = ["H_near_temporal_00", "H_near_temporal_08", "H_near_temporal_16", "H_near_temporal_24",
           "H_far_temporal_00", "H_far_temporal_16"]


def sharpness(path):
    a = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(np.abs(lap).mean())


def mean_diff(a, b):
    return float(np.abs(np.asarray(Image.open(a).convert("RGB"), dtype=np.int16)
                        - np.asarray(Image.open(b).convert("RGB"), dtype=np.int16)).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", required=True)
    ap.add_argument("--height", type=float, default=200.0)
    ap.add_argument("--out", default=os.path.join(paths.OUT, "probes", "ghost"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    loc = locs.get(paths.LOCATIONS, args.location)
    with open(RIG, encoding="utf-8") as f:
        rig = json.load(f)

    ad = RDR2Adapter()
    ad.ensure_ready(restart=False)
    ad.open()
    results = {}
    try:
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.set_clock("12:00")
        origin = ad.ground_point(loc["position"])
        shots = select_cameras(build(rig, Placement(origin, ad.rig_rotation(loc["facing_deg"]))), CAMERAS)
        shots = shots["steps"][0]["shots"]
        x, y, z = origin
        for cond in ("at_spot", "sky_focus", "sky_nofocus", "at_spot_2"):
            if cond.startswith("at_spot"):
                ad.sess.cmd("ghost", 0)
                ad.sess.cmd("focus", "clear")
                ad.go_to(loc["position"], loc["facing_deg"])
            else:
                ad.sess.cmd("ghost", 1)
                ad.sess.cmd("park", "%.3f %.3f %.3f" % (x, y, z + args.height))
                if cond == "sky_focus":
                    ad.sess.cmd("focus", "%.3f %.3f %.3f" % (x, y, z))
                else:
                    ad.sess.cmd("focus", "clear")
            ad.hide_subject(True)
            ad.sess.cmd("wait", 600)  # let streaming settle for the new player position / focus
            ad.begin_frozen(shots[0])
            files = []
            for s in shots:
                dst = os.path.join(args.out, "%s_%s.bmp" % (cond, s["name"]))
                ad.set_camera(s)
                ad.capture(dst, 60)
                files.append(dst)
            ad.end_frozen()
            player = ad.sess.cmd("state")["player"]
            results[cond] = {"files": files, "player": player}
            print("%-12s player at %s" % (cond, player), flush=True)
    finally:
        ad.close()

    base = results["at_spot"]["files"]
    report = {}
    for cond, r in results.items():
        d = [mean_diff(a, b) for a, b in zip(base, r["files"])]
        s = [sharpness(f) for f in r["files"]]
        report[cond] = {"mean_diff_to_at_spot": round(float(np.mean(d)), 2), "sharpness": round(float(np.mean(s)), 3),
                        "per_view_diff": [round(v, 2) for v in d], "player": r["player"]}
        print("%-12s diff to at_spot %5.2f   sharpness %.3f" % (cond, np.mean(d), np.mean(s)))
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)


if __name__ == "__main__":
    main()
