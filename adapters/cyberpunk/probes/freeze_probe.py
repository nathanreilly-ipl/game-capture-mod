"""Is the held world really still, does a moved camera still render, and are time steps exact?

At the player's spot (stand somewhere with people around): hide the HUD, hold the world, park
the player, then
  1. the same pose captured 480 frames apart: people's positions and the two frames compared
  2. the camera moved 2 m and back: the moved frame must differ, the frame after coming back
     must match the first
  3. three time steps of 1/30 s: what the simulation clock advanced, how far people moved
Frames and a report go to out/probes/cyberpunk_freeze/.

    uv run --project . python -m adapters.cyberpunk.probes.freeze_probe [--frames 480]
"""
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ...common import redlua
from .. import paths
from ..adapter import SESSION_JOB


def people(sess, radius=60):
    st = sess.cmd("people", radius)
    out = {}
    for n in range(1, int(st["people_count"]) + 1):
        ident, pos = st["e%d" % n].split("|")
        out[ident] = np.array([float(v) for v in pos.split()])
    return out


def moved(a, b):
    """(count in both, largest move in metres, appeared, gone)"""
    both = [k for k in a if k in b]
    worst = max((float(np.linalg.norm(a[k] - b[k])) for k in both), default=0.0)
    return len(both), worst, len(set(b) - set(a)), len(set(a) - set(b))


def main(argv):
    frames = int(argv[argv.index("--frames") + 1]) if "--frames" in argv else 480
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_freeze")
    os.makedirs(out, exist_ok=True)
    sess = redlua.Session(ex, SESSION_JOB, idle_s=300, timeout_s=1800, staged=True)
    report = {}

    def shoot(name, settle=40):
        r = sess.cmd("shoot", settle, name, timeout=60)
        dst = os.path.join(out, name + ".bmp")
        shutil.move(os.path.join(ex, *r["file"].split("/")), dst)
        img = np.asarray(Image.open(dst).convert("RGB"), dtype=np.float32)
        Image.open(dst).convert("RGB").resize((1280, 720)).save(os.path.join(out, name + ".jpg"), quality=88)
        os.remove(dst)
        return img, r

    def pose(pos, right, fwd, up, fov=60.0):
        sess.cmd("pose", " ".join("%.6f" % v for v in list(pos) + list(right) + list(fwd) + list(up) + [fov]))

    try:
        if "--at" in argv:   # x,y,z,yaw: go there first, set noon, let people arrive
            x, y, z, yaw = (float(v) for v in argv[argv.index("--at") + 1].split(","))
            r = sess.cmd("teleport", "%.3f %.3f %.3f %.3f" % (x, y, z, yaw), timeout=300)
            report["teleport"] = {k: r[k] for k in ("loaded", "frames", "ground_z")}
            sess.cmd("clock", 12, 0)
            sess.cmd("wait", 600, timeout=120)
        st = sess.cmd("state")
        p = np.array(redlua.vec(st["player"]))
        h = np.radians(float(st["player_heading"]))
        fwd = np.array([-np.sin(h), np.cos(h), 0.0])
        right = np.array([np.cos(h), np.sin(h), 0.0])
        up = np.array([0.0, 0.0, 1.0])
        eye = p + up * 1.7 - fwd * 1.0
        sess.cmd("hud", 0)
        sess.cmd("freeze")
        sess.cmd("wait", 10)
        sess.cmd("park", 12)
        if "--extra" in argv:   # a session command to try on top of the hold, e.g. "timepause 1"
            c = argv[argv.index("--extra") + 1].split(" ", 1)
            report["extra"] = {"cmd": " ".join(c), "answer": {k: v for k, v in sess.cmd(*c).items() if k.endswith("paused")}}
        a = sess.cmd("anchor")
        report["anchor"] = {k: a[k] for k in a if k.startswith("anchor_")}
        pose(eye, right, fwd, up)
        p0 = people(sess)
        img_a, ra = shoot("a_first", 90)
        report["requested_pos"] = [float(v) for v in eye]
        report["rendered"] = {k: ra.get(k) for k in ("rendered_pos", "rendered_fwd", "rendered_up", "rendered_right", "rendered_fov",
                                                      "width", "height", "dilation", "real_dt")}
        s0 = float(ra["sim_time"])
        sess.cmd("wait", frames, timeout=60 + frames / 20)
        p1 = people(sess)
        img_b, rb = shoot("b_same_pose_later", 1)
        n, worst, new, gone = moved(p0, p1)
        report["held"] = {"frames": frames, "people": n, "largest_move_m": worst, "appeared": new, "gone": gone,
                          "sim_time_advanced_s": float(rb["sim_time"]) - s0,
                          "frame_difference_mean": float(np.abs(img_a - img_b).mean()),
                          "frame_difference_max": float(np.abs(img_a - img_b).max())}
        pose(eye + right * 2.0, right, fwd, up)
        img_c, _ = shoot("c_moved_2m")
        pose(eye, right, fwd, up)
        img_d, _ = shoot("d_back")
        report["camera"] = {"moved_difference_mean": float(np.abs(img_a - img_c).mean()),
                            "back_difference_mean": float(np.abs(img_a - img_d).mean())}
        steps = []
        for i in range(0 if "--no-steps" in argv else 3):
            before = people(sess)
            r = sess.cmd("advance", "%.9f" % (1 / 30), timeout=120)
            sess.cmd("park", 12)
            sess.cmd("anchor")
            pose(eye, right, fwd, up)
            after = people(sess)
            n, worst, new, gone = moved(before, after)
            steps.append({"advanced_s": float(r["advanced_s"]), "frames": int(r["frames"]), "people": n,
                          "largest_move_m": worst, "appeared": new, "gone": gone})
        report["steps"] = steps
        img_e, _ = shoot("e_after_3_steps")
        report["after_steps_difference_mean"] = float(np.abs(img_a - img_e).mean())
    finally:
        for c in ("unpark", "unfreeze"):
            try:
                sess.cmd(c)
            except Exception as e:  # noqa: BLE001
                print("cleanup %s: %s" % (c, e))
        try:
            sess.cmd("hud", 1)
        except Exception as e:  # noqa: BLE001
            print("cleanup hud: %s" % e)
        sess.end()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
