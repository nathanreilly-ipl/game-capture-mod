"""One camera's clip frames side by side, optionally a crop of them: the way to look at a flicker,
a pop or a drift that tools/temporal_flicker.py found (its boxes are fractions of the frame, the
same as --crop here). Game-agnostic: reads a take's raw frames (capture_log.jsonl).

    uv run --project . python tools/clip_strip.py <take folder> <camera> <out.jpg>
        [--from 1] [--count 12] [--crop x,y,w,h] [--cols 6] [--width 2400]

<camera> is a camera as the capture log names it (near_temporal_00, near_moving, ...). The
crop is x, y, width, height as fractions of the frame (0.78,0,0.22,0.5 = the upper right).
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw


def shots(take, camera):
    out = []
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("accepted") and e["name"].split("_", 1)[1].rsplit("_", 1)[0] == camera:
                out.append((int(e["frame"]), os.path.join(take, e["file"])))
    return sorted(out)


def strip(take, camera, out, first=1, count=12, crop=None, cols=6, width=2400):
    picked = [s for s in shots(take, camera) if first <= s[0] < first + count]
    if not picked:
        raise SystemExit("no accepted shots of %s from clip frame %d in %s" % (camera, first, take))
    cell_w = width // cols
    ims = []
    for frame, path in picked:
        im = Image.open(path).convert("RGB")
        if crop:
            W, H = im.size
            x, y, w, h = crop
            im = im.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)))
        im = im.resize((cell_w, max(1, round(im.height * cell_w / im.width))))
        ImageDraw.Draw(im).text((4, 4), "clip frame %d" % frame, fill=(255, 255, 0))
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
    a = ap.parse_args(argv)
    crop = [float(v) for v in a.crop.split(",")] if a.crop else None
    n, size = strip(a.take, a.camera, a.out, a.first, a.count, crop, a.cols, a.width)
    print("%d clip frames, %dx%d -> %s" % (n, size[0], size[1], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
