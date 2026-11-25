"""How much a sweep flickers: a camera path at one frozen instant (e.g. the ST-DM near sweep,
345 poses) should change smoothly from pose to pose. Game-agnostic: reads a take's raw frames in
the order they were captured (capture_log.jsonl).

Each frame is compared with the average of its two neighbours. Smooth camera motion mostly
cancels out (what is left is parallax at edges, the same for every take of the same rig at the
same place); flicker, which changes and changes back, does not. Reported per take:

    roughness        mean |f[i] - (f[i-1] + f[i+1]) / 2| in levels of 255 (frames at 480x270)
    share_over_12    share of pixels, over all frames, where that difference is above 12
    brightness_jitter    RMS of the same second difference of each frame's mean brightness
    worst            the poses with the most roughness (where to look in the video)

and a map of where it happens (mean over the sweep, x8).

    uv run --project . python tools/sweep_flicker.py <take folder> [<take folder> ...] [--out DIR] [--warp]

--warp: each neighbour is first turned into this pose's view by the rotation between the two cameras
(the homography K R_i R_j^T K^-1 from the take's shots.json), so the part of the change that is the
camera turning cancels; what moving the camera along the path shows (parallax) is left. Compare
warped numbers with warped numbers only.
"""
import json
import os
import sys

import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from take_frames import frame_file  # noqa: E402

SIZE = (480, 270)


def frames(take, with_names=False):
    paths = []
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            path = frame_file(take, e["file"]) if e.get("accepted") else None
            if path:      # a QC round may send a subset of the poses: the measure is then over those
                paths.append((path, e["name"]) if with_names else path)
    return paths


def _poses(take):
    """{shot name: (R world->camera with rows right, -up, fwd; vertical fov in degrees)} from shots.json."""
    with open(os.path.join(take, "shots.json"), encoding="utf-8") as f:
        shots = json.load(f)
    out = {}
    for st in shots["steps"]:
        for sh in st["shots"]:
            fwd, up = np.asarray(sh["fwd"], float), np.asarray(sh["up"], float)
            right = np.asarray(sh["right"], float) if "right" in sh else np.cross(fwd, up)
            out[sh["name"]] = (np.stack([right, -up, fwd]), float(sh["vfov_deg"]))
    return out


def _warp(img, R_src, R_dst, vfov):
    """img (seen from R_src) as seen from R_dst, the camera turned in place (PIL image, same size)."""
    w, h = img.size
    fy = (h / 2) / np.tan(np.radians(vfov) / 2)
    K = np.array([[fy, 0, w / 2], [0, fy, h / 2], [0, 0, 1.0]])
    M = K @ R_src @ R_dst.T @ np.linalg.inv(K)      # destination pixel -> source pixel
    M = M / M[2, 2]
    return img.transform(img.size, Image.PERSPECTIVE, tuple(M.flatten()[:8]), Image.BILINEAR)


def measure(take, warp=False):
    named = frames(take, with_names=True)
    paths = [p for p, _ in named]
    if len(paths) < 3:
        raise SystemExit("%s: fewer than 3 accepted frames" % take)
    poses = _poses(take) if warp else None
    prev2 = prev = None
    rough, over, lum, heat, per = 0.0, 0.0, [], None, []
    n = 0
    ims = [None, None, None]     # PIL images of the last three poses (for --warp)
    names = [None, None, None]
    for p, name in named:
        im = Image.open(p).convert("RGB").resize(SIZE, Image.BOX)
        f = np.asarray(im, dtype=np.float32)
        ims, names = ims[1:] + [im], names[1:] + [name]
        lum.append(float(f.mean()))
        if prev2 is not None:
            if warp and all(nm in poses for nm in names):
                R0, R1, R2 = (poses[nm][0] for nm in names)
                v = poses[names[1]][1]
                a = np.asarray(_warp(ims[0], R0, R1, v), dtype=np.float32)
                c = np.asarray(_warp(ims[2], R2, R1, v), dtype=np.float32)
                d = np.abs(prev - (a + c) / 2).mean(axis=2)
                d[:6, :] = d[-6:, :] = 0      # the borders a turned neighbour does not cover
                d[:, :6] = d[:, -6:] = 0
            else:
                d = np.abs(prev - (prev2 + f) / 2).mean(axis=2)
            rough += float(d.mean())
            over += float((d > 12).mean())
            heat = d if heat is None else heat + d
            per.append(float(d.mean()))
            n += 1
        prev2, prev = prev, f
    lum = np.array(lum)
    jitter = float(np.sqrt(np.mean((lum[1:-1] - (lum[:-2] + lum[2:]) / 2) ** 2)))
    worst = sorted(range(len(per)), key=lambda i: -per[i])[:5]
    return {"take": take, "frames": len(paths), "warped": bool(warp), "roughness": round(rough / n, 4),
            "share_over_12": round(over / n, 5), "brightness_jitter": round(jitter, 4),
            "worst": [{"pose": i + 1, "roughness": round(per[i], 3)} for i in worst]}, heat / n


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    warp = "--warp" in argv
    takes = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--out")]
    results = []
    for t in takes:
        r, heat = measure(t, warp)
        results.append(r)
        print(json.dumps(r))
        if out:
            os.makedirs(out, exist_ok=True)
            name = "_".join(os.path.normpath(t).split(os.sep)[-3:-1] + [os.path.basename(os.path.normpath(t))])
            Image.fromarray(np.clip(heat * 8, 0, 255).astype(np.uint8)).save(os.path.join(out, name + "_flicker_x8.png"))
    if out:
        with open(os.path.join(out, "sweep_flicker.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
