"""Cameras inside or right against a moving thing (person, animal, vehicle).

An adapter with the "obstacles" capability lists what moves near the rig as oriented boxes:
    {"id": <adapter's handle>, "kind": "human" | "animal" | "vehicle", "owned": bool,
     "center": [x, y, z], "axes": [[ax], [ay], [az]] (unit vectors, rows), "half": [a, b, c]}
A camera position is a hit when it lies inside the box grown by the margin on every side.

Policy (capture/runner.py):
- At the start of a take, with the world frozen at its first clip frame, anything that holds
  any camera position of the take is deleted, with what belongs to it; nothing is deleted later.
- Before each clip frame's shots, a hit on any of that frame's cameras stops the take for a
  retake when less than retake_before of its shots are captured; later, the take is finished
  and the hit shots are marked.
"""
import math

import numpy as np


def obb_from_aabb(aabb_min, aabb_max, fwd_xy):
    """Oriented box of an upright entity from its world-axis-aligned box and its heading.
    A rectangle with half extents a (right), b (forward) rotated by t has AABB half widths
    wx = a|cos t| + b|sin t|, wy = a|sin t| + b|cos t|. Near 45 degrees a and b cannot be told
    apart; then the AABB itself is returned (it can only be larger than the entity)."""
    mn, mx = np.asarray(aabb_min, float), np.asarray(aabb_max, float)
    center = (mn + mx) / 2
    wx, wy, hz = (mx - mn) / 2
    f = np.array([fwd_xy[0], fwd_xy[1], 0.0])
    n = np.linalg.norm(f)
    if n < 1e-6:
        return {"center": center.tolist(), "axes": np.eye(3).tolist(), "half": [wx, wy, hz], "approx": "aabb"}
    f /= n
    r = np.array([f[1], -f[0], 0.0])  # right of forward, Z up
    c, s = abs(r[0]), abs(r[1])       # |cos t|, |sin t| of the right axis against world X
    det = c * c - s * s
    if abs(det) < 0.25:
        return {"center": center.tolist(), "axes": np.eye(3).tolist(), "half": [wx, wy, hz], "approx": "aabb"}
    a = (wx * c - wy * s) / det
    b = (wy * c - wx * s) / det
    if a <= 0 or b <= 0:
        return {"center": center.tolist(), "axes": np.eye(3).tolist(), "half": [wx, wy, hz], "approx": "aabb"}
    return {"center": center.tolist(), "axes": [r.tolist(), f.tolist(), [0.0, 0.0, 1.0]], "half": [a, b, hz],
            "approx": "obb"}


def hits(obstacles, points, margin):
    """{obstacle index: [point indices inside it]} for camera positions (N x 3)."""
    pts = np.asarray(points, float).reshape(-1, 3)
    out = {}
    for k, o in enumerate(obstacles):
        local = (pts - np.asarray(o["center"])) @ np.asarray(o["axes"]).T
        inside = np.all(np.abs(local) <= np.asarray(o["half"]) + margin, axis=1)
        idx = np.nonzero(inside)[0]
        if len(idx):
            out[k] = idx.tolist()
    return out


def reach(points, center):
    """Distance from center to the farthest camera position."""
    pts = np.asarray(points, float).reshape(-1, 3)
    return float(np.max(np.linalg.norm(pts - np.asarray(center), axis=1))) if len(pts) else 0.0


def _selftest():
    # a 2.5 m long horse (b = 1.25), 0.4 wide (a = 0.2), turned 30 degrees; its AABB and heading
    t = math.radians(30)
    r = np.array([math.cos(t), math.sin(t), 0])
    f = np.array([-math.sin(t), math.cos(t), 0])
    a, b, h = 0.2, 1.25, 1.0
    corners = np.array([sx * a * r + sy * b * f for sx in (-1, 1) for sy in (-1, 1)])
    mn = np.append(corners.min(0)[:2], -h) + np.array([10, 20, 1])
    mx = np.append(corners.max(0)[:2], h) + np.array([10, 20, 1])
    o = obb_from_aabb(mn, mx, f[:2])
    assert o["approx"] == "obb" and np.allclose(o["half"], [a, b, h]), o
    on_body = np.array([10, 20, 1]) + 1.2 * f          # near its nose: inside
    beside = np.array([10, 20, 1]) + 0.5 * r            # 0.3 m beside its flank: outside at margin 0.15
    corner_gap = np.array([10, 20, 1]) + 1.0 * f + 0.5 * r  # inside the AABB, outside the body
    hit = hits([o], [on_body, beside, corner_gap], 0.15)
    assert hit == {0: [0]}, hit
    return "ok"


if __name__ == "__main__":
    print(_selftest())
