"""Does a pose set through the GTA V adapter render as the rig's pinhole camera says?

For a few poses around the player (level, pitched, rolled, wide and narrow field of view) it
asks the engine where world points land on screen (GET_SCREEN_COORD_FROM_WORLD_COORD, the
rendered camera) and compares with the pinhole model of the pose (vertical FoV, centred
principal point, 16:9). Errors in pixels at 2560x1440. Also checks the heading convention
(forward = (-sin h, cos h, 0)) against the camera the game renders for a level pose.

    uv run --project . python adapters/gtav/probes/geometry_probe.py
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from adapters.common import redlua  # noqa: E402
from adapters.gtav.adapter import GTAVAdapter  # noqa: E402

W, H = 2560, 1440


def axes(yaw, pitch, roll):
    """right, fwd, up of a camera turned by yaw (heading), pitched, then rolled about forward."""
    y, p, r = (math.radians(v) for v in (yaw, pitch, roll))
    fwd = np.array([-math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), math.sin(p)])
    right0 = np.array([math.cos(y), math.sin(y), 0.0])
    up0 = np.cross(right0, fwd)
    right = math.cos(r) * right0 + math.sin(r) * up0        # positive roll: right edge goes up
    up = np.cross(right, fwd)
    return right, fwd, up


def pinhole(pt, pos, right, fwd, up, vfov):
    d = np.asarray(pt) - np.asarray(pos)
    t = math.tan(math.radians(vfov) / 2)
    x = 0.5 + 0.5 * (d @ right) / (d @ fwd) / (t * W / H)
    y = 0.5 - 0.5 * (d @ up) / (d @ fwd) / t
    return x, y


def main():
    a = GTAVAdapter()
    a.ensure_ready(restart=False)
    a.open()
    try:
        s = a.sess
        p = np.array(redlua.vec(s.cmd("state")["player"]))
        pos = p + np.array([0.0, 0.0, 1.0])
        worst = 0.0
        for yaw, pitch, roll, vfov in ((0, 0, 0, 50), (90, -10, 0, 50), (200, 15, 0, 70), (30, 0, 20, 50),
                                       (300, -20, -35, 40), (120, 5, 60, 90)):
            right, fwd, up = axes(yaw, pitch, roll)
            a._pose(pos, right, fwd, up, vfov)
            st = s.cmd("wait", 5)
            errs = []
            for u, v in ((0.0, 0.0), (0.3, 0.2), (-0.3, -0.25), (0.4, -0.3), (-0.35, 0.3)):
                t = math.tan(math.radians(vfov) / 2)
                pt = pos + 10 * fwd + 10 * t * (u * 2 * (W / H) * right + v * 2 * up)
                r = s.cmd("project", "%.5f %.5f %.5f" % tuple(pt))
                ex, ey = (float(x) for x in r["screen"].split())
                mx, my = pinhole(pt, pos, right, fwd, up, vfov)
                errs.append(math.hypot((ex - mx) * W, (ey - my) * H))
            rot = st["rendered_rot"]
            worst = max(worst, max(errs))
            print("yaw %4d pitch %4d roll %4d vfov %3d: rendered rot %s fov %s; projection error max %.2f px (%s)" % (
                yaw, pitch, roll, vfov, rot, st["rendered_fov"], max(errs), " ".join("%.2f" % e for e in errs)))
        print("worst projection error: %.2f px" % worst)
        # heading: a level camera along heading h looks where heading_basis says
        h = 75.0
        f, rt, u = (np.asarray(v) for v in a.heading_basis(h))
        a._pose(pos, rt, f, u, 50)
        st = s.cmd("wait", 5)
        print("heading %.0f: rendered rot %s (the game's yaw should be %.0f)" % (h, st["rendered_rot"], h))
    finally:
        a.close()


if __name__ == "__main__":
    main()
