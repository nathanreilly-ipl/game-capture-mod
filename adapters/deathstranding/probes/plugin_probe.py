"""Tests capture_ds.asi in the running game: hold (frames compared over seconds), steps (the game
clock read through the plug-in's status), and the camera override (a pose moved and the picture
compared). How the hold and the camera were first measured, 2026-11-25.

    python -m adapters.deathstranding.probes.plugin_probe hold
    python -m adapters.deathstranding.probes.plugin_probe cam --dx 0.5
    python -m adapters.deathstranding.probes.plugin_probe step --frames 8
"""
import argparse
import os
import time

import numpy as np

from adapters.common import window_win32 as w
from capture import paths

X = os.path.join(paths.OUT, "exchange", "deathstranding")
TITLE = "DEATH STRANDING DIRECTOR'S CUT"
OUT = os.path.join(paths.OUT, "probes", "deathstranding")


class Ctl:
    def __init__(self):
        self.seq = int(time.time() * 10) % 10 ** 8

    def status(self):
        st = {}
        for line in open(os.path.join(X, "capture_status.txt")):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                st[k] = v
        return st

    def cmd(self, text, timeout=5.0):
        self.seq += 1
        tmp = os.path.join(X, "capture.txt.tmp")
        with open(tmp, "w") as f:
            f.write("%d %s\n" % (self.seq, text))
        os.replace(tmp, os.path.join(X, "capture.txt"))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                st = self.status()
                if st.get("seq") == str(self.seq):
                    return st
            except OSError:
                pass
            time.sleep(0.01)
        raise TimeoutError("no answer to %r" % text)

    def wait_frames(self, n, timeout=30):
        f0 = int(self.status()["frame"])
        t0 = time.time()
        while int(self.status()["frame"]) < f0 + n and time.time() - t0 < timeout:
            time.sleep(0.01)


def grab(h, size=(960, 540)):
    return np.asarray(w.grab(h).convert("L").resize(size), dtype=np.float32)


def series(h, n=6, gap=0.5):
    pics = []
    for _ in range(n):
        pics.append(grab(h))
        time.sleep(gap)
    neighbour = float(np.mean([np.abs(pics[i + 1] - pics[i]).mean() for i in range(n - 1)]))
    over = float((np.abs(pics[-1] - pics[0]) > 12).mean())
    return neighbour, over, pics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["hold", "cam", "step", "run"])
    ap.add_argument("--dx", type=float, default=0.0)
    ap.add_argument("--dy", type=float, default=0.0)
    ap.add_argument("--dz", type=float, default=0.0)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    h = w.windows_titled(TITLE)[0]
    c = Ctl()
    if a.what == "run":
        print(c.cmd("run")); print(c.cmd("cam off")); return
    if a.what == "hold":
        c.cmd("run")
        n, o, _ = series(h)
        print("running: neighbour diff %.3f, share over 12 first-last %.4f" % (n, o))
        st = c.cmd("hold")
        time.sleep(0.5)
        n, o, pics = series(h, n=int(a.seconds / 0.5) + 1)
        print("held:    neighbour diff %.3f, share over 12 first-last %.4f (frame %s)" % (n, o, c.status()["frame"]))
        from PIL import Image
        Image.fromarray(np.clip(np.abs(pics[-1] - pics[0]) * 8, 0, 255).astype(np.uint8)).save(os.path.join(OUT, "plugin_hold_diff.png"))
        return
    if a.what == "step":
        c.cmd("hold")
        time.sleep(0.3)
        ticks = round(2 ** 32 / 30)
        f0 = int(c.status()["frame"])
        c.cmd("step %d %d" % (ticks, a.frames))
        c.wait_frames(a.frames + 2)
        st = c.status()
        print("step of %d ticks over %d frames: given %s ticks, state %s, frames %d" % (ticks, a.frames, st["ticks"], st["state"], int(st["frame"]) - f0))
        return
    if a.what == "cam":
        st = c.status()
        pos = [float(v) for v in st["game_pos"].split(",")]
        rot = [float(v) for v in st["game_rot"].split(",")]
        fov = float(st["game_fov"])
        c.cmd("hold")
        time.sleep(0.5)
        before = grab(h)
        p2 = [pos[0] + a.dx, pos[1] + a.dy, pos[2] + a.dz]
        st = c.cmd("cam %.6f %.6f %.6f %s %.5f" % (*p2, " ".join("%.7f" % r for r in rot), fov))
        time.sleep(0.5)
        after = grab(h)
        print("override sent: render_pos %s (asked %.3f,%.3f,%.3f)" % (c.status()["render_pos"], *p2))
        print("picture change %.2f, share over 12 %.3f" % (np.abs(after - before).mean(), (np.abs(after - before) > 12).mean()))
        w.grab(h).convert("RGB").save(os.path.join(OUT, "plugin_cam_after.jpg"), quality=85)
        c.cmd("cam off")


if __name__ == "__main__":
    main()
