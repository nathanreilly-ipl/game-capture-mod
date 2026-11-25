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
    """Each frame against the frames accepted before it from the same camera (key: a clip's fixed
    camera, or a sweep's path, whose neighbouring poses look alike), and more loosely against every
    camera's: a camera that looks at grey water or fog all take long is no pause screen (The Witcher
    3, Novigrad docks: a camera at saturation 11 against 42 for the others failed a take, QC round 4,
    2026-11-25), while a pause screen (RDR2: saturation 5-7 against 45-62) differs from both."""

    def __init__(self, window=40, min_saturation_ratio=0.35, min_luminance_ratio=0.25, warmup=5,
                 any_camera_saturation_ratio=0.18, any_camera_luminance_ratio=0.12, camera_warmup=2):
        self.recent = deque(maxlen=window)
        self.by_key = {}
        self.min_sat = min_saturation_ratio
        self.min_lum = min_luminance_ratio
        self.any_sat = any_camera_saturation_ratio
        self.any_lum = any_camera_luminance_ratio
        self.warmup = warmup
        self.camera_warmup = camera_warmup
        self.window = window

    def check(self, path, key=None):
        """(problems, stats). An empty problem list accepts the frame into the baselines. key: the
        camera (shot name without its clip frame and index); None compares with every camera alone."""
        st = frame_stats(path)
        problems = []
        own = self.by_key.setdefault(key, deque(maxlen=self.window)) if key is not None else None
        if own is not None and len(own) >= self.camera_warmup:
            base, sat_r, lum_r = own, self.min_sat, self.min_lum
        elif own is None and len(self.recent) >= self.warmup:
            base, sat_r, lum_r = self.recent, self.min_sat, self.min_lum
        elif len(self.recent) >= self.warmup:
            base, sat_r, lum_r = self.recent, self.any_sat, self.any_lum   # a camera's first frames
        else:
            base = None
        if base is not None:
            sat = float(np.median([s["saturation"] for s in base]))
            lum = float(np.median([s["luminance"] for s in base]))
            if st["saturation"] < sat_r * sat:
                problems.append("picture grey: saturation %.1f against %.1f recently" % (st["saturation"], sat))
            if st["luminance"] < lum_r * lum:
                problems.append("picture dark: luminance %.1f against %.1f recently" % (st["luminance"], lum))
        if not problems and own is not None and base is self.by_key.get(key) and len(self.recent) >= self.warmup:
            # also the loose check against every camera (a pause screen in a camera's own history)
            sat = float(np.median([s["saturation"] for s in self.recent]))
            if st["saturation"] < self.any_sat * sat:
                problems.append("picture grey: saturation %.1f against %.1f recently" % (st["saturation"], sat))
        if not problems:
            self.recent.append(st)
            if own is not None:
                own.append(st)
        return problems, st
