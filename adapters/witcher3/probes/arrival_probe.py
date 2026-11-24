"""How long after a teleport the scene is complete (grass, foliage), with the world running and held.

    uv run --project . python -m adapters.witcher3.probes.arrival_probe [--location witcher3-mulbrydale-001] [--away x,y,z]

Found 2026-11-23: a near sweep at Mulbrydale, taken after a 1.3 km teleport, had no grass in its first
72 poses and grass from pose 72 on (about 200 s into the held world). For each mode (running, held)
the player is sent --away and back to the location, the photo-mode camera is put 1.7 m above the
location looking 35 degrees down, and frames are saved at the given seconds after arrival; each is
compared with the last one (mean difference, levels of 255). Frames and a sheet under
out/probes/witcher3/arrival/.
"""
import argparse
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, vec

TIMES = (1, 3, 6, 10, 15, 20, 30, 45, 60, 90, 120)


def load(path):
    from PIL import Image
    with Image.open(path) as im:
        a = np.asarray(im.convert("RGB").resize((640, 360), Image.BOX), dtype=np.float32)
    os.remove(path)
    return a


def arrive(s, ex, away, there, facing, wait_away=15):
    s.cmd("unfreeze")
    s.cmd("teleport", away[0], away[1], away[2], 0)
    time.sleep(wait_away)
    s.cmd("teleport", there[0], there[1], there[2] + 0.1, facing)
    return time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="witcher3-mulbrydale-001")
    ap.add_argument("--away", default="666.1,1874.5,10.1")       # Hierarch Square, 1.3 km off
    ap.add_argument("--modes", default="running,held")
    a = ap.parse_args()
    from PIL import Image
    loc = locs.find(locs.load(capture_paths.LOCATIONS), a.location) if hasattr(locs, "find") else next(
        l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    there, facing = loc["position"], float(loc.get("facing_deg", 0.0))
    away = [float(v) for v in a.away.split(",")]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "arrival")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("hud", 0)
    h = np.radians(facing)
    pose = (there[0], there[1], there[2] + 1.7, -35.0, facing)
    rows = []
    try:
        for mode in a.modes.split(","):
            t0 = arrive(s, ex, away, there, facing)
            s.cmd("hide", 1)
            s.cmd("freeze")                     # photo mode and its camera
            if mode == "running":
                s.cmd("pause", 0)               # photo-mode camera, world running
            s.cmd("pose", *pose, 0, 60)
            shots = []
            for t in TIMES:
                time.sleep(max(0.0, t0 + t - time.time()))
                time.sleep(s.console_clear_in())
                r = frames.shoot(ex, "arrival/%s_%03d" % (mode, t))
                shots.append((t, time.time() - t0, load(r["path"])))
            st = s.state()
            last = shots[-1][2]
            line = []
            for t, real, img in shots:
                d = float(np.abs(img - last).mean())
                line.append("%ds:%.2f" % (t, d))
                Image.fromarray(img.astype(np.uint8)).save(os.path.join(out, "%s_%03d.jpg" % (mode, t)), quality=85)
            print("%s (streaming=%s at the end): difference to the %d s frame  %s" % (mode, st.get("streaming"), TIMES[-1], "  ".join(line)))
            rows.append((mode, shots))
    finally:
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    # a sheet: each mode a row of 6 of its frames
    pick = [0, 2, 4, 6, 8, len(TIMES) - 1]
    sheet = Image.new("RGB", (6 * 320, len(rows) * 180))
    for r, (mode, shots) in enumerate(rows):
        for c, k in enumerate(pick):
            sheet.paste(Image.fromarray(shots[k][2].astype(np.uint8)).resize((320, 180)), (c * 320, r * 180))
    sheet.save(os.path.join(out, "sheet.jpg"), quality=85)
    print("frames and sheet in", out)


if __name__ == "__main__":
    main()
