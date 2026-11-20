"""Reading a captured take.

A take directory holds:
    take.json           job, location, rig, placement, settings, world state id, timing, status
    shots.json          the shot list that was captured (world coordinates)
    capture_log.jsonl   one line per captured shot: shot id, file, health, timing
    steps.jsonl         one line per time step
    raw/                the frames

Frames are found by shot id through the capture log (frame_paths), never by assuming a
file name, so a take can later draw shots from a cache (BACKLOG.md: shot reuse).
"""
import json
import os

from .util import read_json


def load(take_dir):
    return read_json(os.path.join(take_dir, "take.json")), read_json(os.path.join(take_dir, "shots.json"))


def frame_paths(take_dir):
    """shot id -> absolute path of its frame. The last capture of a shot wins."""
    out = {}
    with open(os.path.join(take_dir, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("accepted", True):
                p = r["file"]
                out[r["id"]] = p if os.path.isabs(p) else os.path.join(take_dir, p)
    return out


def camera_uses(shots):
    """camera name -> [(clip frame, pose index, shot id, w, h)]"""
    uses = {}
    for st in shots["steps"]:
        for s in st["shots"]:
            for u in s["uses"]:
                uses.setdefault(u["camera"], []).append((st["frame"], u["pose_index"], s["id"], u["w"], u["h"]))
    return uses
