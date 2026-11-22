"""How many frames does the picture need after a camera cut?

Path tracing with Ray Reconstruction gathers light over frames, so right after a cut the frame
is not finished. In a held world at the player's spot: cut from a pose looking the other way
to a test pose, wait N frames, capture; repeat for each N. Every capture is compared with the
longest wait (mean absolute difference, levels of 255), and the longest wait with a second
capture of itself (what is left is noise that never settles, plus anything still animating).

    uv run --project . python -m adapters.cyberpunk.probes.settle_probe [--waits 5,10,20,40,80,160,320]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ..adapter import CyberpunkAdapter


def main(argv):
    waits = [int(v) for v in (argv[argv.index("--waits") + 1] if "--waits" in argv else "5,10,20,40,80,160,320").split(",")]
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_settle")
    os.makedirs(out, exist_ok=True)
    report = {"waits": {}}
    try:
        st = ad.subject_state()
        fwd, right, up = (np.array(v) for v in ad.heading_basis(st["facing_deg"]))
        eye = np.array(st["position"]) + up * 1.6 - fwd * 2.0
        ad.hide_subject(True)
        shot = {"pos": eye, "right": right, "fwd": fwd, "up": up, "vfov_deg": 60.0}
        away = dict(shot, right=-right, fwd=-fwd)
        ad.begin_frozen(shot)

        def cut_and_capture(n):
            ad.set_camera(away)
            ad.wait_frames(30)
            ad.set_camera(shot)
            p = os.path.join(out, "wait_%03d.bmp" % n)
            info = ad.capture(p, n)
            img = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
            os.remove(p)
            return img, info

        ref, info = cut_and_capture(max(waits))
        report["frame_s"] = float(ad.sess.state["real_dt"])
        again, _ = cut_and_capture(max(waits))
        report["longest_twice"] = float(np.abs(ref - again).mean())
        diff = np.abs(ref - again).mean(axis=2)
        report["longest_twice_share_over_8"] = float((diff > 8).mean())
        Image.fromarray(np.clip(diff * 8, 0, 255).astype(np.uint8)).resize((1280, 720)).save(
            os.path.join(out, "longest_twice_difference_x8.jpg"), quality=88)
        for n in waits:
            img, _ = cut_and_capture(n)
            d = np.abs(img - ref)
            report["waits"][n] = {"mean": float(d.mean()), "p99": float(np.percentile(d.mean(axis=2), 99))}
        Image.fromarray(ref.astype(np.uint8)).resize((1280, 720)).save(os.path.join(out, "reference.jpg"), quality=88)
        ad.end_frozen()
    finally:
        ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
