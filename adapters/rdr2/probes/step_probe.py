"""Measures how exactly the world can be stepped by 1/30 s between frozen states.

    uv run --with numpy tools/step_probe.py [--steps 30] [--scale 0.1]

Freezes, then advances N times by 1/30 s, and compares the requested total with
the game timer and with the player's head bone travel (a world clock that does not
depend on the frame-time readings).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.session import CamSession  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=0.1)
    args = ap.parse_args()
    sess = CamSession()
    try:
        sess.cmd("freeze")
        sess.cmd("wait", 20)
        t_start = int(sess.cmd("state")["game_timer"])
        total, ticks = 0.0, []
        for i in range(args.steps):
            r = sess.cmd("advance", "%.9f %.4f" % (1 / 30, args.scale), timeout=60)
            total += float(r["advanced_s"])
            ticks.append(int(r["ticks"]))
            if i < 3:
                print("step %d: advanced %.5f s in %s ticks, timer +%s ms, frame time while frozen %s; dts %s" % (
                    i, float(r["advanced_s"]), r["ticks"], r["timer_ms"], r["frame_time_after_freeze"], r["dts"]))
        t_end = int(sess.cmd("state")["game_timer"])
        want = args.steps / 30
        print("requested %.4f s; summed frame time %.4f s; game timer %.3f s; ticks per step %d..%d" % (
            want, total, (t_end - t_start) / 1000, min(ticks), max(ticks)))
        sess.cmd("unfreeze")
    finally:
        sess.end()


if __name__ == "__main__":
    main()
