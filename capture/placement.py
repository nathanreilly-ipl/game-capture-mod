"""Puts a rig into a game world.

Rig frame (camrig/v1): metres, right-handed, +Y up, floor at y = 0, the subject at the
origin facing +Z; cameras are OpenCV camera-to-world matrices (x right, y down, z forward).

A placement is a rotation R (rig frame -> world frame, supplied by the game adapter from
the location's facing, so it carries the game's axis convention) and the world point the
rig origin goes to (the ground under the location). A rig point p maps to
    world = R @ p + origin
"""
import numpy as np


class Placement:
    def __init__(self, origin, rotation):
        self.origin = np.asarray(origin, dtype=np.float64)
        self.R = np.asarray(rotation, dtype=np.float64)

    def point(self, p):
        return self.R @ np.asarray(p, dtype=np.float64) + self.origin

    def camera(self, c2w):
        """OpenCV c2w in the rig frame -> right, forward, up, position in the world."""
        m = np.asarray(c2w, dtype=np.float64)
        return self.R @ m[:3, 0], self.R @ m[:3, 2], self.R @ -m[:3, 1], self.R @ m[:3, 3] + self.origin

    def to_json(self):
        return {"origin_world": self.origin.tolist(), "rig_to_world_rotation": self.R.tolist(),
                "note": "world = R @ rig + origin_world; rig: metres, +Y up, subject at 0 facing +Z"}
