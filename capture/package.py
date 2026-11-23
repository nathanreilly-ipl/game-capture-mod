"""Packages a captured take in the delivery layout the camera-rig repository's QC tools
read (gamecapture-camera-rigs-huixin/qc/stdm_view.py):

    <out>/render_metadata.json
    <out>/<production label>/rgb.mp4            e.g. SYN_StdmHNearTemporalCam_00
    <out>/<production label>/NNNN.camera.json   one per video frame

Each rig camera gets its frames from the shots that used it. Landscape and portrait
images are centre crops of the same render at full height (both keep the rig's vertical
field of view), scaled to the camera's size.

camera.json: transform_matrix is the OpenCV world-to-camera matrix in metres in the
"CV world" of the rig repo (rig frame with Y and Z negated: Y down), with the rig origin
at 0. fl_x, fl_y, cx, cy, w, h are pinhole intrinsics in pixels.
"""
import glob
import json
import math
import os
import shutil
import subprocess

import numpy as np
from PIL import Image

from .take import camera_uses, frame_paths, load
from .util import read_json, write_json

D4 = np.diag([1.0, -1.0, -1.0, 1.0])


def ffmpeg_exe():
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    if os.name != "nt":     # the machine's conda environment (capture/host: env_dir, `capture host setup`)
        from .host import proton
        return proton.tool("ffmpeg")
    found = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
                                   "Gyan.FFmpeg*", "*", "bin", "ffmpeg.exe"))
    return found[0] if found else None


def crop_scale(img, w, h):
    """Centre crop at full height to the aspect w:h, then scale to w x h."""
    W, H = img.size
    cw = int(round(H * w / h))
    if cw > W:
        raise ValueError("render %dx%d is too narrow for a %dx%d crop" % (W, H, w, h))
    left = (W - cw) // 2
    return img.crop((left, 0, left + cw, H)).resize((w, h), Image.LANCZOS)


def package(take_dir, out=None, crf=16, log=print):
    out = out or os.path.join(take_dir, "package")
    os.makedirs(out, exist_ok=True)
    take, shots = load(take_dir)
    rig = read_json(take["rig_file"])
    files = frame_paths(take_dir)
    ff = ffmpeg_exe()
    if not ff:
        raise RuntimeError("ffmpeg not found: put it on PATH or set FFMPEG")

    uses = camera_uses(shots)
    frames = [st["frame"] for st in shots["steps"]]
    render_size, upscaled = None, False
    written = []
    for cam in rig["cameras"]:
        entries = uses.get(cam["name"])
        if not entries:
            continue
        frozen = cam["time"]["mode"] == "frozen"
        entries.sort(key=lambda e: (e[1] if frozen else e[0]))
        label = cam.get("meta", {}).get("production_label", cam["name"])
        cdir = os.path.join(out, label)
        os.makedirs(cdir, exist_ok=True)
        w, h = cam["w"], cam["h"]
        fl = 0.5 * h / math.tan(math.radians(cam["vfov_deg"]) / 2)
        proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                 "-s", "%dx%d" % (w, h), "-r", str(rig.get("fps", 30)), "-i", "-",
                                 "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
                                 os.path.join(cdir, "rgb.mp4")], stdin=subprocess.PIPE)
        for k, (frame, pose_index, shot_id, _, _) in enumerate(entries):
            img = Image.open(files[shot_id]).convert("RGB")
            render_size = img.size
            upscaled = upscaled or img.size[1] < h
            proc.stdin.write(crop_scale(img, w, h).tobytes())
            c2w = np.asarray(cam["c2w"][pose_index], dtype=np.float64)
            w2c = np.linalg.inv(D4 @ c2w)
            with open(os.path.join(cdir, "%04d.camera.json" % k), "w", encoding="utf-8") as f:
                json.dump({"transform_matrix": w2c.tolist(), "w": w, "h": h, "fl_x": fl, "fl_y": fl,
                           "cx": w / 2, "cy": h / 2, "camera_model": "PINHOLE",
                           "clip_frame": frame, "pose_index": pose_index, "camera": cam["name"],
                           "source_shot": shot_id}, f)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed for " + label)
        written.append({"label": label, "camera": cam["name"], "frames": len(entries)})

    record = rig.get("record", {})
    location = take.get("location", {})
    meta = {
        "source": "capture_mod (%s)" % take.get("game"),
        "map_path": (take.get("game") or "").upper(),
        "fps": rig.get("fps", 30),
        "frame_range": [min(frames), max(frames)],
        "num_frames": max(frames) - min(frames) + 1,
        "location": [0.0, 0.0, 0.0],
        "persons": [],
        # As read by the rig repo's qc/stdm_view.py (checked with the 2026-11-19 sample).
        "camera_rigs": [{"type": rig["rig"], "record": record},
                        {"type": "zehao_traj", "record": record.get("zehao_traj")}],
        "world_note": "camera.json transform_matrix: OpenCV world-to-camera, metres, rig frame with Y and Z negated "
                      "(Y down), rig origin at 0. The rig origin sits on the game's ground at placement.origin_world.",
        "capture_location": {k: location.get(k) for k in ("id", "game", "position", "facing_deg")},
        "placement": take.get("placement"),
        "rig_source": take.get("rig_source"),
        "world_state_id": take.get("world_state_id"),
        "render": take.get("render"),
        "render_size": list(render_size) if render_size else None,
        "portrait_upscaled": upscaled,
        "sample": take.get("sample"),
        "cameras": written,
    }
    write_json(os.path.join(out, "render_metadata.json"), meta)
    log("%d cameras packaged into %s%s" % (len(written), out,
        "; portrait frames upscaled (render height %d)" % render_size[1] if upscaled else ""))
    return meta
