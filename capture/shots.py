"""A rig's shot list: the distinct renders a take needs.

One shot per (clip frame, distinct pose, field of view). Cameras with the same pose and
field of view at the same clip frame share a shot (e.g. a landscape and a portrait camera
on the same ring slot; the packager crops both from it).

Clip frames: a `play` camera contributes a pose at each frame of its range (one pose for
a static camera, or one per frame); a `frozen` camera contributes all its poses at its one
frame (sweeps, trajectories).

Shot ids come from what the shot is, not from where it sits in a take: clip frame, pose in
the rig frame, field of view. The same shot has the same id in any take and any edited
copy of the rig, which a shot cache can key on (BACKLOG.md).
"""
import hashlib
import math

import numpy as np

SCHEMA = "capture_shot_list/v1"
FROZEN_KINDS = ("sweep", "trajectory")


def shot_id(frame, c2w, vfov_deg):
    m = np.round(np.asarray(c2w, dtype=np.float64)[:3, :4], 5) + 0.0  # + 0.0 turns -0.0 into 0.0
    text = "%d|%.4f|%s" % (frame, round(float(vfov_deg), 4) + 0.0, ",".join("%.5f" % v for v in m.ravel()))
    return "t%03d_%s" % (frame, hashlib.sha1(text.encode()).hexdigest()[:12])


def _strip_orientation(name):
    return name[2:] if name[:2] in ("H_", "V_") else name


def build(rig, placement):
    centre = placement.point(rig.get("record", {}).get("center_world", [0, 0, 0]))
    shots = {}

    def add(frame, cam, pose_index, c2w):
        sid = shot_id(frame, c2w, cam["vfov_deg"])
        shot = shots.get(sid)
        if shot is None:
            right, fwd, up, pos = placement.camera(c2w)
            shot = shots[sid] = {
                "id": sid,
                "name": "t%03d_%s_%03d" % (frame, _strip_orientation(cam["name"]), pose_index),
                "frame": frame, "group": _strip_orientation(cam["group"]), "kind": cam["kind"],
                "vfov_deg": cam["vfov_deg"],
                "pos": pos.tolist(), "right": right.tolist(), "fwd": fwd.tolist(), "up": up.tolist(),
                "uses": [],
            }
        shot["uses"].append({"camera": cam["name"],
                             "label": cam.get("meta", {}).get("production_label", cam["name"]),
                             "pose_index": pose_index, "w": cam["w"], "h": cam["h"]})

    for cam in rig["cameras"]:
        t = cam["time"]
        poses = cam["c2w"]
        if t["mode"] == "play":
            for frame in range(t["first"], t["last"] + 1):
                k = frame - t["first"] if len(poses) > 1 else 0
                add(frame, cam, k, poses[k])
        elif t["mode"] == "frozen":
            for k, c2w in enumerate(poses):
                add(t["frame"], cam, k, c2w)
        else:
            raise ValueError("unknown time mode %r for %s" % (t["mode"], cam["name"]))

    by_frame = {}
    for shot in shots.values():
        by_frame.setdefault(shot["frame"], []).append(shot)

    def order(shot):
        # Playing cameras first, round the rig centre so consecutive shots are close;
        # then each sweep in its own pose order.
        if shot["kind"] in FROZEN_KINDS:
            u = shot["uses"][0]
            return (1, shot["group"], u["camera"], u["pose_index"], 0.0)
        return (0, "", "", 0, math.atan2(shot["pos"][1] - centre[1], shot["pos"][0] - centre[0]))

    steps = [{"frame": f, "shots": sorted(by_frame[f], key=order)} for f in sorted(by_frame)]
    return {
        "schema": SCHEMA,
        "rig": rig.get("rig"), "rig_title": rig.get("title"), "fps": rig.get("fps", 30), "seed": rig.get("seed"),
        "placement": dict(placement.to_json(), rig_center_world=centre.tolist()),
        "n_shots": len(shots), "n_camera_frames": sum(len(s["uses"]) for s in shots.values()),
        "steps": steps,
    }


def subset(shots, last_frame=0, sweep_stride=1):
    """Keeps clip frames up to last_frame (0 = all) and every sweep_stride-th pose of the
    frozen sweeps and trajectories. For samples and tests."""
    if not last_frame and sweep_stride <= 1:
        return shots
    steps = []
    for st in shots["steps"]:
        if last_frame and st["frame"] > last_frame:
            continue
        kept = []
        for s in st["shots"]:
            uses = [u for u in s["uses"] if s["kind"] not in FROZEN_KINDS or u["pose_index"] % sweep_stride == 0]
            if uses:
                kept.append(dict(s, uses=uses))
        steps.append({"frame": st["frame"], "shots": kept})
    out = dict(shots, steps=steps)
    out["n_shots"] = sum(len(st["shots"]) for st in steps)
    out["n_camera_frames"] = sum(len(s["uses"]) for st in steps for s in st["shots"])
    out["sample"] = {"last_frame": last_frame, "sweep_stride": sweep_stride}
    return out
