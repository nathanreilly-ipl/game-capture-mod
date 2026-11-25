"""Does grass move on game time, or by frames? (QC round 1, kcd-001: the grass close to the lens at
Rattay changed almost completely at every 1/30 s step.) A time step is spread over step_frames frames
of equal game time; if the grass's sway follows game time, the change per step is the same whether a
step has 8 frames or 32; if it follows frames, it grows with them (too fast in a take).

    uv run --project . python -m adapters.kcd.probes.grass_step_probe --take <a take folder> [--camera near_temporal_00]
        [--crop 0.0,0.6,0.3,0.4] [--steps 6] [--frames 8,32,8]

At the take's location, from that camera's first pose: for each frames value, --steps steps of 1/30 s
and a frame after each; the mean absolute change of the crop per step (levels of 255).
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ..adapter import KcdAdapter


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--take", required=True)
    ap.add_argument("--camera", default="near_temporal_00")
    ap.add_argument("--crop", default="0.0,0.6,0.3,0.4")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--frames", default="8,32,8")
    a = ap.parse_args(argv)
    take = json.load(open(os.path.join(a.take, "take.json"), encoding="utf-8"))
    shots = json.load(open(os.path.join(a.take, "shots.json"), encoding="utf-8"))
    pose = next(sh for st in shots["steps"] for sh in st["shots"] if a.camera in sh["name"])
    out = os.path.join(capture_paths.OUT, "probes", "kcd_grass_step", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    x, y, w, h = (float(v) for v in a.crop.split(","))
    ad = KcdAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    report = {"take": a.take, "camera": a.camera, "crop": a.crop, "runs": []}
    try:
        loc = take["location"]
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.prepare_take(shots)
        ad.begin_frozen(pose)
        ad.set_camera(pose)

        def crop():
            p = os.path.join(out, "f.bmp")
            ad.capture(p, 20)
            im = Image.open(p).convert("RGB")
            W, H = im.size
            c = np.asarray(im.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))), dtype=np.float32)
            os.remove(p)
            return c

        for frames_per_step in (int(v) for v in a.frames.split(",")):
            ad.settings["step_frames"] = frames_per_step
            prev = crop()
            d = []
            for _ in range(a.steps):
                ad.advance(1.0 / 30)
                cur = crop()
                d.append(round(float(np.abs(cur - prev).mean()), 3))
                prev = cur
            report["runs"].append({"step_frames": frames_per_step, "change_per_step": d, "mean": round(float(np.mean(d)), 3)})
            print("step over %2d frames: change per step %s, mean %.3f" % (frames_per_step, d, np.mean(d)), flush=True)
    finally:
        try:
            ad.end_frozen()
            ad.hide_subject(False)
        finally:
            ad.close()
    json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
