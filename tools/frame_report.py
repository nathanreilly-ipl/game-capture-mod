"""Contact sheet and difference report for the frames of one capture job.

    uv run --with pillow --with numpy tools/frame_report.py <job folder> --out reports/<name>
        [--pairs 03_frozen_a:04_frozen_b 03_frozen_a:05_frozen_c]

Writes into --out:
    sheet.png       every frame of the job, labelled
    diff_<a>__<b>.png   for each pair: a, b, and a heat map of |a - b| (amplified)
    report.json     per-pair difference statistics
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw

LABEL_H = 22


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def labelled(img, text, width):
    scale = width / img.width
    small = img.resize((width, round(img.height * scale)), Image.LANCZOS)
    tile = Image.new("RGB", (width, small.height + LABEL_H), (24, 24, 24))
    tile.paste(small, (0, LABEL_H))
    ImageDraw.Draw(tile).text((6, 4), text, fill=(235, 235, 235))
    return tile


def grid(tiles, cols):
    rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheet = Image.new("RGB", (cols * w, rows * h), (24, 24, 24))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * w, (i // cols) * h))
    return sheet


def heat(diff, gain):
    """|a - b| per pixel (max over channels) -> black / red / yellow / white map."""
    d = np.clip(diff.astype(np.float32) * gain / 255.0, 0, 1)
    r = np.clip(d * 3, 0, 1)
    g = np.clip(d * 3 - 1, 0, 1)
    b = np.clip(d * 3 - 2, 0, 1)
    return Image.fromarray((np.stack([r, g, b], axis=-1) * 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", nargs="*", default=[])
    ap.add_argument("--tile-width", type=int, default=640)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--gain", type=float, default=16.0, help="heat map amplification")
    ap.add_argument("--threshold", type=int, default=4, help="a pixel counts as changed above this (0-255)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    names = sorted(f[:-4] for f in os.listdir(args.job_dir) if f.lower().endswith(".bmp"))
    if not names:
        raise SystemExit("no .bmp frames in " + args.job_dir)
    frames = {n: load(os.path.join(args.job_dir, n + ".bmp")) for n in names}

    tiles = [labelled(Image.fromarray(frames[n].astype(np.uint8)), n, args.tile_width) for n in names]
    grid(tiles, args.cols).save(os.path.join(args.out, "sheet.png"))

    report = {"job_dir": os.path.abspath(args.job_dir), "frames": names,
              "size": [int(frames[names[0]].shape[1]), int(frames[names[0]].shape[0])], "pairs": []}
    for pair in args.pairs:
        a, b = pair.split(":")
        diff = np.abs(frames[a] - frames[b]).max(axis=-1)
        changed = diff > args.threshold
        ys, xs = np.nonzero(changed)
        entry = {
            "a": a, "b": b,
            "mean_abs_diff": round(float(diff.mean()), 4),
            "max_abs_diff": int(diff.max()),
            "changed_share": round(float(changed.mean()), 6),
            "changed_bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None,
            # share of changed pixels in each cell of a 4 x 4 grid (rows top to bottom)
            "changed_share_4x4": [[round(float(c.mean()), 4) for c in np.array_split(r, 4, axis=1)]
                                  for r in np.array_split(changed, 4, axis=0)],
        }
        report["pairs"].append(entry)
        w = args.tile_width
        row = [labelled(Image.fromarray(frames[a].astype(np.uint8)), a, w),
               labelled(Image.fromarray(frames[b].astype(np.uint8)), b, w),
               labelled(heat(diff, args.gain), "|a - b| x%g   changed %.2f%%   max %d"
                        % (args.gain, 100 * entry["changed_share"], entry["max_abs_diff"]), w)]
        grid(row, 3).save(os.path.join(args.out, "diff_%s__%s.png" % (a, b)))

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report["pairs"], indent=1))


if __name__ == "__main__":
    main()
