"""Do people and cloth move continuously through time steps? (Nathan saw cloth reset at every cm_stepw
and "fall into" a new position, 2026-11-23.)

    uv run --project . python -m adapters.witcher3.probes.cloth_step_probe [--pose x,y,z,pitch,yaw]
        [--steps 6] [--phases photo,pcam,game]

At a view with cloth and people (Hierarch Square: awnings, banners, robes), one frame after each of
these, compared with the frame before it (mean difference in levels of 255, share of pixels off by
more than 24; frames and difference maps x4 under out/probes/witcher3/cloth_step/, report.json):

photo   the world held by the photo mode and our pause (the method until 2026-11-23):
        held (nothing, 2 s), toggle (the photo mode off and on, no time passing), stepw (1/30 s steps
        with the photo mode off for each), then a settle series after one more step
pcam    the world held by our pause alone, the photo mode's camera made the rendered camera without
        the photo mode (cm_pcam): its drift while held, held, stepw with the photo mode never
        touched, the settle series, and the field of view
game    the same with the game's own camera (cm_gpose): it carries an offset and drifts while held

The settle series: right after a step, frames 2, 10, 30, 60 and 120 frames later with the world held.
Anything that changes between them moves in a held world (cloth falling after a reset does).
"""
import argparse
import json
import os
import time

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, parse_kv, vec


def load(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB").resize((1280, 720), Image.BOX), dtype=np.float32)


def shot(s, ex, name, out, settle=60):
    from PIL import Image
    for _ in range(3):
        time.sleep(s.console_clear_in())
        r = frames.shoot(ex, "cloth_step/" + name, after=settle)
        if not s._settle_console(s.hwnd()):        # the console was in the picture: closed, shot again
            break
        settle = max(settle, 10)
    a = load(r["path"])
    os.remove(r["path"])
    Image.fromarray(a.astype(np.uint8)).save(os.path.join(out, name + ".jpg"), quality=90)
    return a


def compare(a, b, out, name):
    from PIL import Image
    d = np.abs(a - b)
    m = d.max(axis=2)
    Image.fromarray(np.clip(m * 4, 0, 255).astype(np.uint8)).save(os.path.join(out, name + "_diff_x4.png"))
    return {"mean": round(float(d.mean()), 3), "over_24_pct": round(100 * float((m > 24).mean()), 3)}


def stepw(s, keep=0):
    mark = s.log_size()
    r = s.cmd("stepw", 1.0 / 30, keep)
    done = s.wait_line("t", r.seq, mark, timeout=30.0)
    if done is None:
        raise SystemExit("a step did not end")
    return parse_kv(done)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="654.6,1871.1,11.6,-6,16")       # Hierarch Square: stalls, awnings, banners
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--phases", default="photo,pcam")
    a = ap.parse_args()
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")]
    phases = a.phases.split(",")
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "cloth_step")
    os.makedirs(out, exist_ok=True)
    rows = []
    prev = None

    def cam_off():
        st = s.state()
        cam = vec(st.get("cam", "0,0,0"))
        return round(float(np.linalg.norm(np.array(cam) - np.array([x, y, z]))), 4), st

    def record(name, kind, extra=None, settle=60):
        nonlocal prev
        img = shot(s, ex, name, out, settle=settle)
        row = dict(compare(prev, img, out, name), kind=kind, name=name, **(extra or {}))
        rows.append(row)
        print("%-16s mean %6.3f, %6.3f%% over 24 %s" % (name, row["mean"], row["over_24_pct"],
                                                        json.dumps(extra) if extra else ""))
        prev = img

    def series(tag, keep):
        stepw(s, keep)
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        for n, wait in ((2, 2), (10, 8), (30, 20), (60, 30), (120, 60)):
            record("%s_series_%03d" % (tag, n), tag + "_series", settle=wait)

    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, yaw)
    time.sleep(12)
    try:
        s.cmd("hide", 1)
        if "photo" in phases:
            s.cmd("freeze")
            s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
            prev = shot(s, ex, "photo_start", out, settle=150)
            for k in range(2):
                time.sleep(2.0)
                record("photo_held_%d" % k, "photo_held")
            for k in range(a.steps):
                got = stepw(s)
                s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
                record("photo_stepw_%d" % k, "photo_stepw", got)
            series("photo", 0)
            for k in range(2):
                s.cmd("photo", 0)
                s.cmd("photo", 1)
                s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
                record("photo_toggle_%d" % k, "photo_toggle")
            s.cmd("unfreeze")
            time.sleep(3.0)          # people back to their own animation before the next phase
        if "pcam" in phases:
            s.cmd("photo", 0)
            s.cmd("pause", 1)
            s.cmd("pcam", 1)
            s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
            d0, st = cam_off()
            prev = shot(s, ex, "pcam_start", out, settle=150)
            d1, st = cam_off()
            print("photo-mode camera without the photo mode: %.4f m off the pose at once, %.4f m 150 frames later; pm=%s held=%s fov=%s"
                  % (d0, d1, st.get("pm"), st.get("held"), st.get("fov")))
            rows.append({"kind": "pcam_drift", "at_once_m": d0, "after_150_m": d1, "pm": st.get("pm"), "fov": st.get("fov")})
            for k in range(2):
                time.sleep(2.0)
                record("pcam_held_%d" % k, "pcam_held")
            for k in range(a.steps):
                got = stepw(s, keep=1)
                d, st = cam_off()
                got.update(cam_off_m=d, pm=st.get("pm"), held=st.get("held"))
                s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
                record("pcam_stepw_%d" % k, "pcam_stepw", got)
            series("pcam", 1)
            for fov in (40, 75):
                s.cmd("pose", x, y, z, pitch, yaw, 0, fov)
                frames.wait(ex, 30)
                st = s.state()
                print("asked fov %d: state fov %s, cam %s" % (fov, st.get("fov"), st.get("cam")))
                rows.append({"kind": "pcam_fov", "asked": fov, "state_fov": st.get("fov"), "cam": st.get("cam")})
                shot(s, ex, "pcam_fov%d" % fov, out)
            s.cmd("pcam", 0)
            s.cmd("pause", 0)
        if "game" in phases:
            s.cmd("photo", 0)
            s.cmd("pause", 1)
            s.cmd("gpose", x, y, z, pitch, yaw, 60, 0)
            d0, _ = cam_off()
            prev = shot(s, ex, "game_start", out, settle=150)
            d1, _ = cam_off()
            print("game camera: %.4f m off the pose at once, %.4f m 150 frames later" % (d0, d1))
            for k in range(a.steps):
                got = stepw(s, keep=1)
                s.cmd("gpose", x, y, z, pitch, yaw, 60, 0)
                d, _ = cam_off()
                got.update(cam_off_m=d)
                record("game_stepw_%d" % k, "game_stepw", got)
            s.cmd("pause", 0)
    finally:
        s.cmd("pcam", 0, check=False)
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
        with open(os.path.join(out, "report.json"), "w") as f:
            json.dump(rows, f, indent=1)
    print("frames in", out)


if __name__ == "__main__":
    main()
