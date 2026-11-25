"""Evidence for a QC review of one take, from its files alone (docs/QC_LOOP.md): what a reviewer
looks at before opening full frames. Game-agnostic; runs on a QC round's data (JPEG frames, a
subset of a sweep's poses) as on the capturing machine's takes.

    uv run --project . python tools/qc_evidence.py <take folder> [--out DIR] [--width 2400]

Writes into <out> (default <take>/qc/evidence), with index.md listing everything:

- timestamps.md: every shot: clip frame, camera, game time, accepted or why not, the picture's
  brightness and saturation; and per clip frame whether the game time stood still across its shots
  (it must) and how far it moved from the frame before (1/fps);
- per camera with several clip frames: strip_<camera>.jpg (every clip frame, small) and
  diff_<camera>.jpg (|frame - frame before| x6 between neighbouring clip frames: steady motion shows
  as thin outlines, flicker and pops as patches that light up in one cell only);
- per pop that tools/temporal_flicker.py finds: pop_<camera>_<frame>.jpg, the clip frames around it
  cropped to the pop's box, at full resolution;
- near sweep: pose_<n>.jpg for the poses tools/sweep_flicker.py flags: the pose before, the pose,
  the pose after, and |pose - mean of its neighbours| x4 (what neither neighbour has).
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_flicker  # noqa: E402
import temporal_flicker  # noqa: E402
from take_frames import frame_file  # noqa: E402


def rows_of(take):
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def game_time(r):
    """The shot's game time in seconds: sim_time (Cyberpunk, The Witcher 3, KCD; seconds) or game_timer
    (RDR2, GTA V: the game's timer in milliseconds)."""
    if r.get("sim_time") not in (None, ""):
        return float(r["sim_time"])
    if r.get("game_timer") not in (None, ""):
        return float(r["game_timer"]) / 1000.0
    return None


def camera_of(name):
    head, rest = name.split("_", 1)
    return int(head[1:]), rest.rsplit("_", 1)[0]


def timestamps(take, rows, out, fps):
    lines = ["# Shots of %s\n" % os.path.basename(os.path.normpath(take)),
             "| clip frame | camera | game time | accepted | problems | brightness | saturation |", "|---|---|---|---|---|---|---|"]
    per_frame = defaultdict(set)
    for r in sorted(rows, key=lambda r: (camera_of(r["name"])[0], r["name"])):
        fr, cam = camera_of(r["name"])
        pic = r.get("picture") or {}
        lines.append("| %d | %s | %s | %s | %s | %.1f | %.1f |" % (
            fr, cam, "" if game_time(r) is None else "%.6f" % game_time(r), "yes" if r.get("accepted") else "no", "; ".join(r.get("problems") or []),
            pic.get("luminance", 0), pic.get("saturation", 0)))
        if r.get("accepted") and game_time(r) is not None:
            per_frame[fr].add(game_time(r))
    lines += ["", "## Game time per clip frame", "",
              "| clip frame | game time | the same across its shots | step from the frame before (s) | off 1/fps by (ms) |",
              "|---|---|---|---|---|"]
    prev = None
    for fr in sorted(per_frame):
        ts = sorted(per_frame[fr])
        step = (ts[0] - prev) if prev is not None else None
        lines.append("| %d | %.6f | %s | %s | %s |" % (
            fr, ts[0], "yes" if len(ts) == 1 else "NO: %d values, spread %.6f s" % (len(ts), ts[-1] - ts[0]),
            "%.6f" % step if step is not None else "", "%.3f" % ((step - 1.0 / fps) * 1000) if step is not None else ""))
        prev = ts[0]
    with open(os.path.join(out, "timestamps.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def grid(images, labels, cols, width):
    cell_w = width // cols
    ims = []
    for im, lab in zip(images, labels):
        im = im.resize((cell_w, max(1, round(im.height * cell_w / im.width))))
        ImageDraw.Draw(im).text((4, 4), lab, fill=(255, 255, 0))
        ims.append(im)
    rows_n = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, ims[0].height * rows_n))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * cell_w, (i // cols) * ims[0].height))
    return sheet


def clip_evidence(take, out, width, made):
    cams = temporal_flicker.cameras(take)
    for cam, shots in sorted(cams.items()):
        ims = [Image.open(p).convert("RGB") for _, p in shots]
        grid(ims, ["clip frame %d" % fr for fr, _ in shots], 6, width).save(os.path.join(out, "strip_%s.jpg" % cam), quality=88)
        made.append(("strip_%s.jpg" % cam, "%s, every clip frame" % cam))
        small = [np.asarray(im.resize((640, 360), Image.BOX), dtype=np.float32) for im in ims]
        diffs = [Image.fromarray(np.clip(np.abs(small[i + 1] - small[i]) * 6, 0, 255).astype(np.uint8))
                 for i in range(len(small) - 1)]
        grid(diffs, ["%d -> %d" % (shots[i][0], shots[i + 1][0]) for i in range(len(diffs))], 6, width).save(
            os.path.join(out, "diff_%s.jpg" % cam), quality=88)
        made.append(("diff_%s.jpg" % cam, "%s, |frame - frame before| x6" % cam))
        m, _ = temporal_flicker.measure(shots)
        for p in m.get("pops", [])[:8]:
            fr0 = p["clip_frame"]
            x, y, w, h = p["box"]
            W, H = ims[0].size
            pad = 0.04
            box = (int(max(0, x - pad) * W), int(max(0, y - pad) * H), int(min(1, x + w + pad) * W), int(min(1, y + h + pad) * H))
            sel = [(fr, im) for (fr, _), im in zip(shots, ims) if fr0 - 2 <= fr <= fr0 + 2]
            g = grid([im.crop(box) for _, im in sel], ["clip frame %d%s" % (fr, " (pop)" if fr == fr0 else "") for fr, _ in sel],
                     len(sel), min(width, (box[2] - box[0]) * len(sel)))
            name = "pop_%s_%d.jpg" % (cam, fr0)
            g.save(os.path.join(out, name), quality=92)
            made.append((name, "%s: a pop at clip frame %d, box %s (temporal_flicker), frames %d-%d" % (cam, fr0, p["box"], fr0 - 2, fr0 + 2)))


def sweep_evidence(take, out, width, made):
    m, _ = sweep_flicker.measure(take)
    paths = sweep_flicker.frames(take)
    for w in m.get("worst", [])[:5]:
        i = int(w["pose"])
        if not (0 < i < len(paths) - 1):
            continue
        a, b, c = (np.asarray(Image.open(paths[j]).convert("RGB"), dtype=np.float32) for j in (i - 1, i, i + 1))
        res = np.clip(np.abs(b - (a + c) / 2) * 4, 0, 255).astype(np.uint8)
        g = grid([Image.fromarray(x.astype(np.uint8)) for x in (a, b, c)] + [Image.fromarray(res)],
                 ["pose %d (before)" % (i - 1), "pose %d" % i, "pose %d (after)" % (i + 1), "|pose - mean of neighbours| x4"], 2, width)
        name = "pose_%03d.jpg" % i
        g.save(os.path.join(out, name), quality=90)
        made.append((name, "sweep pose %d (roughness %s): its neighbours and what neither has" % (i, w["roughness"])))
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take")
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--fps", type=float, default=30.0)
    a = ap.parse_args(argv)
    out = a.out or os.path.join(a.take, "qc", "evidence")
    os.makedirs(out, exist_ok=True)
    rows = rows_of(a.take)
    timestamps(a.take, rows, out, a.fps)
    made = [("timestamps.md", "every shot's clip frame, camera, game time and checks; game time per clip frame")]
    frames_per = {camera_of(r["name"])[0] for r in rows}
    if len(frames_per) > 2:
        clip_evidence(a.take, out, a.width, made)
    else:
        sweep_evidence(a.take, out, a.width, made)
    with open(os.path.join(out, "index.md"), "w", encoding="utf-8") as f:
        f.write("# Evidence for %s\n\n" % os.path.basename(os.path.normpath(a.take)))
        for name, what in made:
            f.write("- `%s`: %s\n" % (name, what))
    print("%d files in %s" % (len(made), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
