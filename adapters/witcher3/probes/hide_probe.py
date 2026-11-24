"""Is anything of the hidden player left in the picture? (Nathan saw a bolt floating where the
invisible player stood, Hierarch Square, 2026-11-23.)

    uv run --project . python -m adapters.witcher3.probes.hide_probe [--at x,y,z] [--yaw deg]

The player stands at a spot; in the held world the camera looks at him from 2.5 m in front and 2.5 m
behind, at chest height, and each view is taken with him shown (cm_hide 0), with his body hidden
only (cm_hide 2, as before 2026-11-23) and with his body and every item entity hidden (cm_hide 1).
Reported per view: the share of pixels that differ by more than 24 between "body only" and
"everything" (what his items add) and between "everything" and the same view taken again
(the renderer's noise). Frames under out/probes/witcher3/hide/.

Found (Hierarch Square, 2026-11-23, the player mounted): his 11 item entities go with his body;
hiding them as well changed 0.002% of pixels in front and behind, also after parking him in the
held world and three steps (--park), so the script went back to hiding the body only and cm_hide
2 is now the same as 1. The floating spear Nathan saw was not the player's.
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
from ..session import Session, vec
from .cloth_step_probe import shot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default="", help="x,y,z of the spot (default: where the player stands)")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--park", action="store_true", help="as the influence probe did: park the player at the spot in the held world, then 3 steps")
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "hide")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("hide", 0)
    if a.at:
        x, y, z = [float(v) for v in a.at.split(",")]
        s.cmd("teleport", x, y, z, a.yaw)
        time.sleep(4)
    st = s.state()
    p = vec(st["player"])
    yaw = float(st.get("heading", a.yaw))
    rows = {}
    try:
        s.cmd("freeze")
        if a.park:
            s.cmd("hide", 2)
            s.cmd("park", p[0], p[1], p[2] + 0.05)
            frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
            for _ in range(3):
                mark = s.log_size()
                r = s.cmd("stepe", 1.0 / 30, 8, frame_s)
                s.wait_line("t", r.seq, mark, timeout=30.0)
            p = vec(s.state()["player"])
        for name, ahead in (("front", 2.5), ("back", -2.5)):
            fx, fy = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
            cx, cy, cz = p[0] + ahead * fx, p[1] + ahead * fy, p[2] + 1.3
            look = math.degrees(math.atan2(-(p[0] - cx), p[1] - cy))
            s.cmd("pose", cx, cy, cz, -8.0, look, 0, 60)
            imgs = {}
            for mode, tag in ((0, "shown"), (2, "body_only"), (1, "everything"), (1, "everything_again")):
                r = s.cmd("hide", mode)
                imgs[tag] = shot(s, ex, "hide_%s_%s" % (name, tag), out, settle=60)
                if mode == 1 and tag == "everything":
                    rows["items_hidden"] = r.data
            def over(u, v):
                return round(100 * float((np.abs(imgs[u] - imgs[v]).max(axis=2) > 24).mean()), 3)
            rows[name] = {"items_add_pct": over("body_only", "everything"),
                          "noise_pct": over("everything", "everything_again"),
                          "body_pct": over("shown", "body_only")}
            print(name, json.dumps(rows[name]))
        print("items:", rows.get("items_hidden"))
    finally:
        s.cmd("unfreeze")
        if a.park:
            s.cmd("unpark", p[0], p[1], p[2] + 0.1, yaw)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(rows, f, indent=1)
    print("frames in", out)


if __name__ == "__main__":
    main()
