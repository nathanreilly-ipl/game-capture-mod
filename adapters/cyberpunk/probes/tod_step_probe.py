"""Does the scene's light jump when the clock of day crosses a game minute during time steps? (QC
round 1, cyberpunk-001: at Badlands clip frame 25 every camera stepped 0.7-0.8 levels brighter at once
while the steps were exact.) The clock runs about 8 game seconds per world second, so a 30-step clip
crosses a minute in about one take in eight.

    uv run --project . python -m adapters.cyberpunk.probes.tod_step_probe [--location cyberpunk-badlands-roadside-001]
        [--clock 11:59] [--start-s 45] [--steps 40]

The clock is set, the world runs until the clock's seconds reach --start-s, then the world is held at
one view (the take's way: hide, exposure lock) and stepped; after each step: the game clock in
seconds and the frame's mean brightness over the pixels that hardly change.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from capture import locations, paths as capture_paths  # noqa: E402
import upscaler_ab as u  # noqa: E402

from ..adapter import CyberpunkAdapter  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="cyberpunk-badlands-roadside-001")
    ap.add_argument("--clock", default="11:59")
    ap.add_argument("--start-s", type=int, default=45)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--target", default="wide")
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_tod_step", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    rows = []
    try:
        loc = locations.get(capture_paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        st = ad.subject_state()
        view = u.views(ad, st)[a.target]
        ad.set_clock(a.clock)
        t0 = time.time()
        while time.time() - t0 < 120:
            sec = int(ad.sess.cmd("state")["game_seconds"]) % 60
            if sec >= a.start_s:
                break
            time.sleep(0.2)
        ad.hide_subject(True)
        ad.begin_frozen(view)
        g0 = None
        for k in range(a.steps + 1):
            if k:
                ad.advance(1.0 / 30)
            p = os.path.join(out, "%02d.bmp" % k)
            ad.capture(p, int(ad.settings.get("settle") or 120))
            g = np.asarray(Image.open(p).convert("L").resize((480, 270)), dtype=np.float32)
            g0 = g if g0 is None else g0
            m = (g0 > 20) & (g0 < 220) & (np.abs(g - g0) < 0.25 * g0)
            secs = int(ad.sess.cmd("state")["game_seconds"])
            rows.append({"step": k, "game_seconds": secs, "clock": "%02d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60),
                         "brightness": round(float(g[m].mean()), 3)})
            print(rows[-1], flush=True)
            Image.open(p).resize((640, 360)).save(p[:-4] + ".jpg", quality=85)
            os.remove(p)
    finally:
        try:
            ad.end_frozen()
            ad.hide_subject(False)
        finally:
            ad.close()
    json.dump(rows, open(os.path.join(out, "report.json"), "w"), indent=1)
    d = [rows[i + 1]["brightness"] - rows[i]["brightness"] for i in range(len(rows) - 1)]
    big = [(rows[i + 1]["clock"], round(v, 3)) for i, v in enumerate(d) if abs(v) > 0.3]
    print("steps over 0.3 levels:", big, "wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
