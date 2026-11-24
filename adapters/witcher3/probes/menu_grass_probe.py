"""Does the game's menu take the grass away, and what brings it back?

    uv run --project . python -m adapters.witcher3.probes.menu_grass_probe [--pose x,y,z,pitch,yaw]

Found 2026-11-23 in a near sweep at Mulbrydale: the world map (opened by an Enter that missed the
console) was closed with Esc before the first shot, and the held world then had no grass for 72
poses (about 200 s). Here, at one pose looking at grass: a frame held; the menu opened and closed
with the world held, frames at 1, 10 and 30 s; then the world let run for 1, 3 and 10 s and held
again, a frame after each. Each frame's difference to the first is printed (no grass differs by
about 20 levels of 255 on this view; noise by about 1). Frames under out/probes/witcher3/menu_grass/.
"""
import argparse
import os
import time

import numpy as np

from capture import paths as capture_paths

from ...common import frames, window
from .. import paths
from ..session import Session


def grab(s, ex, name, out):
    from PIL import Image
    time.sleep(s.console_clear_in())
    r = frames.shoot(ex, "menu_grass/" + name, after=30)
    with Image.open(r["path"]) as im:
        a = np.asarray(im.convert("RGB").resize((640, 360), Image.BOX), dtype=np.float32)
    os.remove(r["path"])
    Image.fromarray(a.astype(np.uint8)).save(os.path.join(out, name + ".jpg"), quality=85)
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", default="906.26,572.95,31.9,-35,315")      # Mulbrydale, the grass by the fence
    a = ap.parse_args()
    pose = [float(v) for v in a.pose.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "menu_grass")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("hud", 0)
    s.cmd("teleport", pose[0], pose[1], pose[2] - 1.7, pose[4])
    time.sleep(10)
    rows = []
    try:
        s.cmd("hide", 1)
        s.cmd("freeze")
        s.cmd("pose", *pose, 0, 60)
        frames.wait(ex, 120)
        ref = grab(s, ex, "0_held", out)
        # the world map, as an Enter typed into the game opens it: our freeze takes the game's keys
        # away, so it is opened and closed with them given back for a moment
        s.cmd("unfreeze")
        s.cmd("freeze")
        h = s.hwnd()
        s.cmd("pause", 1)
        st = s.state()
        print("before the menu: held=%s input=%s" % (st.get("held"), st.get("input")))
        # give the game its keys back (our freeze stored EMPTY_CONTEXT), open the map with Enter
        s.cmd("unfreeze")
        window.focus(h)
        window.press(h, "Enter", hold_s=0.05)
        time.sleep(2.0)
        st = s.state()
        print("after Enter: menu=%s" % st.get("menu"))
        s.close_menu()
        s.cmd("freeze")
        s.cmd("pose", *pose, 0, 60)
        for t in (1, 10, 30):
            time.sleep(t if t == 1 else t - (10 if t == 30 else 1))
            img = grab(s, ex, "1_after_menu_%02ds" % t, out)
            rows.append(("held, %d s after the menu" % t, float(np.abs(img - ref).mean())))
        for t in (1, 3, 10):
            s.cmd("pause", 0)
            time.sleep(t)
            s.cmd("pause", 1)
            frames.wait(ex, 60)
            img = grab(s, ex, "2_after_running_%02ds" % t, out)
            rows.append(("after the world ran %d s" % t, float(np.abs(img - ref).mean())))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    for label, d in rows:
        print("%-32s difference to the first held frame %.2f" % (label, d))


if __name__ == "__main__":
    main()
