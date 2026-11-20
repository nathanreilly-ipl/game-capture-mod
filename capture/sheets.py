"""Render sheets for a captured take, from its frames cropped as the packager crops them.

ring.png       landscape near-ring temporal cameras at the first frame (every 4th of 32)
far_ring.png   the same for the far ring
sweep.png      the near spatial sweep at its frame (up to 12 poses)
portrait.png   portrait crops of four near temporal cameras
time.png       one camera over the take's clip frames (up to 12)
diverse.png    the Diverse trajectory (up to 8 poses)
Sheets whose cameras are not in the take are skipped.
"""
import os

from PIL import Image, ImageDraw

from .package import crop_scale
from .take import camera_uses, frame_paths, load


def tile(img, label, width):
    h = round(img.height * width / img.width)
    t = Image.new("RGB", (width, h + 20), (24, 24, 24))
    t.paste(img.resize((width, h), Image.LANCZOS), (0, 20))
    ImageDraw.Draw(t).text((5, 4), label, fill=(235, 235, 235))
    return t


def grid(tiles, cols):
    w = max(t.width for t in tiles)
    h = max(t.height for t in tiles)
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGB", (cols * w, rows * h), (24, 24, 24))
    for i, t in enumerate(tiles):
        out.paste(t, ((i % cols) * w, (i // cols) * h))
    return out


def spread(n, k):
    """Up to k indices spread evenly over range(n)."""
    if n <= k:
        return list(range(n))
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def make_sheets(take_dir, out_dir=None, log=print):
    out_dir = out_dir or os.path.join(take_dir, "sheets")
    os.makedirs(out_dir, exist_ok=True)
    _, shots = load(take_dir)
    files = frame_paths(take_dir)
    uses = camera_uses(shots)

    def frame(cam, i, by_pose=False):
        e = sorted(uses[cam], key=lambda x: x[1] if by_pose else x[0])[i]
        img = Image.open(files[e[2]]).convert("RGB")
        return crop_scale(img, e[3], e[4]), e

    made = []

    def sheet(name, items, cols, width):
        if items:
            grid([tile(img, label, width) for img, label in items], cols).save(os.path.join(out_dir, name))
            made.append(name)

    def ring(prefix, label):
        return [(frame(prefix % k, 0)[0], label % k) for k in range(0, 32, 4) if prefix % k in uses]

    sheet("ring.png", ring("H_near_temporal_%02d", "near temporal %02d"), 4, 420)
    sheet("far_ring.png", ring("H_far_temporal_%02d", "far temporal %02d"), 4, 420)
    sheet("portrait.png", [(frame("V_near_temporal_%02d" % k, 0)[0], "portrait near temporal %02d" % k)
                           for k in (0, 8, 16, 24) if "V_near_temporal_%02d" % k in uses], 4, 300)
    if "H_near_sweep_t000" in uses:
        n = len(uses["H_near_sweep_t000"])
        items = []
        for i in spread(n, 12):
            img, e = frame("H_near_sweep_t000", i, True)
            items.append((img, "near sweep pose %d" % e[1]))
        sheet("sweep.png", items, 4, 420)
    if "H_near_temporal_00" in uses:
        n = len(uses["H_near_temporal_00"])
        items = []
        for i in spread(n, 12):
            img, e = frame("H_near_temporal_00", i)
            items.append((img, "near temporal 00, clip frame %d" % e[0]))
        sheet("time.png", items, 3, 560)
    traj = sorted(c for c in uses if c.startswith("traj_"))
    if traj:
        n = len(uses[traj[0]])
        items = []
        for i in spread(n, 8):
            img, e = frame(traj[0], i, True)
            items.append((img, "%s pose %d" % (traj[0], e[1])))
        sheet("diverse.png", items, 4, 420)
    log("sheets in %s: %s" % (out_dir, ", ".join(made)))
    return made
