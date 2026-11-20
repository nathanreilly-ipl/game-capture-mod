"""Checks that a pose written into the render camera frame gives exactly the picture
the engine itself renders for that pose, and that the engine's projection matches
the rig's pinhole model (vertical FoV, centred principal point).

    uv run --with numpy --with pillow tools/verify_geometry.py [--fov 54.5642]

1. Script camera at pose X (normal engine path), freeze, capture "ref".
2. Write a different pose Y, capture "other" (to show what a wrong pose costs).
3. Write pose X back through memory, capture "written". ref vs written should be
   at the noise level (ref vs a second ref capture).
4. Project points at known offsets in front of the camera with the engine and with
   the pinhole model, for the written pose.
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.session import CamSession, look_at, vec  # noqa: E402
from adapters.rdr2.render_camera import FOV_OFFSET, basis, calibrate, frame_bytes, pick_render_frame  # noqa: E402
from adapters.rdr2.mem import Process  # noqa: E402


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def bars(img):
    """Rows of black bar at the top and bottom."""
    rows = img.max(axis=(1, 2))
    top = next((i for i, v in enumerate(rows) if v > 3), 0)
    bottom = next((i for i, v in enumerate(rows[::-1]) if v > 3), 0)
    return top, bottom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fov", type=float, default=54.5642)
    ap.add_argument("--out", default="reports/verify_geometry")
    ap.add_argument("--exposure", choices=["lock", "none"], default="lock")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sess = CamSession()
    res = {"job_dir": sess.job_dir, "fov": args.fov}
    try:
        player = vec(sess.state["player"])
        aim = (player[0], player[1], player[2] + 0.9)
        X = (player[0] + 3.1, player[1] - 4.3, player[2] + 2.2)
        Y = (player[0] - 5.0, player[1] + 1.0, player[2] + 1.0)
        px, yx = look_at(X, aim)
        py_, yy = look_at(Y, aim)
        with Process(write=True) as proc:
            found, _ = calibrate(sess, proc, player)
            sess.pose(X, px, yx, args.fov)
            sess.cmd("wait", 40)
            sess.cmd("freeze")
            sess.cmd("wait", 30)
            frame = pick_render_frame(sess, proc, found)
            if len(frame) != 1:
                raise SystemExit("render camera frame not found: %s" % frame)
            frame = frame[0]
            sess.cmd("wait", 10)
            ref = sess.cmd("capture", "ref")
            ref2 = sess.cmd("capture", "ref2")
            if args.exposure == "lock":
                res["exposure_at_lock"] = sess.cmd("exposure", "lock")["exposure"]

            def write(pos, pitch, yaw):
                r, f, u = basis(pitch, yaw)
                proc.write(frame - 0x30, frame_bytes(pos, r, f, u))
                proc.write_floats(frame + FOV_OFFSET, [args.fov])
                sess.cmd("wait", 10)

            write(Y, py_, yy)
            other = sess.cmd("capture", "other")
            res["exposure_at_other"] = sess.cmd("exposure", "get")["exposure"]
            write(X, px, yx)
            written = sess.cmd("capture", "written")
            res["exposure_at_written"] = sess.cmd("exposure", "get")["exposure"]
            # How the difference to ref fades with more frames after the jump.
            settle_series = [(10, written["file"])]
            waited = 10
            for extra in (10, 20, 40, 80):
                sess.cmd("wait", extra)
                waited += extra
                settle_series.append((waited, sess.cmd("capture", "written_%03d" % waited)["file"]))
            if args.exposure == "lock":
                sess.cmd("exposure", "unlock")

            # Projection of points in front of the written camera.
            r, f, u = (np.array(v) for v in basis(px, yx))
            W, H = int(written["width"]), int(written["height"])
            fpx = 0.5 * H / math.tan(math.radians(args.fov) / 2)
            proj = []
            for d, a, b in [(5, 0, 0), (5, 1.5, 0), (5, 0, 1.2), (8, -2.5, -1.5), (4, 1.0, 1.0), (10, 3.0, 2.0)]:
                p = np.array(X) + d * f + a * r + b * u
                kv = sess.cmd("project", "%.6f %.6f %.6f" % tuple(p))
                sx, sy = vec(kv["screen"])
                mx, my = 0.5 + fpx * (a / d) / W, 0.5 - fpx * (b / d) / H
                proj.append({"d": d, "a": a, "b": b, "engine": [sx, sy], "model": [round(mx, 6), round(my, 6)],
                             "err_px": [round((sx - mx) * W, 2), round((sy - my) * H, 2)],
                             "onscreen": kv["onscreen"]})
            res["projection"] = proj
            res["rendered_after_write"] = {k: written[k] for k in ("rendered_pos", "rendered_rot", "rendered_fov")}
            res["engine_pose_X"] = {"pitch": px, "yaw": yx}
            sess.cmd("unfreeze")
    finally:
        sess.end()

    imgs = {k: load(v["file"]) for k, v in (("ref", ref), ("ref2", ref2), ("other", other), ("written", written))}
    res["size"] = [W, H]
    res["bars_ref"] = bars(imgs["ref"])
    res["diff_ref_ref2_noise"] = round(float(np.abs(imgs["ref"] - imgs["ref2"]).mean()), 3)
    res["diff_ref_written"] = round(float(np.abs(imgs["ref"] - imgs["written"]).mean()), 3)
    res["diff_ref_other"] = round(float(np.abs(imgs["ref"] - imgs["other"]).mean()), 3)
    res["settle_series"] = [[n, round(float(np.abs(imgs["ref"] - load(f)).mean()), 3)] for n, f in settle_series]
    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "projection"}, indent=1))
    for p in res["projection"]:
        print("d=%-3s a=%-5s b=%-5s engine=(%.4f, %.4f) model=(%.4f, %.4f) error px=%s" % (
            p["d"], p["a"], p["b"], p["engine"][0], p["engine"][1], p["model"][0], p["model"][1], p["err_px"]))


if __name__ == "__main__":
    main()
