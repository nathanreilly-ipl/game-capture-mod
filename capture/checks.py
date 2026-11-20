"""Per-shot picture check: catches frames the game itself does not report as wrong,
such as a pause or loading screen, by comparing each frame's colour saturation and
brightness with the frames accepted just before it.

Measured on the full RDR2 take of 2026-11-20: normal frames have a mean saturation of
45-62 (0-255 scale); the pause-screen frames had 5-7.
"""
from collections import deque

import numpy as np
from PIL import Image


def frame_stats(path):
    img = Image.open(path).convert("RGB")
    img = img.reduce(max(1, img.width // 200))
    a = np.asarray(img, dtype=np.float32)
    return {"saturation": float((a.max(2) - a.min(2)).mean()), "luminance": float(a.mean())}


class PictureCheck:
    def __init__(self, window=40, min_saturation_ratio=0.35, min_luminance_ratio=0.25, warmup=5):
        self.recent = deque(maxlen=window)
        self.min_sat = min_saturation_ratio
        self.min_lum = min_luminance_ratio
        self.warmup = warmup

    def check(self, path):
        """(problems, stats). An empty problem list accepts the frame into the baseline."""
        st = frame_stats(path)
        problems = []
        if len(self.recent) >= self.warmup:
            sat = float(np.median([s["saturation"] for s in self.recent]))
            lum = float(np.median([s["luminance"] for s in self.recent]))
            if st["saturation"] < self.min_sat * sat:
                problems.append("picture grey: saturation %.1f against %.1f recently" % (st["saturation"], sat))
            if st["luminance"] < self.min_lum * lum:
                problems.append("picture dark: luminance %.1f against %.1f recently" % (st["luminance"], lum))
        if not problems:
            self.recent.append(st)
        return problems, st
