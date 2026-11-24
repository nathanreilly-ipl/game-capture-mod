"""A clip to look at: cloth and people through time steps beside the same world running unbroken.

    uv run --project . python -m adapters.witcher3.probes.cloth_clip_probe [--frames 30]

Left: the world running on at a time scale of 0.1, a frame taken every 1/30 s of game time (its
natural motion, the reference). Right: the world held with the capture method (our pause, the
photo mode's camera) and stepped by 1/30 s between frames with even steps (cm_stepe), each frame
after the settle a shot gets. Both from the same pose at Hierarch Square, one after the other.
Writes out/probes/witcher3/cloth_clip/side_by_side.mp4 (10 frames/s, a third of real speed) and
the per-frame mean change in an awning box and over the frame for both.
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np

from capture import paths as capture_paths
from capture.package import ffmpeg_exe

from ...common import frames
from .. import paths
from ..session import Session, parse_kv
from .cloth_step_probe import load, shot

AWNING = (180, 230, 430, 400)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="654.6,1871.1,11.6,-6,16")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--step-frames", type=int, default=8)
    a = ap.parse_args()
    from PIL import Image
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "cloth_clip")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, yaw)
    time.sleep(12)
    play, steps = [], []
    report = {}
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        frames.wait(ex, 150)
        fps = frames.frame_rate(ex, 1.0)
        # the reference: the world running at 0.1, a frame every 1/30 s of game time
        gap = max(2, int(round(fps * (1.0 / 30) / 0.1)))
        s.cmd("timescale", 0.1)
        s.cmd("pause", 0)
        time.sleep(1.5 + s.console_clear_in())
        last = None
        game_ms = []
        for k in range(a.frames):
            r = frames.shoot(ex, "cloth_clip/play_%02d" % k, after=gap)
            play.append(load(r["path"]))
            os.remove(r["path"])
            if last is not None:
                game_ms.append((int(r["time_ms"]) - last) * 0.1)
            last = int(r["time_ms"])
        s.cmd("pause", 1)
        s.cmd("timescale", -1)
        report["play_game_ms_between_frames"] = [round(float(np.min(game_ms)), 1), round(float(np.mean(game_ms)), 1), round(float(np.max(game_ms)), 1)]
        # the capture method: held, stepped by even 1/30 s steps
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        frame_s = round(1.0 / max(1.0, fps), 5)
        steps.append(shot(s, ex, "step_00", out, settle=150))
        advanced = []
        debt = 0.0
        for k in range(1, a.frames):
            mark = s.log_size()
            r = s.cmd("stepe", 1.0 / 30 + debt, a.step_frames, frame_s)
            got = parse_kv(s.wait_line("t", r.seq, mark, timeout=30.0) or "")
            adv = float(got.get("advanced", 0))
            debt = 1.0 / 30 + debt - adv
            advanced.append(adv)
            if float(got.get("frame_s", 0) or 0) > 0.001:
                frame_s = float(got["frame_s"])
            s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
            steps.append(shot(s, ex, "step_%02d" % k, out))
        report["step_ms"] = [round(1000 * min(advanced), 3), round(1000 * float(np.mean(advanced)), 4), round(1000 * max(advanced), 3)]
        report["step_total_off_ms"] = round(1000 * (sum(advanced) - (a.frames - 1) / 30.0), 4)
    finally:
        s.cmd("timescale", -1)
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)

    def change(seq):
        x0, y0, x1, y1 = AWNING
        aw = [float(np.abs(p[y0:y1, x0:x1] - q[y0:y1, x0:x1]).mean()) for p, q in zip(seq, seq[1:])]
        fr = [float(np.abs(p - q).mean()) for p, q in zip(seq, seq[1:])]
        return {"awning_mean": round(float(np.mean(aw)), 3), "awning_max": round(float(np.max(aw)), 3),
                "frame_mean": round(float(np.mean(fr)), 3), "awning_per_frame": [round(v, 2) for v in aw]}

    report["play"] = change(play)
    report["steps"] = change(steps)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({k: v for k, v in report.items()}, indent=1))
    # side by side: whole frames at 640x360 over awning crops at 2x, labelled
    from PIL import ImageDraw
    tmp = os.path.join(out, "sbs")
    os.makedirs(tmp, exist_ok=True)
    x0, y0, x1, y1 = AWNING
    for k, (p, q) in enumerate(zip(play, steps)):
        canvas = Image.new("RGB", (1280, 360 + 340))
        for i, img in enumerate((p, q)):
            im = Image.fromarray(img.astype(np.uint8))
            canvas.paste(im.resize((640, 360)), (i * 640, 0))
            canvas.paste(im.crop((x0, y0, x1, y1)).resize((500, 340)), (i * 640 + 70, 360))
        d = ImageDraw.Draw(canvas)
        d.text((8, 8), "world running at 0.1, every 1/30 s of game time  #%d" % k, fill=(255, 255, 0))
        d.text((648, 8), "held + even 1/30 s steps (capture method)  #%d" % k, fill=(255, 255, 0))
        canvas.save(os.path.join(tmp, "f%03d.png" % k))
    video = os.path.join(out, "side_by_side.mp4")
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", "10", "-i", os.path.join(tmp, "f%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", video], check=True)
    print("video:", video)


if __name__ == "__main__":
    main()
