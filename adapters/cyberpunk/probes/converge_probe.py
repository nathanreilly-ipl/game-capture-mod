"""How long does the path-traced picture keep changing after a camera cut?

In a held world: look away, cut to a test pose, then capture every `every` frames up to `until`
without moving the camera again. Each capture is compared with the last one (mean absolute
difference, levels of 255, on frames reduced to 1280x720) and with the one before it, and its
brightness is listed: the light the path tracer gathers keeps building up for hundreds of frames.

    uv run --project . python -m adapters.cyberpunk.probes.converge_probe [--every 40] [--until 640] [--eval "<lua>"]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ..adapter import CyberpunkAdapter


def main(argv):
    every = int(argv[argv.index("--every") + 1]) if "--every" in argv else 40
    until = int(argv[argv.index("--until") + 1]) if "--until" in argv else 640
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_converge")
    os.makedirs(out, exist_ok=True)
    report = {"every": every, "until": until}
    try:
        st = ad.subject_state()
        fwd, right, up = (np.array(v) for v in ad.heading_basis(st["facing_deg"]))
        eye = np.array(st["position"]) + up * 1.6 - fwd * 2.0
        ad.hide_subject(True)
        shot = {"pos": eye, "right": right, "fwd": fwd, "up": up, "vfov_deg": 60.0}
        ad.begin_frozen(dict(shot, right=-right, fwd=-fwd))
        if "--eval" in argv:
            report["eval"] = argv[argv.index("--eval") + 1]
            report["eval_answer"] = ad.eval(report["eval"]).strip()
        ad.wait_frames(60)
        ad.set_camera(shot)
        frames, at = [], []
        n = 0
        first = True
        while n < until:
            step = 5 if first else every - (5 if n == 5 else 0)
            first = False
            p = os.path.join(out, "c.bmp")
            ad.capture(p, step)
            n += step
            at.append(n)
            frames.append(np.asarray(Image.open(p).convert("RGB").resize((1280, 720), Image.BOX), dtype=np.float32))
            os.remove(p)
        report["frame_s"] = float(ad.sess.state["real_dt"])
        last = frames[-1]
        report["curve"] = [{"frames_after_cut": a, "to_last": round(float(np.abs(f - last).mean()), 3),
                            "to_previous": round(float(np.abs(f - frames[i - 1]).mean()), 3) if i else None,
                            "brightness": round(float(f.mean()), 2)} for i, (a, f) in enumerate(zip(at, frames))]
        ad.end_frozen()
    finally:
        ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    for c in report["curve"]:
        print("%4d frames: to last %6.3f  to previous %s  brightness %.2f" % (
            c["frames_after_cut"], c["to_last"], "%6.3f" % c["to_previous"] if c["to_previous"] is not None else "     -", c["brightness"]))
    print("frame time %.3f s" % report["frame_s"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
