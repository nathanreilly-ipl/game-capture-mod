"""Does cloth follow game time through a time step, or the number of frames the step takes?

    uv run --project . python -m adapters.witcher3.probes.cloth_rate_probe [--repeats 5]

cm_stepw runs the world at a small time scale for about 30 frames to land on exactly 1/30 s. If
cloth were simulated per frame instead of per second of game time, it would move far more in a
step than in 1/30 s of play (Nathan saw it jump at every step, 2026-11-23). Here the world is held
by our pause and seen through the photo mode's camera without the photo mode (cm_pcam), and steps
of the same length are run over different numbers of frames (frac: the share of what is left that
each frame covers), plus shorter steps over about the same number of frames. Mean difference
(levels of 255) between the frames before and after each step, in boxes on cloth (an awning,
banners) and over the whole frame.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, parse_kv
from .cloth_step_probe import shot

BOXES = {"awning": (180, 230, 430, 400), "banners": (740, 60, 900, 180), "frame": (0, 0, 1280, 720)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="654.6,1871.1,11.6,-6,16")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--play", type=int, default=6, help="frames taken of the world running on (0: none)")
    ap.add_argument("--holds", default="1,10,30", help="seconds held before a step")
    ap.add_argument("--hold", default="pause", help="pause, or a time scale to hold the world with (1e-6)")
    ap.add_argument("--soft", type=float, default=0.0, help="a step's first 3 frames at this time scale (0: none)")
    ap.add_argument("--const", default="", help="time scales to let the world run at between two commands")
    ap.add_argument("--cases", default="0.9:0.0333333,0.25:0.0333333,0.05:0.0333333,0.25:0.0083333,0.9:0.0083333")
    a = ap.parse_args()
    x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "cloth_rate")
    os.makedirs(out, exist_ok=True)
    rows = []

    def diffs(p, q):
        d = np.abs(p - q)
        return {k: round(float(d[y0:y1, x0:x1].mean()), 3) for k, (x0, y0, x1, y1) in BOXES.items()}

    def engine(st):
        return float(st["engine_base"]) + float(st["engine_rel"])

    def wind():
        """The wind 10 m in front of the camera (physics; visuals)."""
        fx, fy = -np.sin(np.radians(yaw)), np.cos(np.radians(yaw))
        r = s.cmd("windat", x + 10 * fx, y + 10 * fy, z)
        return r.data[0] if r.data else ""

    def hold_world():
        """The world held: by our pause, or by a tiny time scale with the world running on."""
        if a.hold == "pause":
            s.cmd("pause", 1)
        else:
            s.cmd("timescale", float(a.hold))
            s.cmd("pause", 0)

    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, yaw)
    time.sleep(12)
    try:
        s.cmd("hide", 1)
        hold_world()
        s.cmd("pcam", 1)
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        prev = shot(s, ex, "start", out, settle=150)
        for k in range(2):
            time.sleep(1.0)
            img = shot(s, ex, "held_%d" % k, out)
            row = dict(diffs(prev, img), case="held")
            rows.append(row)
            print("held            ", json.dumps(row))
            prev = img
        # for scale: the world running on, unbroken, at time scales 1 and 0.1; frames a known real
        # time apart, so the game time between them is known too
        from .cloth_step_probe import load
        for scale, gap in ((1.0, 2), (0.1, 20), (0.1, 2)):
            if a.play == 0:
                break
            s.cmd("timescale", scale)
            s.cmd("pause", 0)
            time.sleep(1.5 + s.console_clear_in())
            last, last_img = None, None
            for k in range(a.play):
                r = frames.shoot(ex, "cloth_rate/play_%d_%d" % (int(scale * 10), k), after=gap)
                img = load(r["path"])
                os.remove(r["path"])
                if last is not None:
                    game_ms = (r["time_ms"] and int(r["time_ms"]) - last) * scale
                    row = dict(diffs(last_img, img), case="play_scale%.1f" % scale, scale=scale,
                               frames=r["frame"] - last_frame, game_ms=round(game_ms, 1))
                    rows.append(row)
                    print("play scale %.1f" % scale, json.dumps(row))
                last, last_frame, last_img = int(r["time_ms"]), r["frame"], img
            s.cmd("timescale", -1)
            hold_world()
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        prev = shot(s, ex, "start2", out, settle=150)
        # does the jump grow with the real time the world was held before the step? (Nathan: as if
        # the hold stored up wind force, 2026-11-23)
        for hold in [float(v) for v in a.holds.split(",") if v]:
            for k in range(2):
                pre = shot(s, ex, ("pre_h%s_%d" % (hold, k)).replace(".", "p"), out, settle=2)
                e0 = engine(s.state())
                w0 = wind()
                time.sleep(hold)
                e1 = engine(s.state())
                w1 = wind()
                mid = shot(s, ex, ("mid_h%s_%d" % (hold, k)).replace(".", "p"), out, settle=2)
                mark = s.log_size()
                r = s.cmd("stepw", 1.0 / 30, 1, 0.25, a.soft)
                got = parse_kv(s.wait_line("t", r.seq, mark, timeout=60.0) or "")
                img = shot(s, ex, ("post_h%s_%d" % (hold, k)).replace(".", "p"), out)
                row = dict(diffs(mid, img), case="hold_%gs" % hold, hold_s=hold, frames=int(got.get("frames", 0)),
                           while_held=diffs(pre, mid)["frame"], creep_ms=round(1000 * (e1 - e0), 4),
                           wind_before=w0, wind_after_hold=w1, wind_after_step=wind())
                rows.append(row)
                print("held %5.1f s, then a step" % hold, json.dumps(row))
                prev = img
        # the world let run at one constant time scale between two commands (no tiny frames at the
        # end of a step, no large first frame): the time it covers is not exact, the engine says it
        for scale in [float(v) for v in a.const.split(",") if v]:
            s.cmd("timescale", scale)
            for k in range(a.repeats):
                e0 = engine(s.state())
                s.cmd("pause", 0)
                s.cmd("pause", 1)
                e1 = engine(s.state())
                img = shot(s, ex, ("const_%s_%d" % (scale, k)).replace(".", "p"), out)
                row = dict(diffs(prev, img), case="const_%g" % scale, scale=scale, game_ms=round(1000 * (e1 - e0), 3))
                rows.append(row)
                print("constant scale %g" % scale, json.dumps(row))
                prev = img
            s.cmd("timescale", -1)
        frame_s = 1.0 / max(1.0, frames.frame_rate(ex, 1.0))
        for case in [c for c in a.cases.split(",") if c]:
            even = case.startswith("even:")       # even:<frames>:<dt>
            if even:
                n, dt = int(case.split(":")[1]), float(case.split(":")[2])
                frac = 0.0
            else:
                frac, dt = [float(v) for v in case.split(":")]
            for k in range(a.repeats):
                mark = s.log_size()
                if even:
                    r = s.cmd("stepe", dt, n, round(frame_s, 5), 1)
                else:
                    r = s.cmd("stepw", dt, 1, frac, a.soft)
                done = s.wait_line("t", r.seq, mark, timeout=60.0)
                if done is None:
                    raise SystemExit("a step did not end")
                got = parse_kv(done)
                img = shot(s, ex, ("%s_%d" % (case, k)).replace(".", "p").replace(":", "_"), out)
                row = dict(diffs(prev, img), case=case, frac=frac, dt=dt,
                           advanced=float(got["advanced"]), frames=int(got["frames"]), ran=int(got.get("ran", 0)))
                rows.append(row)
                print(case, json.dumps(row))
                prev = img
    finally:
        s.cmd("pcam", 0, check=False)
        s.cmd("timescale", -1)
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
        with open(os.path.join(out, "report.json"), "w") as f:
            json.dump(rows, f, indent=1)
    print("summary (mean over repeats):")
    for case in (["held", "play_scale1.0", "play_scale0.1"] + ["hold_%gs" % float(v) for v in a.holds.split(",") if v]
                 + ["const_%g" % float(v) for v in a.const.split(",") if v] + a.cases.split(",")):
        rs = [r for r in rows if r["case"] == case]
        if rs:
            print("  %-18s frames %5s  awning %.3f  banners %.3f  frame %.3f" % (
                case, "%.0f" % np.mean([r.get("frames", 0) for r in rs]),
                np.mean([r["awning"] for r in rs]), np.mean([r["banners"] for r in rs]), np.mean([r["frame"] for r in rs])))


if __name__ == "__main__":
    main()
