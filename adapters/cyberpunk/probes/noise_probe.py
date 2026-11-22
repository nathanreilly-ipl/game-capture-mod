"""What is the difference between two captures of one pose in a held world made of?

Path tracing leaves noise that waiting does not remove (settle_probe.py: two captures after 320
frames still differ). Here one pose is captured many times, a few frames apart, and the captures
compared: one against another, the average of one half against the average of the other half
(independent noise shrinks with the square root of the count; a slow drift or a moving thing
does not), and the brightness of each capture (a drifting exposure shows there).

    uv run --project . python -m adapters.cyberpunk.probes.noise_probe [--count 12] [--gap 4] [--eval "<lua>"]
"""
import json
import os
import sys

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ..adapter import CyberpunkAdapter


def main(argv):
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 12
    gap = int(argv[argv.index("--gap") + 1]) if "--gap" in argv else 4
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_noise")
    os.makedirs(out, exist_ok=True)
    report = {"count": count, "gap_frames": gap}
    try:
        st = ad.subject_state()
        fwd, right, up = (np.array(v) for v in ad.heading_basis(st["facing_deg"]))
        eye = np.array(st["position"]) + up * 1.6 - fwd * 2.0
        ad.hide_subject(True)
        ad.begin_frozen({"pos": eye, "right": right, "fwd": fwd, "up": up, "vfov_deg": 60.0})
        if "--eval" in argv:   # Lua to run in the held world first, e.g. an engine option to try
            report["eval"] = argv[argv.index("--eval") + 1]
            report["eval_answer"] = ad.eval(report["eval"]).strip()
        ad.wait_frames(120)
        frames = []
        for i in range(count):
            p = os.path.join(out, "n.bmp")
            ad.capture(p, gap)
            frames.append(np.asarray(Image.open(p).convert("RGB").resize((1280, 720), Image.BOX), dtype=np.float32))
            os.remove(p)
        report["frame_s"] = float(ad.sess.state["real_dt"])
        report["health_at_end"] = ad.health()["problems"]
        if "--eval-after" in argv:   # Lua to undo what --eval did
            ad.eval(argv[argv.index("--eval-after") + 1])
        f = np.stack(frames)
        report["brightness"] = [round(float(x.mean()), 3) for x in f]
        report["next_to_next"] = float(np.mean([np.abs(f[i] - f[i + 1]).mean() for i in range(count - 1)]))
        report["first_to_last"] = float(np.abs(f[0] - f[-1]).mean())
        half = count // 2
        report["halves_interleaved"] = float(np.abs(f[0::2].mean(axis=0) - f[1::2].mean(axis=0)).mean())
        report["halves_first_second"] = float(np.abs(f[:half].mean(axis=0) - f[half:].mean(axis=0)).mean())
        report["independent_noise_would_give"] = report["next_to_next"] / (half ** 0.5)
        sd = f.std(axis=0).mean(axis=2)
        report["per_pixel_std_mean"] = float(sd.mean())
        report["share_of_pixels_std_over_4"] = float((sd > 4).mean())
        Image.fromarray(np.clip(sd * 16, 0, 255).astype(np.uint8)).save(os.path.join(out, "std_x16.jpg"), quality=88)
        Image.fromarray(f.mean(axis=0).astype(np.uint8)).save(os.path.join(out, "average.jpg"), quality=90)
        ad.end_frozen()
    finally:
        ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
