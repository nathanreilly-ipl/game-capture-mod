"""Images and videos for the project's documentation page.

    uv run --with numpy --with pillow tools/doc_media.py progress --reports reports --rig <rig.json> --out <media>/gcap_progress
    uv run --with numpy --with pillow tools/doc_media.py demo <take dir> --sheets reports/<take sheets> --out <media>/gcap_demos

progress: comparison images for the worklog, from the test reports and the rig file.
demo:     JPEG sheets and web videos (ring grid over time, frozen sweep, flythrough) from a
          packaged take. Needs ffmpeg (FFMPEG env var or on PATH).
"""
import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BG = (24, 24, 24)
FG = (235, 235, 235)


def ffmpeg():
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg not found: set FFMPEG")
    return exe


def save_jpg(img, path, width=None):
    if width and img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    img.convert("RGB").save(path, quality=88, optimize=True)
    print("wrote", path, img.size)


def labelled(img, label, pad=22):
    out = Image.new("RGB", (img.width, img.height + pad), BG)
    out.paste(img, (0, pad))
    ImageDraw.Draw(out).text((6, 5), label, fill=FG)
    return out


def stack(images):
    w = max(i.width for i in images)
    out = Image.new("RGB", (w, sum(i.height for i in images)), BG)
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height
    return out


def rig_plan(rig_path, size=1400):
    """Top-down and side views of every camera position of the rig, by kind."""
    with open(rig_path, encoding="utf-8") as f:
        rig = json.load(f)
    colours = {"temporal": (90, 160, 255), "freecam": (120, 220, 140), "moving": (255, 200, 60),
               "spacetime": (255, 120, 60), "sweep": (200, 120, 255), "trajectory": (255, 90, 160)}
    pts = []
    for cam in rig["cameras"]:
        c2w = np.array(cam["c2w"], dtype=float)
        if c2w.ndim == 2:
            c2w = c2w[None]
        for m in c2w:
            pts.append((cam["kind"], m[0, 3], m[1, 3], m[2, 3]))
    xs = np.array([p[1] for p in pts]); ys = np.array([p[2] for p in pts]); zs = np.array([p[3] for p in pts])
    half = max(np.abs(xs).max(), np.abs(zs).max()) * 1.05
    panel = size // 2

    def draw_panel(title, u, v, umin, umax, vmin, vmax):
        img = Image.new("RGB", (panel, panel), BG)
        d = ImageDraw.Draw(img)
        s = (panel - 60) / max(umax - umin, vmax - vmin)
        def to_px(a, b):
            return 30 + (a - umin) * s, panel - 30 - (b - vmin) * s
        # 1 m grid
        for g in range(math.floor(umin), math.ceil(umax) + 1):
            x0, _ = to_px(g, vmin); d.line([(x0, 30), (x0, panel - 30)], fill=(40, 40, 40))
        for g in range(math.floor(vmin), math.ceil(vmax) + 1):
            _, y0 = to_px(umin, g); d.line([(30, y0), (panel - 30, y0)], fill=(40, 40, 40))
        order = ["sweep", "trajectory", "moving", "spacetime", "freecam", "temporal"]
        radius = {"sweep": 0.6, "trajectory": 1, "moving": 1.5, "spacetime": 1.5, "freecam": 3.5, "temporal": 3.5}
        for kind in order:
            for (k, *_), a, b in zip(pts, u, v):
                if k != kind:
                    continue
                x, y = to_px(a, b)
                rr = radius[kind]
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=colours[kind])
        ox, oy = to_px(0, 0)
        d.ellipse([ox - 5, oy - 5, ox + 5, oy + 5], outline=FG, width=2)
        d.text((8, 6), title, fill=FG)
        return img

    top = draw_panel("top view (1 m grid), subject at the circle", xs, -zs, -half, half, -half, half)
    side = draw_panel("side view (1 m grid), floor at the circle", xs, ys, -half, half, -0.5, 2 * half - 0.5)
    out = Image.new("RGB", (panel * 2, panel + 40), BG)
    out.paste(top, (0, 0)); out.paste(side, (panel, 0))
    d = ImageDraw.Draw(out)
    x = 10
    for kind, c in colours.items():
        n = sum(1 for p in pts if p[0] == kind)
        d.rectangle([x, panel + 14, x + 12, panel + 26], fill=c)
        d.text((x + 18, panel + 14), "%s (%d poses)" % (kind, n), fill=FG)
        x += 230
    return out


