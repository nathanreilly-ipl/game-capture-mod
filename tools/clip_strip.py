"""One camera's clip frames side by side, optionally a crop of them: the way to look at a flicker,
a pop or a drift that tools/temporal_flicker.py found (its boxes are fractions of the frame, the
same as --crop here). Game-agnostic: reads a take's raw frames (capture_log.jsonl).

    uv run --project . python tools/clip_strip.py <take folder> <camera> <out.jpg>
        [--from 1] [--count 12] [--crop x,y,w,h] [--cols 6] [--width 2400] [--diff]

--diff: under each clip frame, |this frame - the one before| x6 (the same crop): a one-frame
flicker lights up in two neighbouring cells, steady motion in all of them.

<camera> is a camera as the capture log names it (near_temporal_00, near_moving, ...). The
crop is x, y, width, height as fractions of the frame (0.78,0,0.22,0.5 = the upper right).
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from take_frames import frame_file  # noqa: E402


def shots(take, camera):
    """[(clip frame, path)] of a camera's accepted shots. The clip frame comes from the shot's name
    (t<frame>_<camera>_<index>): older takes of The Witcher 3 and Kingdom Come logged the game's own
    frame counter as "frame"."""
    out = []
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            head, rest = e["name"].split("_", 1)
            path = frame_file(take, e["file"]) if e.get("accepted") and rest.rsplit("_", 1)[0] == camera else None
            if path:
                out.append((int(head[1:]), path))
    return sorted(out)


def strip(take, camera, out, first=1, count=12, crop=None, cols=6, width=2400, diff=False):
    all_shots = shots(take, camera)
    picked = [s for s in all_shots if first <= s[0] < first + count]
    if not picked:
        raise SystemExit("no accepted shots of %s from clip frame %d in %s" % (camera, first, take))
    cell_w = width // cols

    def load(path):
        im = Image.open(path).convert("RGB")
        if crop:
            W, H = im.size
            x, y, w, h = crop
            im = im.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)))
        return im

    ims = []
    before = {fr: p for fr, p in all_shots}
    for frame, path in picked:
        full = load(path)
        im = full.resize((cell_w, max(1, round(full.height * cell_w / full.width))))
        ImageDraw.Draw(im).text((4, 4), "clip frame %d" % frame, fill=(255, 255, 0))
        if diff:
            import numpy as np
            prev = [fr for fr in before if fr < frame]
            if prev:
                a = np.asarray(load(before[max(prev)]), dtype=np.float32)
                d = Image.fromarray(np.clip(np.abs(np.asarray(full, dtype=np.float32) - a) * 6, 0, 255).astype(np.uint8))
            else:
                d = Image.new("RGB", full.size)
            d = d.resize(im.size)
            ImageDraw.Draw(d).text((4, 4), "%s -> %d (x6)" % (max(prev) if prev else "-", frame), fill=(255, 255, 0))
            both = Image.new("RGB", (im.width, im.height * 2))
            both.paste(im, (0, 0))
            both.paste(d, (0, im.height))
            im = both
        ims.append(im)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, ims[0].height * rows))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * cell_w, (i // cols) * ims[0].height))
    sheet.save(out, quality=88)
    return len(ims), sheet.size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take")
    ap.add_argument("camera")
    ap.add_argument("out")
    ap.add_argument("--from", dest="first", type=int, default=1)
    ap.add_argument("--count", type=int, default=12)
    ap.add_argument("--crop", help="x,y,w,h as fractions of the frame")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--diff", action="store_true", help="each frame's difference to the one before, under it")
    a = ap.parse_args(argv)
    crop = [float(v) for v in a.crop.split(",")] if a.crop else None
    n, size = strip(a.take, a.camera, a.out, a.first, a.count, crop, a.cols, a.width, a.diff)
    print("%d clip frames, %dx%d -> %s" % (n, size[0], size[1], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
