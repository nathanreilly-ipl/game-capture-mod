"""How long the debug console stays in the picture after a command.

    uv run --project . python -m adapters.witcher3.probes.console_probe [--runs 5]

A command is typed into the console, which is drawn in the frame and slides shut after the last
key. The world is held, a reference frame is taken two seconds after a command, and then, for each
run, frames are saved one after another from the moment the command's answer arrives; each one's
top strip (where the console is) is compared with the reference. Prints, per run, the real time
and the number of frames after the answer at which the strip last differed. The adapter waits
longer than the worst of these before every picture (Session.clear_s).
"""
import argparse
import os
import time

import numpy as np

from ...common import frames
from .. import paths
from ..session import Session


def strip(path):
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
        a = np.asarray(im.convert("RGB").crop((0, 0, w, h // 3)), dtype=np.float32)
    os.remove(path)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--shots", type=int, default=14)
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    st = s.close_menu()
    if st.get("menu") == "1":
        raise SystemExit("the game's menu is open and would not close")
    s.cmd("hud", 0)
    s.cmd("hide", 1)
    s.cmd("freeze")
    worst_ms, worst_frames = 0.0, 0
    try:
        s.state()
        time.sleep(2.0)
        ref = strip(frames.shoot(ex, "console/ref")["path"])
        again = strip(frames.shoot(ex, "console/ref2", after=3)["path"])
        floor = float((np.abs(ref - again).max(axis=2) > 24).mean())
        print("two clean frames: %.4f%% of the strip's pixels differ by more than 24 (renderer noise)" % (100 * floor))
        for run in range(a.runs):
            s.state()
            t0 = time.time()
            f0 = None
            last_ms, last_frames, rows = 0.0, 0, []
            for i in range(a.shots):
                shot = frames.shoot(ex, "console/r%d_%02d" % (run, i))
                ms = (time.time() - t0) * 1000
                f0 = shot["frame"] if f0 is None else f0
                share = float((np.abs(strip(shot["path"]) - ref).max(axis=2) > 24).mean())
                rows.append((ms, shot["frame"] - f0, share))
                if share > floor * 3 + 0.002:
                    last_ms, last_frames = ms, shot["frame"] - f0
            print("run %d: console last seen %.0f ms and %d frames after the answer  (%s)"
                  % (run, last_ms, last_frames, " ".join("%.0fms:%.1f%%" % (m, 100 * sh) for m, _, sh in rows[:8])))
            worst_ms, worst_frames = max(worst_ms, last_ms), max(worst_frames, last_frames)
            time.sleep(1.0)
        print("worst: %.0f ms, %d frames" % (worst_ms, worst_frames))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)


if __name__ == "__main__":
    main()
