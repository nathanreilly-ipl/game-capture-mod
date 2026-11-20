"""Finds where the engine keeps the rendered camera position, and tests which of
those copies changes the picture when written while the world is frozen.

    uv run --with numpy --with pillow tools/find_camera.py scan  --out reports/camfind
    uv run --with numpy --with pillow tools/find_camera.py write --out reports/camfind [--limit 60]

scan:  places the script camera at three poses, searches memory for the rendered
       position each time, keeps addresses that followed all three, and writes
       candidates.json with what surrounds each one (rotation-matrix check).
write: freezes the world, writes a new position into each candidate in turn,
       captures a frame, restores the bytes, and reports which writes moved the
       picture (image difference against a frozen baseline).
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

FOV = 50.0


def offset_pose(player, off, aim_height=0.5):
    pos = (player[0] + off[0], player[1] + off[1], player[2] + off[2])
    pitch, yaw = look_at(pos, (player[0], player[1], player[2] + aim_height))
    return pos, pitch, yaw


def matrix_check(proc, addr):
    """Looks for a rotation matrix stored just before a position (rage Mat34V style:
    right, forward, up, position, each 16 bytes) and reports what it finds."""
    report = {}
    for stride, name in ((16, "vec4_rows"), (12, "vec3_rows")):
        start = addr - 3 * stride
        raw = proc.read(start, 3 * stride)
        if not raw or len(raw) < 3 * stride:
            continue
        rows = [struct.unpack_from("<3f", raw, i * stride) for i in range(3)]
        m = np.array(rows, dtype=np.float64)
        norms = np.linalg.norm(m, axis=1)
        ortho = abs(float(m[0] @ m[1])) + abs(float(m[0] @ m[2])) + abs(float(m[1] @ m[2]))
        report[name] = {"rows": [[round(v, 5) for v in r] for r in rows],
                        "norms": [round(float(n), 5) for n in norms], "ortho_err": round(ortho, 5),
                        "is_rotation": bool(np.all(np.abs(norms - 1) < 1e-3) and ortho < 1e-3)}
    return report


def cmd_scan(args):
    os.makedirs(args.out, exist_ok=True)
    sess = CamSession()
    log = []
    try:
        player = vec(sess.state["player"])
        poses = [(6.0, 0.0, 1.5), (0.0, 6.0, 2.5), (-4.0, -4.0, 1.0), (3.0, -5.0, 3.0)]
        candidates = None
        with Process() as proc:
            for i, off in enumerate(poses):
                pos, pitch, yaw = offset_pose(player, off)
                sess.pose(pos, pitch, yaw, FOV)
                sess.cmd("wait", 20)
                st = sess.cmd("state")
                rendered = vec(st["rendered_pos"])
                if candidates is None:
                    t0 = time.time()
                    candidates, scanned = proc.scan_vec3(rendered)
                    line = "pose %d: rendered %s; scanned %.2f GB in %.1f s; %d matches" % (
                        i, rendered, scanned / 1e9, time.time() - t0, len(candidates))
                else:
                    kept = []
                    for a in candidates:
                        f = proc.read_floats(a, 3)
                        if f and all(abs(f[k] - rendered[k]) < 1e-3 for k in range(3)):
                            kept.append(a)
                    line = "pose %d: rendered %s; %d of %d still match" % (i, rendered, len(kept), len(candidates))
                    candidates = kept
                print(line, flush=True)
                log.append(line)
            out = []
            for a in candidates:
                out.append({"addr": hex(a), "addr_int": a, "around": matrix_check(proc, a)})
            # Copies stored as a camera matrix (rotation rows right before the position) first.
            out.sort(key=lambda c: (not any(v.get("is_rotation") for v in c["around"].values()), c["addr_int"]))
    finally:
        sess.end()
    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump({"log": log, "player": player, "candidates": out}, f, indent=1)
    with_rot = [c for c in out if any(v.get("is_rotation") for v in c["around"].values())]
    print("%d candidates, %d stored right after a rotation matrix:" % (len(out), len(with_rot)))
    for c in with_rot:
        print(" ", c["addr"], ",".join(k for k, v in c["around"].items() if v.get("is_rotation")))


def mean_diff(a_path, b_path):
    a = np.asarray(Image.open(a_path).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(b_path).convert("RGB"), dtype=np.int16)
    return float(np.abs(a - b).mean())


def cmd_write(args):
    with open(os.path.join(args.out, "candidates.json"), encoding="utf-8") as f:
        data = json.load(f)
    cands = [c["addr_int"] for c in data["candidates"]][: args.limit]
    sess = CamSession()
    results = []
    try:
        player = vec(sess.state["player"])
        pos, pitch, yaw = offset_pose(player, (6.0, 0.0, 1.5))
        sess.pose(pos, pitch, yaw, FOV)
        sess.cmd("wait", 30)
        sess.cmd("freeze")
        sess.cmd("wait", 30)
        base = sess.cmd("capture", "base")["file"]
        base2 = sess.cmd("capture", "base2")["file"]
        noise = mean_diff(base, base2)
        print("frozen baseline noise: %.3f" % noise, flush=True)
        # A different place: 6 m along -y, same height, which should change the picture a lot.
        new_pos = (player[0], player[1] - 6.0, player[2] + 1.5)
        with Process(write=True) as proc:
            for i, a in enumerate(cands):
                orig = proc.read(a, 12)
                if not orig:
                    continue
                proc.write_floats(a, new_pos)
                st = sess.cmd("wait", 5)
                shot = sess.cmd("capture", "cand_%02d" % i)["file"]
                after = proc.read_floats(a, 3)
                proc.write(a, orig)
                sess.cmd("wait", 5)
                d = mean_diff(base, shot)
                stuck = after is not None and all(abs(after[k] - new_pos[k]) < 1e-3 for k in range(3))
                r = {"i": i, "addr": hex(a), "diff": round(d, 3), "noise": round(noise, 3),
                     "write_stuck": stuck, "rendered_pos_after": st["rendered_pos"]}
                results.append(r)
                print("%2d %s diff %.3f (noise %.3f) write %s rendered %s" % (
                    i, hex(a), d, noise, "kept" if stuck else "overwritten", st["rendered_pos"]), flush=True)
        sess.cmd("unfreeze")
    finally:
        sess.end()
    with open(os.path.join(args.out, "write_results.json"), "w", encoding="utf-8") as f:
        json.dump({"job_dir": sess.job_dir, "results": results}, f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["scan", "write"])
    ap.add_argument("--out", default="reports/camfind")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    {"scan": cmd_scan, "write": cmd_write}[args.mode](args)


if __name__ == "__main__":
    main()
