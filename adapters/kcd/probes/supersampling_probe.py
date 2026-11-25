"""Does r_Supersampling take effect, and what does it do to the frame? At one held view (the
player's spot, looking along his heading), for each value: the frame rate, the saved frame's size,
its mean brightness, and its edge energy (mean absolute Laplacian of the luma, divided by the mean:
anti-aliasing and supersampling lower it on edges and raise nothing else), with a crop sheet.

    uv run --project . python -m adapters.kcd.probes.supersampling_probe [--values 1,2,3,1] [--frames 120]

The world stays held, so nothing moves between values; the eye does not adapt in a held world, so a
switch that resets the eye shows as a brightness change (--run-s lets the world run after each).
"""
import argparse
import json
import os
import time

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, vec


def edge_energy(a):
    lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    lap = np.abs(4 * lum[1:-1, 1:-1] - lum[:-2, 1:-1] - lum[2:, 1:-1] - lum[1:-1, :-2] - lum[1:-1, 2:])
    return float(lap.mean() / max(1e-3, lum.mean())), float(lum.mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--values", default="1,2,3,1")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--crop", default="0.40,0.30,0.20,0.20", help="x,y,w,h fractions for the crop sheet")
    ap.add_argument("--run-s", type=float, default=0.0, help="after each switch the world runs this long with the eye "
                    "at speed 30 (a switch resets the eye: 89.6 -> 248 of 255 in a held world, 2026-11-25), then is held")
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "kcd_supersampling", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    st = s.state()
    p = vec(st["player"])
    h = float(st["heading"])
    report = {"values": [], "player": p}
    crops = []
    try:
        s.cmd("hud", 0)
        s.cmd("ghost", 1)
        time.sleep(2)
        s.cmd("freeze")
        s.cmd("pose", p[0], p[1], p[2] + 1.7, -5.0, 0.0, h, 60.0)
        for v in a.values.split(","):
            s.cmd("cvar", "r_Supersampling", int(v))
            if a.run_s:
                s.cmd("cvar", "r_HDREyeAdaptationSpeed", 30)
                s.cmd("unfreeze")
                time.sleep(a.run_s)
                s.cmd("freeze")
                s.cmd("cvar", "r_HDREyeAdaptationSpeed", 3)
            frames.wait(ex, a.frames)
            got = (s.cmd("cvar", "r_Supersampling").data or ["?"])[0]
            fps = frames.frame_rate(ex, 2.0)
            time.sleep(s.console_clear_in())
            r = frames.shoot(ex, "ss_%s" % v, after=30)
            with Image.open(r["path"]) as im:
                arr = np.asarray(im.convert("RGB"), dtype=np.float32)
                size = im.size
            os.remove(r["path"])
            e, m = edge_energy(arr)
            W, H = size
            x, y, w, hh = (float(t) for t in a.crop.split(","))
            crop = arr[int(y * H):int((y + hh) * H), int(x * W):int((x + w) * W)]
            crops.append((v, crop))
            Image.fromarray(arr.astype(np.uint8)).save(os.path.join(out, "ss_%s_%d.jpg" % (v, len(crops))), quality=92)
            row = {"value": v, "read_back": got, "fps": round(fps, 1), "size": size, "brightness": round(m, 2),
                   "edge_energy": round(e, 4)}
            report["values"].append(row)
            print(row, flush=True)
        ch = max(c.shape[0] for _, c in crops)
        sheet = Image.new("RGB", (sum(c.shape[1] for _, c in crops) * 2, ch * 2))
        xo = 0
        for v, c in crops:
            im = Image.fromarray(c.astype(np.uint8)).resize((c.shape[1] * 2, c.shape[0] * 2), Image.NEAREST)
            sheet.paste(im, (xo, 0))
            xo += im.width
        sheet.save(os.path.join(out, "crops_x2.png"))
    finally:
        s.cmd("cvar", "r_Supersampling", 1)
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("ghost", 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
