"""The obstacle policy of the take loop, against a fake game (no game needed).

    uv run --project . python tests/test_obstacle_policy.py

1. Something holding a camera at the start of the take is deleted; the take completes.
2. Something walking into a camera early (before retake_before) raises Retake.
3. Something walking into a camera late is recorded; the take completes.
4. Something a game script owns holding a camera at the start raises Retake.
"""
import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.adapter import Adapter  # noqa: E402
from capture.runner import Retake, run_take  # noqa: E402

RIG_CAMS = 6  # cameras in the toy rig
FRAMES = 6


def toy_rig():
    """A ring of 6 static cameras 3 m around the origin, 1.5 m up, playing frames 1..6."""
    cams = []
    for k in range(RIG_CAMS):
        a = 2 * np.pi * k / RIG_CAMS
        pos = np.array([3 * np.cos(a), 1.5, 3 * np.sin(a)])
        fwd = -pos / np.linalg.norm(pos)
        right = np.cross([0, 1, 0], fwd)
        right /= np.linalg.norm(right)
        down = np.cross(fwd, right)
        c2w = np.eye(4)
        c2w[:3, 0], c2w[:3, 1], c2w[:3, 2], c2w[:3, 3] = right, down, fwd, pos
        cams.append({"name": "H_cam_%02d" % k, "group": "H_ring", "kind": "temporal", "w": 64, "h": 36,
                     "vfov_deg": 50.0, "time": {"mode": "play", "first": 1, "last": FRAMES}, "c2w": [c2w.tolist()],
                     "meta": {}})
    return {"schema": "camrig/v1", "rig": "toy", "fps": 30, "cameras": cams, "record": {"center_world": [0, 1, 0]}}


class FakeGame(Adapter):
    """World: Z up, rig +Y to world +Z. Obstacles appear per scenario."""
    name = "fake"
    capabilities = frozenset({"obstacles"})

    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario
        self.frame = 1
        self.deleted = set()
        self.listed = []

    def rig_rotation(self, facing_deg):
        return np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)

    def go_to(self, position, facing_deg):
        pass

    def ground_point(self, position):
        return list(position)

    def set_clock(self, hhmm):
        return hhmm

    def hide_subject(self, hidden):
        pass

    def begin_frozen(self, first_shot):
        self.frame = 1

    def set_camera(self, shot):
        self.cam = shot

    def capture(self, path, settle):
        Image.fromarray(np.full((36, 64, 3), (120, 90, 60), np.uint8)).save(path, format="BMP")
        return {"width": 64, "height": 36, "health": {"problems": []}}

    def advance(self, seconds):
        self.frame += 1
        return {"advanced_s": seconds}

    def instant(self):
        return self.frame

    def end_frozen(self):
        pass

    def render_settings(self):
        return {}

    def _box_at(self, cam_index, name, owned=False):
        a = 2 * np.pi * cam_index / RIG_CAMS
        # rig (3cos, 1.5, 3sin) -> world (3cos, -3sin, 1.5)
        return {"id": name, "kind": "human", "owned": owned, "center": [3 * np.cos(a), -3 * np.sin(a), 1.5],
                "axes": np.eye(3).tolist(), "half": [0.3, 0.3, 0.9], "approx": "obb"}

    def obstacles(self, center, radius):
        s, out = self.scenario, []
        if s.get("start_on_cam") is not None and "start" not in self.deleted:
            out.append(self._box_at(s["start_on_cam"], "start", owned=s.get("owned", False)))
        if s.get("walk_in_frame") and self.frame >= s["walk_in_frame"]:
            out.append(self._box_at(2, "walker"))
        # something nearby but clear of every camera
        out.append({"id": "bystander", "kind": "human", "owned": False, "center": [0, 0, 1.0],
                    "axes": np.eye(3).tolist(), "half": [0.3, 0.3, 0.9], "approx": "obb"})
        return out

    def remove_obstacles(self, ids):
        skipped = [i for i in ids if i == "start" and self.scenario.get("owned")]
        for i in ids:
            if i not in skipped:
                self.deleted.add(i)
        return {"removed": len(ids) - len(skipped), "skipped": skipped}


def run(scenario, **settings):
    job = {"id": "test", "location": {"id": "toy", "position": [0, 0, 0], "facing_deg": 0},
           "settings": dict({"clock": None}, **settings)}
    with tempfile.TemporaryDirectory() as d:
        game = FakeGame(scenario)
        rig_path = os.path.join(d, "rig.json")
        open(rig_path, "w").write("{}")
        return run_take(game, job, toy_rig(), rig_path, os.path.join(d, "take"), log=lambda *a: None), game


def main():
    take, game = run({"start_on_cam": 4})
    assert take["status"] == "captured" and take["cleared"]["removed"] == 1 and "start" in game.deleted, take
    assert "bystander" not in game.deleted
    print("1 ok: deleted at the start, take complete:", take["cleared"])

    try:
        run({"walk_in_frame": 2})
        raise AssertionError("expected a retake")
    except Retake as r:
        assert r.progress < 2 / 3
        print("2 ok: early walk-in ->", r)

    take, _ = run({"walk_in_frame": 6})
    assert take["status"] == "captured" and take["obstructions"] and take["obstructions"][0]["frame"] == 6, take
    print("3 ok: late walk-in recorded, take complete:", take["obstructions"])

    try:
        run({"start_on_cam": 1, "owned": True})
        raise AssertionError("expected a retake")
    except Retake as r:
        print("4 ok: script-owned at the start ->", r)

    take, _ = run({"walk_in_frame": 2}, obstacle_check=False)
    assert take["status"] == "captured" and not take["obstructions"]
    print("5 ok: --no-obstacle-check ignores it")


if __name__ == "__main__":
    main()