def progress(args):
    os.makedirs(args.out, exist_ok=True)
    r = args.reports
    # 01: written pose against the engine's own render, and the first pose again at the end
    save_jpg(Image.open(os.path.join(r, "frozen_orbit", "compare", "sheet.png")),
             os.path.join(args.out, "01_written_pose_vs_engine_render.jpg"), 1920)
    # 02: difference to the engine render after 10 and after 40 ticks
    a = Image.open(os.path.join(r, "verify_geometry_settle", "sheets", "diff_ref__written_010.png"))
    b = Image.open(os.path.join(r, "verify_geometry_settle", "sheets", "diff_ref__written_040.png"))
    save_jpg(stack([a, b]), os.path.join(args.out, "02_settle_10_vs_40_ticks.jpg"), 1920)
    # 03: the rig's camera positions
    save_jpg(rig_plan(args.rig), os.path.join(args.out, "03_rig_camera_positions.jpg"))
    # 04: the sample take at 03:36 and at 12:00
    night = Image.open(os.path.join(r, "sample_take", "ring.png"))
    noon = Image.open(os.path.join(r, "sample_noon", "ring.png"))
    save_jpg(stack([labelled(night, "game clock 03:36"), labelled(noon, "game clock set to 12:00")]),
             os.path.join(args.out, "04_sample_night_vs_noon.jpg"), 1680)


def run(cmd):
    print(" ".join(cmd[:3]), "...", cmd[-1], flush=True)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def demo(args):
    os.makedirs(args.out, exist_ok=True)
    ff = ffmpeg()
    take = args.take
    p = args.prefix

    # sheets as JPEG (default: the take's own sheets/ folder)
    sheets = args.sheets or os.path.join(take, "sheets")
    for name in ("ring", "far_ring", "sweep", "portrait", "time", "diverse"):
        src = os.path.join(sheets, name + ".png")
        if os.path.exists(src):
            save_jpg(Image.open(src), os.path.join(args.out, "%s_%s.jpg" % (p, name)), 2400)

    with open(os.path.join(take, "take.json"), encoding="utf-8") as f:
        rig_file = json.load(f)["rig_file"]
    with open(rig_file, encoding="utf-8") as f:
        rig = json.load(f)
    labels = {c["name"]: c["meta"].get("production_label", c["name"]) for c in rig["cameras"]}

    def cam_video(name):
        """The camera's packaged video, or None when the take does not have that camera."""
        v = os.path.join(take, "package", labels.get(name, name), "rgb.mp4")
        return v if os.path.exists(v) else None

    # ring grid: 8 near temporal cameras over the clip frames, 2 x 4
    cams = ["H_near_temporal_%02d" % k for k in range(0, 32, 4)]
    if all(cam_video(c) for c in cams):
        inputs = []
        for c in cams:
            inputs += ["-i", cam_video(c)]
        tile_w, tile_h = 480, 274
        filt = ";".join("[%d:v]scale=%d:%d,setsar=1[v%d]" % (i, tile_w, tile_h, i) for i in range(len(cams)))
        layout = "|".join("%d_%d" % ((i % 4) * tile_w, (i // 4) * tile_h) for i in range(len(cams)))
        filt += ";" + "".join("[v%d]" % i for i in range(len(cams))) + "xstack=inputs=%d:layout=%s[out]" % (len(cams), layout)
        frames = ["-frames:v", str(args.ring_frames)] if args.ring_frames else []
        run([ff, "-y", *inputs, "-filter_complex", filt, "-map", "[out]", *frames, "-c:v", "libx264", "-crf", "23",
             "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             os.path.join(args.out, "%s_ring_over_time.mp4" % p)])

    # frozen sweeps and the flythrough at web size, for whichever the take has
    traj = sorted(n for n in labels if n.startswith("traj_"))
    for label, name in (("H_near_sweep_t000", "near_sweep"), ("H_far_sweep_t000", "far_sweep"),
                        (traj[0] if traj else "", "flythrough")):
        src = cam_video(label) if label else None
        if src:
            run([ff, "-y", "-i", src, "-vf", "scale=1344:768", "-c:v", "libx264", "-crf", "24",
                 "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 os.path.join(args.out, "%s_%s.mp4" % (p, name))])
    for f in sorted(os.listdir(args.out)):
        if f.startswith(p + "_"):
            print("%8.1f MB  %s" % (os.path.getsize(os.path.join(args.out, f)) / 1e6, f))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("progress")
    a.add_argument("--reports", default="reports")
    a.add_argument("--rig", required=True)
    a.add_argument("--out", required=True)
    b = sub.add_parser("demo")
    b.add_argument("take")
    b.add_argument("--sheets", help="sheets folder (default: <take>/sheets)")
    b.add_argument("--out", required=True)
    b.add_argument("--prefix", default="d01")
    b.add_argument("--ring-frames", type=int, default=0, help="keep only the first n clip frames in the ring video")
    args = ap.parse_args()
    progress(args) if args.cmd == "progress" else demo(args)


if __name__ == "__main__":
    main()
