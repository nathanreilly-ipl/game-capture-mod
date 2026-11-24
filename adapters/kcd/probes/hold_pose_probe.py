"""Does holding the world change people's poses? (In The Witcher 3, switching its photo mode put
people into their arms-out reference pose; a Rattay preview here showed two women with arms out.)

    uv run --project . python -m adapters.kcd.probes.hold_pose_probe [--location kcd-loc-001] [--heading 159.2]

With the world running, the camera is put at the location's eye height looking along --heading and
a frame taken; at once the world is held and frames taken 20 and 300 frames later; then 30 even
steps of 1/30 s and one more frame. Compared: running against held (people move between the two,
so look at the pictures: poses must look the same), held against held later (must be equal), and
the frames are saved to out/probes/kcd/hold_pose/.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, parse_kv


def grab(ex, name, out, after):
    from PIL import Image
    r = frames.shoot(ex, "hold_pose/" + name, after=after)
    with Image.open(r["path"]) as im:
        a = np.asarray(im.convert("RGB"), dtype=np.float32)
        im.convert("RGB").save(os.path.join(out, name + ".jpg"), quality=90)
    os.remove(r["path"])
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="kcd-loc-001")
    ap.add_argument("--heading", type=float, default=159.2)
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    x, y, z = loc["position"][0], loc["position"][1], loc["position"][2] + 1.6
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "kcd", "hold_pose")
    os.makedirs(out, exist_ok=True)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, a.heading)
    time.sleep(8)
    rep = {}
    try:
        s.cmd("hud", 0)
        s.cmd("hide", 1)
        s.cmd("pose", x, y, z, 0.0, 0.0, a.heading, 60.0)
        time.sleep(s.console_clear_in())
        running = grab(ex, "0_running", out, 20)
        s.cmd("freeze")
        time.sleep(s.console_clear_in())
        held = grab(ex, "1_held_20", out, 20)
        held2 = grab(ex, "2_held_300", out, 300)
        frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
        for _ in range(30):
            mark = s.log_size()
            r = s.cmd("step", 1.0 / 30, 8)
            s.wait_line("t", r.seq, mark, timeout=20.0)
        time.sleep(s.console_clear_in())
        stepped = grab(ex, "3_after_30_steps", out, 20)
        rep = {"running_vs_held": round(float(np.abs(running - held).mean()), 3),
               "held_vs_held_300": round(float(np.abs(held - held2).mean()), 3),
               "held_vs_after_steps": round(float(np.abs(held2 - stepped).mean()), 3)}
        print(json.dumps(rep))
    finally:
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    print("frames in", out)


if __name__ == "__main__":
    main()
