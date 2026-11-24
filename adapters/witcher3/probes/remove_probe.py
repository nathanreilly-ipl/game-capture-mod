"""Does anything stay behind when people are removed? (Nathan saw a spear or bolt floating in the
air, Hierarch Square, 2026-11-23; what people hold are item entities of their own.)

    uv run --project . python -m adapters.witcher3.probes.remove_probe [--pose x,y,z,pitch,yaw]

In the held world, a view of townspeople (by default the torch-bearing priests at Hierarch
Square): a frame; the people in the near half of the view removed as takes did until 2026-11-23
(cm_remove keep 1: the person only); a frame; the rest removed with their items hidden first
(cm_remove: the capture method); a frame; then three time steps and a last frame. Frames and
difference maps under out/probes/witcher3/remove/: look for torches, tools or weapons left where
people stood.
"""
import argparse
import json
import math
import os
import time

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, pack
from .cloth_step_probe import shot
from .npc_influence_probe import people


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="654.6,1871.1,11.6,-6,16")
    ap.add_argument("--reach", type=float, default=14.0, help="people this far ahead of the camera and nearer")
    a = ap.parse_args()
    from PIL import Image
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "remove")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, yaw)
    time.sleep(12)
    report = {}
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        before = shot(s, ex, "0_before", out, settle=150)
        f = np.array([-math.sin(math.radians(yaw)), math.cos(math.radians(yaw)), 0.0])
        cam = np.array([x, y, z])
        seen = []
        for p in people(s, list(cam + 8 * f), 9.0):
            d = p["pos"] - cam
            ahead = float(d @ f)
            side = abs(float(d[0] * f[1] - d[1] * f[0]))
            if 1.0 < ahead < a.reach and side < ahead * 0.7:
                seen.append((ahead, p))
        seen.sort(key=lambda t: t[0])
        half = len(seen) // 2
        old = [p for _, p in seen[:half]]
        new = [p for _, p in seen[half:]]
        report["people_in_view"] = len(seen)
        r = s.cmd("remove", pack([v for p in old for v in p["pos"]], digits=4), 1)
        report["old_way"] = r.text
        after_old = shot(s, ex, "1_removed_old_way", out)
        r = s.cmd("remove", pack([v for p in new for v in p["pos"]], digits=4))
        report["new_way"] = r.text
        after_new = shot(s, ex, "2_removed_new_way", out)
        frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
        for _ in range(3):
            mark = s.log_size()
            r = s.cmd("stepe", 1.0 / 30, 8, frame_s)
            s.wait_line("t", r.seq, mark, timeout=30.0)
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        stepped = shot(s, ex, "3_after_steps", out)
        for name, (u, v) in {"old": (before, after_old), "new": (after_old, after_new), "steps": (after_new, stepped)}.items():
            d = np.clip(np.abs(u - v).max(axis=2) * 3, 0, 255).astype(np.uint8)
            Image.fromarray(d).save(os.path.join(out, "diff_%s_x3.png" % name))
        print(json.dumps(report, indent=1))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
    with open(os.path.join(out, "report.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    print("frames in", out)


if __name__ == "__main__":
    main()
