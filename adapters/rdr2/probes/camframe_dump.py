"""Dumps the memory around the camera position the renderer uses, for two known
script-camera poses, so the layout (rotation rows, field of view) can be read off.

    uv run --with numpy tools/camframe_dump.py 0x202c4413f00
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.session import CamSession, look_at, vec  # noqa: E402
from adapters.rdr2.mem import Process  # noqa: E402

BEFORE, AFTER = 0x100, 0x200


def basis(pitch, yaw):
    """Right, forward, up of a camera with roll 0 (game: Z up, yaw about Z, rotation order 2)."""
    p, y = math.radians(pitch), math.radians(yaw)
    fwd = (-math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), math.sin(p))
    right = (math.cos(y), math.sin(y), 0.0)
    up = (fwd[1] * right[2] - fwd[2] * right[1], fwd[2] * right[0] - fwd[0] * right[2], fwd[0] * right[1] - fwd[1] * right[0])
    up = tuple(-u for u in up) if up[2] < 0 else up
    return right, fwd, up


def main():
    addr = int(sys.argv[1], 16)
    sess = CamSession()
    dumps = []
    try:
        player = vec(sess.state["player"])
        poses = [((6.0, 0.0, 1.5), 37.5), ((0.0, 6.0, 3.0), 61.25)]
        with Process() as proc:
            for off, fov in poses:
                pos = (player[0] + off[0], player[1] + off[1], player[2] + off[2])
                pitch, yaw = look_at(pos, (player[0], player[1], player[2] + 0.5))
                sess.pose(pos, pitch, yaw, fov)
                sess.cmd("wait", 20)
                st = sess.cmd("state")
                raw = proc.read(addr - BEFORE, BEFORE + AFTER)
                floats = struct.unpack("<%df" % ((BEFORE + AFTER) // 4), raw)
                dumps.append((pos, pitch, yaw, fov, st, floats))
    finally:
        sess.end()

    for pos, pitch, yaw, fov, st, _ in dumps:
        r, f, u = basis(pitch, yaw)
        print("pose pos=%s pitch=%.4f yaw=%.4f fov=%.3f rendered_rot=%s rendered_fov=%s" % (
            tuple(round(v, 4) for v in pos), pitch, yaw, fov, st["rendered_rot"], st["rendered_fov"]))
        print("  expected right=%s fwd=%s up=%s" % tuple(tuple(round(v, 4) for v in w) for w in (r, f, u)))
    print("offset  " + "  ".join("pose%d" % i for i in range(len(dumps))))
    n = (BEFORE + AFTER) // 4
    for i in range(n):
        vals = [d[5][i] for d in dumps]
        if all(v == 0 for v in vals):
            continue
        rel = i * 4 - BEFORE
        mark = " *" if vals[0] != vals[1] else ""
        print("%+6d  %s%s" % (rel, "  ".join("%14.6g" % v for v in vals), mark))


if __name__ == "__main__":
    main()
