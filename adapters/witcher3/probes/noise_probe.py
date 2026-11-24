"""What changes from frame to frame at one pose in a held world: renderer noise, or something moving?

    uv run --project . python -m adapters.witcher3.probes.noise_probe [--n 16] [--gap 2] [--pose x,y,z,pitch,yaw] [--tag name]

Takes n frames `gap` frames apart, twice (the second set two seconds later), and prints

    neighbours        mean difference between frames next to each other, and 2, 4, 8 apart
    spread            share of pixels whose standard deviation over the set is over 4 and over 12
    average of k      the difference between the two sets' averages of k frames (1, 2, 4, ..., n):
                      noise without memory falls by the square root of k; noise that the renderer
                      carries from frame to frame, or something moving slowly, falls more slowly

and saves the standard-deviation map (x8), one frame, the average, and a crop of the first frame
beside the same crop of the last and their difference (x6) under out/probes/witcher3/noise/<tag>/.
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
        a = np.asarray(im.convert("RGB"), dtype=np.float32)
    os.remove(path)
    return a


def burst(ex, n, gap, tag):
    return np.stack([load(frames.shoot(ex, "noise/%s_%02d" % (tag, i), after=gap)["path"]) for i in range(n)])


def mad(p, q):
    return float(np.abs(p - q).mean())


def measure(s, ex, pose, n=16, gap=2, settle=180, fov=60, do=(), log=print):
    """Holds the world at pose (x, y, z, pitch, yaw), takes the two sets and releases it.
    Returns (report, first set, second set)."""
    x, y, z, pitch, yaw = pose
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", x, y, z, pitch, yaw, 0, fov)
        for line in do:                        # e.g. "wind 1 1", "water 0"
            parts = line.split()
            r = s.cmd(parts[0], *[float(v) if "." in v else int(v) for v in parts[1:]])
            log("> %s -> %s" % (line, r.text))
        frames.wait(ex, settle)
        time.sleep(0.5)
        fps = frames.frame_rate(ex, 1.0)
        one = burst(ex, n, gap, "a")
        time.sleep(2.0)
        two = burst(ex, n, gap, "b")
        st = s.state()
        if st.get("menu") == "1":
            raise SystemExit("the game's menu opened during the probe")
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
    report = {"pose": list(pose), "n": n, "gap": gap, "frames_per_s": round(fps, 1), "apart": {}, "average_of": {}}
    for k in (1, 2, 4, 8):
        if k < n:
            report["apart"][k] = round(float(np.mean([mad(one[i], one[i + k]) for i in range(n - k)])), 4)
    sd = one.std(axis=0).max(axis=2)
    report["sd_over_4_pct"] = round(100 * float((sd > 4).mean()), 4)
    report["sd_over_12_pct"] = round(100 * float((sd > 12).mean()), 4)
    k = 1
    while k <= n:
        report["average_of"][k] = round(mad(one[:k].mean(axis=0), two[:k].mean(axis=0)), 4)
        k *= 2
    return report, one, two


def save(out, report, one, two, crop):
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    sd = one.std(axis=0).max(axis=2)
    avg = one.mean(axis=0)
    Image.fromarray(np.clip(sd * 8, 0, 255).astype(np.uint8)).save(os.path.join(out, "sd_x8.png"))
    Image.fromarray(one[0].astype(np.uint8)).save(os.path.join(out, "frame.png"))
    Image.fromarray(np.clip(avg + 0.5, 0, 255).astype(np.uint8)).save(os.path.join(out, "average.png"))
    x0, y0, x1, y1 = crop
    a, b = one[0][y0:y1, x0:x1], two[-1][y0:y1, x0:x1]
    pair = np.concatenate([a, b, np.clip(np.abs(a - b) * 6, 0, 255)], axis=1)
    Image.fromarray(np.clip(pair, 0, 255).astype(np.uint8)).resize((pair.shape[1] * 2, pair.shape[0] * 2), Image.NEAREST).save(
        os.path.join(out, "crop_first_later_diff_x6.png"))
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)


def text(report):
    return ("%.1f frames/s; frames %d apart in each set\n" % (report["frames_per_s"], report["gap"])
            + "neighbours: mean difference " + ", ".join("%s apart %.3f" % kv for kv in report["apart"].items()) + "\n"
            + "spread: %.3f%% of pixels with a standard deviation over 4, %.3f%% over 12\n"
            % (report["sd_over_4_pct"], report["sd_over_12_pct"])
            + "two sets two seconds apart, average of k frames against average of k: "
            + ", ".join("k=%s %.3f" % kv for kv in report["average_of"].items()))


def default_pose(st):
    cam = [float(v) for v in st["cam"].split(",")]
    return cam[0], cam[1], cam[2] + 1.0, -8.0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--gap", type=int, default=2)
    ap.add_argument("--pose", default="")
    ap.add_argument("--settle", type=int, default=180)
    ap.add_argument("--tag", default="here")
    ap.add_argument("--crop", default="1300,450,1600,650", help="x0,y0,x1,y1 of the detail crop")
    ap.add_argument("--do", action="append", default=[], help="a cm_ command to run once the world is held (repeatable)")
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "noise", a.tag)
    st = s.close_menu()
    if st.get("menu") == "1":
        raise SystemExit("the game's menu is open and would not close")
    st = s.cmd("hud", 0).state
    pose = [float(v) for v in a.pose.split(",")] if a.pose else default_pose(st)
    try:
        report, one, two = measure(s, ex, pose, a.n, a.gap, a.settle, do=a.do)
    finally:
        s.cmd("hud", 1)
    save(out, report, one, two, [int(v) for v in a.crop.split(",")])
    print(text(report))
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
