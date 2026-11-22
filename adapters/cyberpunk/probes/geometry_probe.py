"""Does the engine put world points where the rig's pinhole model says?

At the player's spot, with the world held: for poses with yaw, pitch and roll, the engine's own
projection of world points (the camera system's ProjectPoint) is compared with a pinhole camera
of the adapter's render field of view (vertical, centred principal point) at the pose asked for.
Reports the largest difference in pixels of the rendered frame, and what the engine's screen
units are.

    uv run --project . python -m adapters.cyberpunk.probes.geometry_probe
"""
import json
import math
import os
import sys

import numpy as np

from capture import paths as capture_paths

from ...common import redlua
from ..adapter import CyberpunkAdapter


def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = axis
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def main(argv):
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_geometry")
    os.makedirs(out, exist_ok=True)
    report = {"poses": []}
    try:
        st = ad.subject_state()
        fwd0, right0, up0 = (np.array(v) for v in ad.heading_basis(st["facing_deg"]))
        eye = np.array(st["position"]) + up0 * 1.7
        w, h = (int(v) for v in ad.settings["render_size"])
        vfov = float(ad.settings["render_vfov"])
        ty = math.tan(math.radians(vfov) / 2)
        tx = ty * w / h
        ad.hide_subject(True)
        rng = np.random.default_rng(7)
        worst = 0.0
        for yaw, pitch, roll in [(0, 0, 0), (40, 0, 0), (-75, 20, 0), (10, -35, 0), (0, 0, 30), (130, 25, -60), (200, -50, 45)]:
            r = rot(up0, yaw)
            f, rt = r @ fwd0, r @ right0
            rp = rot(rt, pitch)
            f, u = rp @ f, rp @ up0
            rr = rot(f, roll)
            rt, u = rr @ rt, rr @ u
            ad._pose(eye, rt, f, u, vfov)
            s = ad.sess.cmd("wait", 5)
            pose = {"yaw": yaw, "pitch": pitch, "roll": roll, "rendered_fov": float(s["rendered_fov"]), "points": []}
            for _ in range(12):
                d = rng.uniform(3, 30)
                a, b = rng.uniform(-0.9, 0.9) * tx, rng.uniform(-0.9, 0.9) * ty
                p = eye + d * (f + a * rt + b * u)
                e = redlua.vec(ad.sess.cmd("project", "%.6f %.6f %.6f" % tuple(p))["screen"])
                # expected, in normalised device units: x to the right, y up, each -1..1
                want = (a / tx, b / ty)
                pose["points"].append({"want_ndc": want, "engine": e})
            report["poses"].append(pose)
        # which way do the engine's units run? fit engine = k * want per axis over every point
        wx = np.array([p["want_ndc"][0] for q in report["poses"] for p in q["points"]])
        wy = np.array([p["want_ndc"][1] for q in report["poses"] for p in q["points"]])
        ex = np.array([p["engine"][0] for q in report["poses"] for p in q["points"]])
        ey = np.array([p["engine"][1] for q in report["poses"] for p in q["points"]])
        kx, ky = float(wx @ ex / (wx @ wx)), float(wy @ ey / (wy @ wy))
        report["engine_units"] = {"x_per_ndc": kx, "y_per_ndc": ky}
        # with the sign of each axis taken from the fit, the scale must be 1: a different vertical
        # field of view or aspect would show as a scale other than 1
        err_x = (ex * np.sign(kx) - wx) * w / 2
        err_y = (ey * np.sign(ky) - wy) * h / 2
        worst = float(np.max(np.hypot(err_x, err_y)))
        report["largest_error_px"] = worst
        report["mean_error_px"] = float(np.mean(np.hypot(err_x, err_y)))
        report["render_size"] = [w, h]
        report["render_vfov_deg"] = vfov
    finally:
        ad.close()
    for q in report["poses"]:
        del q["points"]
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
