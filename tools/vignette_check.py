"""Does the picture darken (or brighten) toward its corners? A vignette is a per-camera effect a rig
of real cameras would not share (docs/VISUAL_CHECKS.md, C). Game-agnostic: reads a take's raw
frames. The frames of a sweep look at many different things, so their average is about even;
what is left of a radial fall-off in it is the renderer's or a post effect's.

    uv run --project . python tools/vignette_check.py <take folder> [...] [--out DIR]
    uv run --project . python tools/vignette_check.py --game G --location L [--view wide] [--reach 0.8]
        [--key F15 --key-after F14]   (a key pressed after the session opens, e.g. a ReShade preset, and one at the end)
        [--weather W] [--clock HH:MM]

From takes this is only a hint: a near sweep always looks at the rig's centre, so the middle of
its frames shows the same thing every time. The live mode (--game) settles it: one view in a held
world, then the camera turned so that the patch of scene at the centre lands near each corner
(at `reach` of the way from the centre to the corner, 0.8 by default); the patch's brightness
there against at the centre is the vignette, the scene the same (live_ratio per corner, 1.0 =
none). Exposure must not follow the view (the adapters hold it during a take).

Per take: the mean brightness (Rec. 709 luma, levels of 255) of the averaged frame in rings of
distance from the centre (0 = centre, 1 = a corner), and corner_ratio = the outer ring (0.9-1.0)
over the inner one (0-0.3). About 1.0 means no vignette; a vignette shows as 0.8 or less, while a
scene that is brighter at the top (sky) and darker at the bottom (ground) mostly cancels across
the four corners. --out saves the averaged frame and a profile.
"""
import json
import os
import sys

import numpy as np
from PIL import Image
from take_frames import frame_file  # noqa: E402

SIZE = (640, 360)
RINGS = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]


def frames(take):
    out = []
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            path = frame_file(take, e["file"]) if e.get("accepted") else None
            if path:
                out.append(path)
    return out


