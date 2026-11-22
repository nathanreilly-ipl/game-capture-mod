"""Does the game's own photo mode stop what a held world does not (screens, holograms, blinking
lights)? Opens photo mode with its key (N), captures the same view several times, a few frames
apart, and reports how much the captures differ and where; then leaves photo mode (Esc).
The photo-mode UI is in the frames; it does not move, so it does not count.

    uv run --project . python -m adapters.cyberpunk.probes.photomode_probe [--count 6] [--gap 30]
"""
import json
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image

from capture import paths as capture_paths

from ...common import window
from ..adapter import CyberpunkAdapter


def main(argv):
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 6
    gap = int(argv[argv.index("--gap") + 1]) if "--gap" in argv else 30
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_photomode")
    os.makedirs(out, exist_ok=True)
    report = {"count": count, "gap_frames": gap}
    try:
        window.focus(ad.hwnd)
        report["key_sent"] = window.press(ad.hwnd, 0x31)   # N
        time.sleep(4)
        st = ad.sess.cmd("wait", 240, timeout=120)
        report["photo_mode"] = ad.eval("return tostring(Game.GetPhotoModeSystem():IsPhotoModeActive())").strip()
        report["state"] = {k: st.get(k) for k in ("paused", "dilation", "sim_time", "real_dt")}
        frames = []
        for i in range(count):
            r = ad.sess.cmd("shoot", gap, "pm", timeout=120)
            p = os.path.join(out, "pm.bmp")
            shutil.move(ad._file(r["file"]), p)
            frames.append(np.asarray(Image.open(p).convert("RGB").resize((1280, 720), Image.BOX), dtype=np.float32))
            os.remove(p)
        f = np.stack(frames)
        report["sim_time_end"] = ad.sess.state.get("sim_time")
        report["brightness"] = [round(float(x.mean()), 3) for x in f]
        report["next_to_next"] = float(np.mean([np.abs(f[i] - f[i + 1]).mean() for i in range(count - 1)]))
        report["first_to_last"] = float(np.abs(f[0] - f[-1]).mean())
        sd = f.std(axis=0).mean(axis=2)
        report["share_of_pixels_std_over_4"] = float((sd > 4).mean())
        a = Image.fromarray(f.mean(axis=0).astype(np.uint8)).resize((800, 450))
        b = Image.fromarray(np.clip(sd * 16, 0, 255).astype(np.uint8)).convert("RGB").resize((800, 450))
        side = Image.new("RGB", (1600, 450))
        side.paste(a, (0, 0))
        side.paste(b, (800, 0))
        side.save(os.path.join(out, "side.jpg"), quality=80)
    finally:
        try:
            window.focus(ad.hwnd)
            window.press(ad.hwnd, "Esc")
            time.sleep(2)
        finally:
            ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
