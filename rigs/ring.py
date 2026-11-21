"""A simple example provider: one ring of static cameras around the subject, looking at it.

The ring starts at radius_m and shrinks in 0.25 m steps until every camera is at least
clearance_m from the scene (the ray hits around the location); if no radius down to min_radius_m
fits, the location is declined. Use it as a template for a new rig format.

    capture submit --provider ring --set count=16 --set radius_m=4 --location <id>
"""
import math

import numpy as np

from capture.providers import Declined

KEY = "ring"
TITLE = "Example: a ring of static cameras, shrunk to clear the scene"
NEEDS_SCENE = True
DEFAULTS = {"count": 16, "radius_m": 4.0, "min_radius_m": 2.0, "height_m": 1.6, "look_height_m": 1.0,
            "vfov_deg": 50.0, "w": 1344, "h": 768, "first": 1, "last": 30, "clearance_m": 0.5}


def _c2w(pos, target):
    fwd = np.asarray(target, float) - pos
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)  # OpenCV: x right, y down, z forward
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = right, down, fwd, pos
    return m


def _positions(s, r):
    return [np.array([r * math.sin(2 * math.pi * k / s["count"]), s["height_m"], r * math.cos(2 * math.pi * k / s["count"])])
            for k in range(int(s["count"]))]


def solve(scene, subject, s):
    pts = np.asarray(scene.points, float).reshape(-1, 3) if scene is not None else np.zeros((0, 3))
    r, effects = float(s["radius_m"]), []
    while r >= float(s["min_radius_m"]) - 1e-9:
        cams = _positions(s, r)
        if not len(pts) or min(np.min(np.linalg.norm(pts - c, axis=1)) for c in cams) >= s["clearance_m"]:
            break
        r -= 0.25
    else:
        raise Declined("no ring from %.2f m down to %.2f m keeps %.2f m from the scene"
                       % (s["radius_m"], s["min_radius_m"], s["clearance_m"]))
    if r < s["radius_m"]:
        effects.append("ring shrunk %.2f -> %.2f m to clear the scene" % (s["radius_m"], r))
    target = [0.0, s["look_height_m"], 0.0]
    fl = 0.5 * s["h"] / math.tan(math.radians(s["vfov_deg"]) / 2)
    cameras = [{"name": "ring_%02d" % k, "group": "ring", "kind": "temporal", "w": s["w"], "h": s["h"],
                "fx": fl, "fy": fl, "cx": s["w"] / 2, "cy": s["h"] / 2, "vfov_deg": s["vfov_deg"],
                "time": {"mode": "play", "first": int(s["first"]), "last": int(s["last"])},
                "c2w": [_c2w(p, target).tolist()], "meta": {"slot": k}}
               for k, p in enumerate(_positions(s, r))]
    return {"schema": "camrig/v1", "rig": KEY, "title": TITLE, "owner": "capture_mod",
            "world": {"units": "m", "up": [0, 1, 0], "handedness": "right"}, "camera_convention": "opencv_c2w",
            "fps": 30.0, "clip_frames": int(s["last"]), "seed": 0, "cameras": cameras,
            "record": {"center_world": target, "radius_m": r, "settings": dict(s),
                       "scene_fit": {"effects": effects, "scene": scene.name if scene else "none"}}}
