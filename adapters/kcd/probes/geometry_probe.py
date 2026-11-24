"""What the camera's numbers mean, measured from pictures of one held instant and from the pose the
engine reads back.

    uv run --project . python -m adapters.kcd.probes.geometry_probe [--fov 40,60,90] [--turn 2] [--poses 20]

1. Random camera bases (forward and up, with roll) turned into CryEngine angles by adapter.angles()
   and set: the forward and up the engine reads back against the ones asked (degrees).
2. Turning the camera by a small known angle about its own position moves the picture by
   f*tan(a) for a pinhole camera of focal length f pixels: per field of view, the shift for a yaw
   and a pitch turn, the focal length and the vertical and horizontal field of view it implies.
3. The roll of the picture for a roll of 10 degrees.
The world is held for the probe; frames under out/probes/kcd/geometry/.
"""
import argparse
import json
import math
import os

import numpy as np

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..adapter import angles
from ..session import Session, vec


def gray(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=np.float32)


def shift_of(a, b, size=1024):
    """(dx, dy) by which the middle of picture b is moved against a (phase correlation, sub-pixel)."""
    h, w = a.shape
    y0, x0 = (h - size) // 2, (w - size) // 2
    win = np.outer(np.hanning(size), np.hanning(size))
    fa = np.fft.fft2((a[y0:y0 + size, x0:x0 + size] - a.mean()) * win)
    fb = np.fft.fft2((b[y0:y0 + size, x0:x0 + size] - b.mean()) * win)
    r = fa.conj() * fb
    c = np.fft.ifft2(r / np.maximum(np.abs(r), 1e-9)).real
    py, px = np.unravel_index(np.argmax(c), c.shape)

    def refine(m1, m0, p1):
        d = m1 - 2 * m0 + p1
        return 0.0 if abs(d) < 1e-12 else 0.5 * (m1 - p1) / d
    sy = py + refine(c[(py - 1) % size, px], c[py, px], c[(py + 1) % size, px])
    sx = px + refine(c[py, (px - 1) % size], c[py, px], c[py, (px + 1) % size])
    if sy > size / 2:
        sy -= size
    if sx > size / 2:
        sx -= size
    return float(sx), float(sy), float(c.max())


def roll_of(a, b, size=900):
    """Degrees picture b is turned against a about its centre (a search over angles)."""
    from PIL import Image
    h, w = a.shape
    y0, x0 = (h - size) // 2, (w - size) // 2
    ia = Image.fromarray(a[y0:y0 + size, x0:x0 + size].astype(np.uint8))
    tb = b[y0:y0 + size, x0:x0 + size]
    m = size // 6
    best = None
    for step, span in ((1.0, 30.0), (0.1, 1.5), (0.01, 0.15)):
        centre = best[1] if best else 0.0
        for k in np.arange(centre - span, centre + span + 1e-9, step):
            ra = np.asarray(ia.rotate(float(k), resample=Image.BICUBIC), dtype=np.float32)
            err = float(np.mean((ra[m:-m, m:-m] - tb[m:-m, m:-m]) ** 2))
            if best is None or err < best[0]:
                best = (err, float(k))
    return best[1]


def angle_between(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return math.degrees(math.acos(float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fov", default="40,60,90")
    ap.add_argument("--turn", type=float, default=2.0)
    ap.add_argument("--settle", type=int, default=60)
    ap.add_argument("--poses", type=int, default=20)
    a = ap.parse_args()
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "kcd", "geometry")
    os.makedirs(out, exist_ok=True)
    st = s.cmd("hud", 0).state
    cam = vec(st["cam"])
    s.cmd("hide", 1)
    s.cmd("freeze")
    frames.wait(ex, 10)
    x, y, z = cam[0], cam[1], cam[2] + 0.5
    report = {"position": [x, y, z], "turn_deg": a.turn, "fovs": [], "bases": []}
    rng = np.random.default_rng(7)
    try:
        # 1. bases: asked against read back
        errs = []
        for _ in range(a.poses):
            f = rng.normal(size=3)
            f[2] *= 0.5
            f /= np.linalg.norm(f)
            u0 = np.array([0.0, 0.0, 1.0]) + rng.normal(size=3) * 0.3
            r = np.cross(f, u0)
            r /= np.linalg.norm(r)
            u = np.cross(r, f)
            pitch, roll, yaw = angles(f, u)
            got = s.cmd("pose", x, y, z, pitch, roll, yaw, 60).state
            ef, eu = angle_between(vec(got["fwd"]), f), angle_between(vec(got["up"]), u)
            ep = float(np.linalg.norm(np.array(vec(got["cam"])) - [x, y, z]))
            errs.append((ef, eu, ep))
        e = np.array(errs)
        report["bases"] = {"poses": len(errs), "forward_err_deg_max": round(float(e[:, 0].max()), 4),
                           "up_err_deg_max": round(float(e[:, 1].max()), 4), "position_err_m_max": round(float(e[:, 2].max()), 5)}
        print("%d random bases: forward within %.4f degrees, up within %.4f degrees, position within %.5f m"
              % (len(errs), e[:, 0].max(), e[:, 1].max(), e[:, 2].max()))

        def shot(name, pitch, roll, yaw, fov):
            s.cmd("pose", x, y, z, pitch, roll, yaw, fov)
            r = frames.shoot(ex, "geometry/" + name, after=a.settle)
            return gray(r["path"]), (r["width"], r["height"])

        # 2. focal length from small turns
        for fov in [float(v) for v in a.fov.split(",")]:
            base, (w, h) = shot("f%g_base" % fov, 0, 0, 0, fov)
            yawed, _ = shot("f%g_yaw" % fov, 0, 0, a.turn, fov)
            pitched, _ = shot("f%g_pitch" % fov, a.turn, 0, 0, fov)
            dx, dy1, q1 = shift_of(base, yawed)
            dx2, dy, q2 = shift_of(base, pitched)
            t = math.tan(math.radians(a.turn))
            fx, fy = abs(dx) / t, abs(dy) / t
            row = {"fov_set": fov, "size": [w, h], "yaw_shift_px": [round(dx, 3), round(dy1, 3)],
                   "pitch_shift_px": [round(dx2, 3), round(dy, 3)], "focal_px_from_yaw": round(fx, 2),
                   "focal_px_from_pitch": round(fy, 2),
                   "vfov_implied_deg": round(2 * math.degrees(math.atan((h / 2) / fy)), 3) if fy else None,
                   "hfov_implied_deg": round(2 * math.degrees(math.atan((w / 2) / fx)), 3) if fx else None,
                   "correlation": [round(q1, 3), round(q2, 3)]}
            report["fovs"].append(row)
            print("fov %g: a %+g degree yaw moves the picture %+.2f px (and %+.2f down), a pitch %+.2f px; "
                  "focal %.1f / %.1f px -> vertical %s, horizontal %s degrees"
                  % (fov, a.turn, dx, dy1, dy, fx, fy, row["vfov_implied_deg"], row["hfov_implied_deg"]))
        # 3. roll
        base, _ = shot("roll_base", 0, 0, 0, 60.0)
        rolled, _ = shot("roll_10", 0, 10.0, 0, 60.0)
        report["roll_10_turns_picture_deg"] = round(roll_of(base, rolled), 2)
        print("roll 10 turns the picture by %+.2f degrees (counter-clockwise positive)" % report["roll_10_turns_picture_deg"])
    finally:
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