def measure(take):
    paths = frames(take)
    acc = None
    for p in paths:
        a = np.asarray(Image.open(p).convert("RGB").resize(SIZE, Image.BOX), dtype=np.float64)
        acc = a if acc is None else acc + a
    mean = acc / len(paths)
    luma = mean @ np.array([0.2126, 0.7152, 0.0722])
    h, w = luma.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((xx + 0.5 - w / 2) / (w / 2), (yy + 0.5 - h / 2) / (h / 2)) / np.sqrt(2)
    rings = [round(float(luma[(r >= a) & (r < b)].mean()), 2) for a, b in RINGS]
    corners = {}
    for name, (ys, xs) in {"top_left": (slice(0, h // 8), slice(0, w // 8)), "top_right": (slice(0, h // 8), slice(-w // 8, None)),
                           "bottom_left": (slice(-h // 8, None), slice(0, w // 8)),
                           "bottom_right": (slice(-h // 8, None), slice(-w // 8, None))}.items():
        corners[name] = round(float(luma[ys, xs].mean()), 2)
    return {"take": take, "frames": len(paths), "rings": dict(("%.1f-%.1f" % ab, v) for ab, v in zip(RINGS, rings)),
            "corner_ratio": round(rings[-1] / rings[0], 3), "corners": corners}, mean


def live(argv):
    """The same patch of scene at the centre and near each corner of a held view."""
    import time
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from capture import adapters_registry, paths
    from capture import locations as locs
    import upscaler_ab as u

    def arg(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    game, location = arg("--game", None), arg("--location", None)
    view, reach = arg("--view", "wide"), float(arg("--reach", 0.8))
    out = arg("--out", None) or os.path.join(paths.OUT, "checks", "vignette", time.strftime("%Y%m%d_%H%M%S") + "_" + game)
    os.makedirs(out)
    ad = adapters_registry.get(game)()
    ad.ensure_ready(restart=False)
    ad.open()
    key, key_after = arg("--key", None), arg("--key-after", None)
    report = {"game": game, "location": location, "view": view, "reach": reach, "key": key, "corners": {}}
    if key:   # e.g. a ReShade preset shortcut (RDR2: F15 = Reality Redemption 2 off), pressed after the session opens
        ad.press_key(key)
        time.sleep(3.0)
    try:
        loc = locs.get(paths.LOCATIONS, location)
        ad.go_to(loc["position"], loc["facing_deg"])
        if arg("--weather", None):
            report["weather"] = ad.set_weather(arg("--weather", None))
        if arg("--clock", None):
            report["clock"] = ad.set_clock(arg("--clock", None))
        st = ad.subject_state()
        base = u.views(ad, st, u.people(ad, st["position"]))[view]
        if hasattr(ad, "prepare_take"):
            ad.prepare_take({"steps": [{"shots": [base]}]})
        ad.hide_subject(True)
        ad.begin_frozen(base)
        settle = int(ad.settings.get("settle", 40))

        def shoot(name, pose):
            ad.set_camera(pose)
            path = os.path.join(out, name + ".bmp")
            ad.capture(path, settle * 2)
            a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) @ np.array([0.2126, 0.7152, 0.0722])
            Image.open(path).save(path[:-4] + ".png")
            os.remove(path)
            return a

        img0 = shoot("centre", base)
        H, W = img0.shape
        f = (H / 2) / np.tan(np.radians(base["vfov_deg"]) / 2)
        fwd0, right0, up0 = (np.asarray(base[k], float) for k in ("fwd", "right", "up"))
        half = max(8, int(0.03 * H))

        def patch(a, x, y):
            x, y = int(round(x)), int(round(y))
            return float(a[max(0, y - half):y + half, max(0, x - half):x + half].mean())

        c0 = patch(img0, W / 2, H / 2)
        for name, sx, sy in (("top_left", -1, 1), ("top_right", 1, 1), ("bottom_left", -1, -1), ("bottom_right", 1, -1)):
            # turn the camera so the centre's direction lands at (reach * corner): point offset in
            # pixels (dx, dy) means the camera turns the other way by atan(d / f)
            dx, dy = sx * reach * W / 2, sy * reach * H / 2
            yaw, pitch = -np.arctan2(dx, f), -np.arctan2(dy, f)
            fwd = fwd0 * np.cos(yaw) + right0 * np.sin(yaw)
            right = np.cross(fwd, up0)
            right /= np.linalg.norm(right)
            fwd2 = fwd * np.cos(pitch) + up0 * np.sin(pitch)
            up2 = np.cross(right, fwd2)
            pose = dict(base, fwd=list(fwd2), right=list(right), up=list(up2))
            img = shoot(name, pose)
            d = fwd0
            x = W / 2 + f * float(d @ right) / float(d @ fwd2)
            y = H / 2 - f * float(d @ up2) / float(d @ fwd2)
            c = patch(img, x, y)
            report["corners"][name] = {"at": [round(x), round(y)], "centre_luma": round(c0, 2), "corner_luma": round(c, 2),
                                       "live_ratio": round(c / c0, 3)}
            print(name, report["corners"][name], flush=True)
        back = shoot("centre_again", base)
        report["centre_again_luma"] = round(patch(back, W / 2, H / 2), 2)
    finally:
        try:
            ad.end_frozen()
            ad.hide_subject(False)
        finally:
            if key_after:   # and the one that undoes it (RDR2: F14), before the session ends
                ad.press_key(key_after)
                time.sleep(3.0)
            ad.close()
        with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        print("wrote", out)
    return 0


def main(argv):
    if "--game" in argv:
        return live(argv)
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    takes = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--out")]
    results = []
    for t in takes:
        r, mean = measure(t)
        results.append(r)
        print(json.dumps(r))
        if out:
            os.makedirs(out, exist_ok=True)
            name = "_".join(os.path.normpath(t).split(os.sep)[-3:-2] + [os.path.basename(os.path.normpath(t))])
            Image.fromarray(np.clip(mean, 0, 255).astype(np.uint8)).save(os.path.join(out, name + "_mean.png"))
    if out:
        with open(os.path.join(out, "vignette.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
