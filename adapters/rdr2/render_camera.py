"""The engine's render camera frame in RDR2's memory, written directly while the world
is frozen (photo-mode freeze ignores every script camera call).

Frame layout found 2026-11-19 (offsets from the position row; rows are 4 floats):
    -0x30 right, -0x20 forward, -0x10 up, +0x00 position, +0x30 vertical FoV (degrees)
The w lanes hold: right 0, forward fwd.z, up -up.z, position pos.x.

The frame's address changes every launch. calibrate() finds the copies of it by a memory
scan; pick_render_frame() keeps the copy the rendered camera follows (under the freeze).
"""
import math
import struct

import numpy as np

from .session import look_at, vec

FOV_OFFSET = 0x30
MATRIX_OFFSET = -0x30


def basis(pitch, yaw):
    """Right, forward, up for roll 0 in game axes (Z up), rotation order 2."""
    p, y = math.radians(pitch), math.radians(yaw)
    right = np.array([math.cos(y), math.sin(y), 0.0])
    fwd = np.array([-math.sin(y) * math.cos(p), math.cos(y) * math.cos(p), math.sin(p)])
    up = np.cross(right, fwd)
    return right, fwd, up


def pitch_yaw(fwd):
    """Pitch and yaw (degrees, rotation order 2) of a forward vector in game axes."""
    return math.degrees(math.asin(max(-1.0, min(1.0, fwd[2])))), math.degrees(math.atan2(-fwd[0], fwd[1]))


def frame_bytes(pos, right, fwd, up):
    """The 64-byte matrix as the engine stores it, including what it keeps in the w lanes."""
    rows = [(*right, 0.0), (*fwd, fwd[2]), (*up, -up[2]), (*pos, pos[0])]
    return struct.pack("<16f", *[float(v) for r in rows for v in r])


def calibrate(sess, proc, player):
    """Copies of the render camera frame: memory holding the rendered position, with the
    expected field of view and rotation, that also follows a second pose."""
    pos = (player[0] + 6.0, player[1], player[2] + 1.5)
    pitch, yaw = look_at(pos, (player[0], player[1], player[2] + 0.5))
    fov = 41.75  # an unusual value, so the FoV check is selective
    sess.pose(pos, pitch, yaw, fov)
    sess.cmd("wait", 20)
    st = sess.cmd("state")
    rendered = vec(st["rendered_pos"])
    hits, _ = proc.scan_vec3(rendered)
    r, f, u = basis(pitch, yaw)
    found = []
    for a in hits:
        fv = proc.read_floats(a + FOV_OFFSET, 1)
        m = proc.read_floats(a + MATRIX_OFFSET, 12)
        if not fv or not m or abs(fv[0] - fov) > 1e-3:
            continue
        got = np.array(m, dtype=np.float64).reshape(3, 4)[:, :3]
        if np.allclose(got, np.array([r, f, u]), atol=2e-3):
            found.append(a)
    pos2 = (player[0], player[1] + 6.0, player[2] + 2.5)
    pitch2, yaw2 = look_at(pos2, (player[0], player[1], player[2] + 0.5))
    sess.pose(pos2, pitch2, yaw2, fov)
    sess.cmd("wait", 20)
    rendered2 = vec(sess.cmd("state")["rendered_pos"])
    found = [a for a in found
             if all(abs(x - y) < 1e-3 for x, y in zip(proc.read_floats(a, 3) or (0, 0, 0), rendered2))]
    return found, len(hits)


def pick_render_frame(sess, proc, frames):
    """With the world frozen, nudges each copy's position and keeps the one the game
    then reports as the rendered camera position."""
    chosen = []
    for a in frames:
        orig = proc.read(a, 12)
        p = proc.read_floats(a, 3)
        before = vec(sess.cmd("state")["rendered_pos"])
        proc.write_floats(a, [p[0] + 2.0, p[1], p[2]])
        after = vec(sess.cmd("wait", 3)["rendered_pos"])
        proc.write(a, orig)
        sess.cmd("wait", 3)
        if abs(after[0] - before[0] - 2.0) < 1e-2:
            chosen.append(a)
    return chosen


def write_pose(proc, frame, pos, right, fwd, up, vfov_deg):
    proc.write(frame + MATRIX_OFFSET, frame_bytes(np.asarray(pos), np.asarray(right), np.asarray(fwd), np.asarray(up)))
    proc.write_floats(frame + FOV_OFFSET, [float(vfov_deg)])
