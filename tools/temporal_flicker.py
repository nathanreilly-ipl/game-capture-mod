"""How much a camera that films over time flickers: in a take with several clip frames (a temporal
ring, the ST-DM moving and temporal cameras), the world moves 1/fps between clip frames and a
fixed camera's picture should change smoothly. Game-agnostic: reads a take's raw frames by
camera, in clip-frame order (capture_log.jsonl).

Each clip frame is compared with the average of its two neighbours, as tools/sweep_flicker.py
does along a sweep. Steady motion cancels (people walking, traffic, a camera moving at a constant
speed leave only their edges); flicker, which changes and changes back, does not. Per camera:

    roughness        mean |f[i] - (f[i-1] + f[i+1]) / 2| in levels of 255 (frames at 480x270)
    share_over_12    share of pixels, over all clip frames, where that difference is above 12
    brightness_jitter    RMS of the same second difference of each frame's mean brightness
    first_step       mean |f[2] - f[1]| against the mean step between later neighbours (a first
                     clip frame that differs, e.g. an exposure flash, shows as a ratio well over 1)
    worst            the clip frames with the most roughness (where to look in the video)
    exposure_drift   the whole frame's brightness at the last clip frame against the first, from the
                     pixels that hardly change (ratio of their means; moving things left out): 1.0 is steady,
                     0.96 is 4% darker. exposure_by_frame has it per clip frame; a drift that settles
                     after a few frames is an eye still adapting, one that goes on is the light changing
    pops             things that appear, vanish or change form in one step while the steps before
                     and after are calm there and around it: a person or car popping in or out, a
                     level of detail switching, a shadow or reflection jumping (a moving limb next to
                     it in the step before or after makes it motion, not a pop). Each pop is a clip frame and
                     a box (x, y, w, h as fractions of the frame); `pops.png` per camera draws them

and a map of where it happens per camera (mean over the clip frames, x8).

    uv run --project . python tools/temporal_flicker.py <take folder> [...] [--out DIR] [--camera SUBSTR] [--size 960x540]

Roughness and the maps are at 480x270 by default (numbers comparable between takes only at one
size); --size 960x540 finds pops down to about 16x16 pixels of a 2560x1440 frame.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
from PIL import Image

SIZE = (480, 270)


def cameras(take):
    """{camera name: [(clip frame, path)]} for the accepted shots of a take, cameras with 3 or more
    clip frames only. A shot's name is t<frame>_<camera>_<index>; the clip frame is read from the
    name, since takes of The Witcher 3 and Kingdom Come before 2026-11-24 logged the game's own frame
    counter as "frame"."""
    by = defaultdict(list)
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if not e.get("accepted"):
                continue
            head, rest = e["name"].split("_", 1)
            cam = rest.rsplit("_", 1)[0]
            by[cam].append((int(head[1:]), os.path.join(take, e["file"])))
    return {c: sorted(v) for c, v in by.items() if len({fr for fr, _ in v}) >= 3}


def load(path):
    return np.asarray(Image.open(path).convert("RGB").resize(SIZE, Image.BOX), dtype=np.float32)


POP_JUMP, POP_CALM, BLOCK = 24.0, 6.0, 6   # levels of 255; blocks of 6x6 pixels at 480x270


def components(mask):
    """Connected regions (4-neighbour) of a 2-D boolean array: [(y0, x0, y1, x1, size)]."""
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    h, w = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, cells = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            cells.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        ys, xs = [c[0] for c in cells], [c[1] for c in cells]
        out.append((min(ys), min(xs), max(ys) + 1, max(xs) + 1, len(cells)))
    return out


def pops(fs, frames):
    """Regions that jump in one step (difference over POP_JUMP) where the step before and the step
    after are calm (under POP_CALM): a thing appearing or vanishing, not moving or flickering."""
    found = []
    d = [np.abs(fs[i + 1] - fs[i]).mean(axis=2) for i in range(len(fs) - 1)]
    for i in range(1, len(d) - 1):
        m = (d[i] > POP_JUMP) & (d[i - 1] < POP_CALM) & (d[i + 1] < POP_CALM)
        h, w = m.shape
        blocks = m[: h - h % BLOCK, : w - w % BLOCK].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean(axis=(1, 3)) > 0.15
        moving = [(d[j] > POP_JUMP)[: h - h % BLOCK, : w - w % BLOCK].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).mean(axis=(1, 3))
                  for j in (i - 1, i + 1)]
        for y0, x0, y1, x1, n in components(blocks):
            if n < 2:   # one block (36 pixels at 480x270) is noise or an edge
                continue
            # something moving right next to it in the step before or after (a walker's foot
            # leaving the ground, an arm swinging) is motion, not a thing popping
            ya, yb, xa, xb = max(0, y0 - 2), y1 + 2, max(0, x0 - 2), x1 + 2
            if max(float((m_[ya:yb, xa:xb] > 0.15).mean()) for m_ in moving) > 0.08:
                continue
            found.append({"clip_frame": frames[i + 1], "box": [round(x0 * BLOCK / w, 3), round(y0 * BLOCK / h, 3),
                                                                round((x1 - x0) * BLOCK / w, 3), round((y1 - y0) * BLOCK / h, 3)],
                          "blocks": n})
    return sorted(found, key=lambda p: -p["blocks"])


def draw_pops(path, found, out):
    from PIL import ImageDraw
    im = Image.open(path).convert("RGB")
    W, H = im.size
    dr = ImageDraw.Draw(im)
    for p in found[:40]:
        x, y, w, h = p["box"]
        dr.rectangle([x * W - 4, y * H - 4, (x + w) * W + 4, (y + h) * H + 4], outline=(255, 40, 40), width=4)
        dr.text((x * W, max(0, y * H - 18)), "frame %d" % p["clip_frame"], fill=(255, 255, 0))
    im.resize((W // 2, H // 2)).save(out)


def measure(shots):
    fs = [load(p) for _, p in shots]
    frames = [fr for fr, _ in shots]
    per, heat, over = [], None, 0.0
    for i in range(1, len(fs) - 1):
        d = np.abs(fs[i] - (fs[i - 1] + fs[i + 1]) / 2).mean(axis=2)
        per.append(float(d.mean()))
        over += float((d > 12).mean())
        heat = d if heat is None else heat + d
    lum = np.array([f.mean() for f in fs])
    jitter = float(np.sqrt(np.mean((lum[1:-1] - (lum[:-2] + lum[2:]) / 2) ** 2)))
    steps = [float(np.abs(fs[i + 1] - fs[i]).mean()) for i in range(len(fs) - 1)]
    later = float(np.mean(steps[1:])) if len(steps) > 1 else 0.0
    worst = sorted(range(len(per)), key=lambda i: -per[i])[:5]
    n = len(per)
    found = pops(fs, frames)
    # The whole frame getting brighter or darker, apart from anything that moves: per clip frame,
    # its brightness against clip frame 1's over the pixels that changed less than a quarter (an exposure
    # change multiplies every pixel alike; a passing cart or person does not count)
    g0 = fs[0].mean(axis=2)
    drift = []
    for f in fs:
        g = f.mean(axis=2)
        m = (g0 > 20) & (g0 < 220) & (np.abs(g - g0) < 0.25 * g0)
        # the ratio of the means: a median of per-pixel ratios cannot see a change under a level
        # (whole-number pixels stay equal, the median stays 1.0)
        drift.append(round(float(g[m].sum() / g0[m].sum()), 4) if m.any() else None)
    return {"clip_frames": len(fs), "roughness": round(sum(per) / n, 4), "share_over_12": round(over / n, 5),
            "brightness_jitter": round(jitter, 4), "brightness_first_last": [round(float(lum[0]), 2), round(float(lum[-1]), 2)],
            "first_step": round(steps[0], 3), "first_step_ratio": round(steps[0] / later, 2) if later else None,
            "worst": [{"clip_frame": frames[i + 1], "roughness": round(per[i], 3)} for i in worst],
            "pop_count": len(found), "pops": found[:20],
            "exposure_drift": drift[-1], "exposure_drift_range": [min(v for v in drift if v), max(v for v in drift if v)],
            "exposure_by_frame": drift}, heat / n


def main(argv):
    global SIZE
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    only = argv[argv.index("--camera") + 1] if "--camera" in argv else None
    if "--size" in argv:   # e.g. 960x540: finer pops (small people far away), 4x the time
        SIZE = tuple(int(v) for v in argv[argv.index("--size") + 1].split("x"))
    skip = {i + 1 for i, a in enumerate(argv) if a in ("--out", "--camera", "--size")}
    takes = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
    results = []
    for t in takes:
        for cam, shots in sorted(cameras(t).items()):
            if only and only not in cam:
                continue
            r, heat = measure(shots)
            r = {"take": t, "camera": cam, **r}
            results.append(r)
            print(json.dumps(r))
            if out:
                os.makedirs(out, exist_ok=True)
                name = "_".join(os.path.normpath(t).split(os.sep)[-3:-2] + [os.path.basename(os.path.normpath(t)), cam])
                Image.fromarray(np.clip(heat * 8, 0, 255).astype(np.uint8)).save(os.path.join(out, name + "_flicker_x8.png"))
                if r["pops"]:
                    draw_pops(shots[len(shots) // 2][1], r["pops"], os.path.join(out, name + "_pops.png"))
    if out:
        with open(os.path.join(out, "temporal_flicker.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
