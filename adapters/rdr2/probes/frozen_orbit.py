"""Drift-free orbit: freezes the world once, then writes each camera pose straight
into the engine's render camera frame and captures it.

    uv run --with numpy --with pillow adapters/rdr2/probes/frozen_orbit.py [--count 12] [--radius 5] [--height 1.5]

Steps:
 1. calibrate: find the render camera frame for this game session (memory scan for
    the rendered position, keep the copy whose field of view and rotation layout match).
 2. freeze, then for each pose: write matrix + field of view, wait, capture.
    The first pose is captured again at the end to prove the world did not move.
 3. unfreeze and render a few of the same poses with a normal script camera, for
    comparison with the written ones.

Camera frame layout found 2026-11-19 (offsets from the position row):
    -0x30 right, -0x20 forward, -0x10 up, +0x00 position (each 4 floats), +0x30 vertical FoV (deg)
"""
import argparse
import json
import math
import os
import struct
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.session import CamSession, look_at, vec  # noqa: E402
from adapters.rdr2.mem import Process  # noqa: E402
from adapters.rdr2.render_camera import FOV_OFFSET, basis, calibrate, frame_bytes, pick_render_frame  # noqa: E402,F401


def mean_diff(a_path, b_path):
    a = np.asarray(Image.open(a_path).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(b_path).convert("RGB"), dtype=np.int16)
    return float(np.abs(a - b).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--radius", type=float, default=5.0)
    ap.add_argument("--height", type=float, default=1.5)
    ap.add_argument("--aim", type=float, default=0.9, help="look-at height above the player's origin")
    ap.add_argument("--fov", type=float, default=50.0)
    ap.add_argument("--settle", type=int, default=8, help="ticks to wait after each write")
    ap.add_argument("--live-checks", type=int, default=3)
    ap.add_argument("--out", default="reports/frozen_orbit")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sess = CamSession()
    summary = {"job_dir": sess.job_dir}
    try:
        player = vec(sess.state["player"])
        target = (player[0], player[1], player[2] + args.aim)
        poses = []
        for k in range(args.count):
            a = 2 * math.pi * k / args.count
            pos = (player[0] + args.radius * math.cos(a), player[1] + args.radius * math.sin(a), player[2] + args.height)
            pitch, yaw = look_at(pos, target)
            poses.append((pos, pitch, yaw))

        with Process(write=True) as proc:
            t0 = time.time()
            found, n_hits = calibrate(sess, proc, player)
            print("calibration: %d position matches, %d camera frames (%.1f s)" % (
                n_hits, len(found), time.time() - t0), flush=True)

            # Start from the first pose with the normal camera, then freeze the world.
            sess.pose(*poses[0], args.fov)
            sess.cmd("wait", 30)
            sess.cmd("freeze")
            sess.cmd("wait", 30)

            chosen = pick_render_frame(sess, proc, found)
            print("render camera frame: %s" % [hex(a) for a in chosen], flush=True)
            if len(chosen) != 1:
                sess.cmd("unfreeze")
                raise SystemExit("expected exactly one render camera frame")
            frame = chosen[0]
            summary["frame_addr"] = hex(frame)
            summary["frame_copies"] = [hex(a) for a in found]

            t0 = time.time()
            shots = []
            for k, (pos, pitch, yaw) in enumerate(poses):
                r, f, u = basis(pitch, yaw)
                proc.write(frame - 0x30, frame_bytes(pos, r, f, u))
                proc.write_floats(frame + FOV_OFFSET, [args.fov])
                sess.cmd("wait", args.settle)
                st = sess.cmd("capture", "orbit_%02d" % k)
                shots.append(st["file"])
                print("pose %2d written, rendered %s" % (k, st["rendered_pos"]), flush=True)
            # First pose again: any difference to orbit_00 is world motion or render noise.
            r, f, u = basis(poses[0][1], poses[0][2])
            proc.write(frame - 0x30, frame_bytes(poses[0][0], r, f, u))
            sess.cmd("wait", args.settle)
            again = sess.cmd("capture", "orbit_00_again")["file"]
            summary["orbit_seconds"] = round(time.time() - t0, 2)
            summary["orbit_00_repeat_diff"] = round(mean_diff(shots[0], again), 3)
            print("orbit took %.1f s; first pose repeated, mean diff %.3f" % (
                summary["orbit_seconds"], summary["orbit_00_repeat_diff"]), flush=True)
            sess.cmd("unfreeze")

        # The same poses with an ordinary script camera (world running), for comparison.
        checks = []
        step = max(1, args.count // max(1, args.live_checks))
        for k in range(0, args.count, step)[: args.live_checks]:
            sess.pose(*poses[k], args.fov)
            sess.cmd("wait", 30)
            live = sess.cmd("capture", "live_%02d" % k)["file"]
            other = shots[(k + 1) % args.count]
            checks.append({"pose": k, "diff_same_pose": round(mean_diff(shots[k], live), 3),
                           "diff_next_pose": round(mean_diff(other, live), 3)})
            print("pose %2d: written vs live %.3f; next pose vs live %.3f" % (
                k, checks[-1]["diff_same_pose"], checks[-1]["diff_next_pose"]), flush=True)
        summary["live_checks"] = checks
    finally:
        sess.end()
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)


if __name__ == "__main__":
    main()
