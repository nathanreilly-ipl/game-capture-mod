"""Is the held world frozen? One pose, captured again and again over hundreds of frames.

    uv run --project . python -m adapters.witcher3.probes.freeze_probe [--frames 0,30,60,120,240,480] [--pose x,y,z,pitch,yaw]

Holds the world (our pause and the photo mode's camera, as the adapter does since 2026-11-23), puts the camera at one pose, lets
the picture settle, then saves the frame at each of the given frame counts and compares every one
with the first: the mean difference in levels of 255 and the share of pixels off by more than 4
and more than 12. Engine time is read before and after. A frozen world leaves only what the
renderer itself changes from frame to frame (path-tracing noise, temporal filtering), spread evenly
over the picture; anything that moves shows as a region in the difference map
(out/probes/witcher3/freeze/diff_x8.png, the last frame against the first, eight times amplified).
For scale, the world is then stepped by 1/30 s once and thirty times (even steps, cm_stepe, as
takes do) and the same pose compared with the last held frame (stepped_diff_x8.png).
"""
import argparse
import json
import os
import time

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session


def load(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def compare(a, b):
    d = np.abs(a - b).max(axis=2)
    return {"mean": round(float(np.abs(a - b).mean()), 4), "over_4_pct": round(100 * float((d > 4).mean()), 4),
            "over_12_pct": round(100 * float((d > 12).mean()), 4)}


def engine(st):
    return float(st["engine_base"]) + float(st["engine_rel"])


def series(s, ex, counts, tag, settle):
    frames.wait(ex, settle)
    t0 = engine(s.state())
    time.sleep(s.console_clear_in())      # the console the command opened slides out of the picture
    frames.wait(ex, 3)
    first, last, rows, done = None, None, [], 0
    wall = time.time()
    for n in counts:
        a = frames.shoot(ex, "freeze/%s_%04d" % (tag, n), after=max(0, n - done))
        done = n
        img = load(a["path"])
        os.remove(a["path"])
        if first is None:
            first = img
        else:
            rows.append(dict(compare(first, img), frame=n))
        last = img
    t1 = engine(s.state())
    return {"engine_moved_s": round(t1 - t0, 7), "real_s": round(time.time() - wall, 1), "against_first": rows}, first, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="0,30,60,120,240,480")
    ap.add_argument("--pose", default="")
    ap.add_argument("--settle", type=int, default=180)
    ap.add_argument("--steps", default="1,30")
    a = ap.parse_args()
    a.steps = [int(v) for v in a.steps.split(",")]
    counts = [int(v) for v in a.frames.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "freeze")
    os.makedirs(out, exist_ok=True)
    st = s.close_menu()
    if st.get("menu") == "1":
        raise SystemExit("the game's menu is open and would not close")
    st = s.cmd("hud", 0).state
    if a.pose:
        x, y, z, pitch, yaw = [float(v) for v in a.pose.split(",")]
    else:
        cam = [float(v) for v in st["cam"].split(",")]
        x, y, z, pitch, yaw = cam[0], cam[1], cam[2] + 1.0, -8.0, 0.0
    report = {"pose": [x, y, z, pitch, yaw], "frames": counts}
    from PIL import Image
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", x, y, z, pitch, yaw, 0, 60)
        held, first, last = series(s, ex, counts, "held", a.settle)
        report["held"] = held
        st = s.state()
        if st.get("menu") == "1":
            raise SystemExit("the game's menu opened during the probe")
        t_end = engine(st)
        d = np.clip(np.abs(first - last).max(axis=2) * 8, 0, 255).astype(np.uint8)
        Image.fromarray(d).save(os.path.join(out, "diff_x8.png"))
        Image.fromarray(first.astype(np.uint8)).save(os.path.join(out, "held_first.png"))
        Image.fromarray(last.astype(np.uint8)).save(os.path.join(out, "held_last.png"))
        print("held world: engine time moved %.7f s in %.0f real seconds" % (held["engine_moved_s"], held["real_s"]))
        for r in held["against_first"]:
            print("  frame %4d against frame 0: mean %.3f, %.3f%% of pixels off by more than 4, %.3f%% by more than 12"
                  % (r["frame"], r["mean"], r["over_4_pct"], r["over_12_pct"]))
        # for scale: the same pose after the world is stepped by 1/30 s, and by 1 s (30 steps)
        report["stepped"] = []
        total = 0
        frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
        for steps in a.steps:
            for _ in range(steps - total):
                mark = s.log_size()
                r = s.cmd("stepe", 1.0 / 30, 8, frame_s)
                if s.wait_line("t", r.seq, mark, timeout=30.0) is None:
                    raise SystemExit("a time step did not end")
                frames.wait(ex, 3)
            total = steps
            shot = frames.shoot(ex, "freeze/step_%03d" % steps, after=a.settle)
            img = load(shot["path"])
            os.remove(shot["path"])
            st = s.state()
            if st.get("menu") == "1":
                raise SystemExit("the game's menu opened during the probe")
            row = dict(compare(last, img), steps=steps, engine_moved_s=round(engine(st) - t_end, 6))
            report["stepped"].append(row)
            print("  after %3d steps of 1/30 s (engine %+.4f s) against the last held frame: mean %.3f, %.3f%% over 4, %.3f%% over 12"
                  % (steps, row["engine_moved_s"], row["mean"], row["over_4_pct"], row["over_12_pct"]))
            if steps == a.steps[-1]:
                d = np.clip(np.abs(last - img).max(axis=2) * 8, 0, 255).astype(np.uint8)
                Image.fromarray(d).save(os.path.join(out, "stepped_diff_x8.png"))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
