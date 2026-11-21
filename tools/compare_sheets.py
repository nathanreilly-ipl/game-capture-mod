"""Readable comparison sheets, with NVIDIA's FLIP error maps (flip-evaluator, LDR, 67 pixels per
degree): where and how much two pictures differ as a viewer would see it, 0 (same) to 1 (most
different), shown with the magma colour scale. Game-agnostic.

    uv run --project . python tools/compare_sheets.py            # every comparison under out/checks
    uv run --project . python tools/compare_sheets.py <folder>   # one comparison

Pages of four rows, a title band, column titles, row labels with the numbers, and a crops
version (the centre third, enlarged) of every page. Understands the folders written by
tools/preset_ab.py (ReShade presets, e.g. ray tracing off/on), tools/upscaler_ab.py (DLSS 5
off/on) and tools/upscaler_sweep.py (one start per setting). FLIP maps are cached in <folder>/flip/.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import paths  # noqa: E402

FONTS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts")
BG, FG, MUTED, ACCENT = (24, 24, 26), (240, 240, 240), (170, 170, 175), (255, 196, 92)


def font(size, bold=False):
    for name in (("arialbd.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")):
        p = os.path.join(FONTS, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def flip_map(folder, ref, test, key):
    """(path of the FLIP map PNG, mean FLIP error), cached in <folder>/flip/."""
    import flip_evaluator
    d = os.path.join(folder, "flip")
    os.makedirs(d, exist_ok=True)
    png, meta = os.path.join(d, key + ".png"), os.path.join(d, "flip.json")
    cache = json.load(open(meta)) if os.path.exists(meta) else {}
    if key in cache and os.path.exists(png):
        return png, cache[key]
    m, mean, _ = flip_evaluator.evaluate(load(ref), load(test), "LDR")
    Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).save(png)
    cache[key] = float(mean)
    json.dump(cache, open(meta, "w"), indent=1)
    return png, float(mean)


def pixel_diff(a, b):
    return float(np.abs(load(a) - load(b)).mean() * 255)


MAGMA = [(0.0, (0, 0, 4)), (0.125, (28, 16, 68)), (0.25, (79, 18, 123)), (0.375, (129, 37, 129)),
         (0.5, (181, 54, 122)), (0.625, (229, 80, 100)), (0.75, (251, 135, 97)), (0.875, (254, 194, 135)),
         (1.0, (252, 253, 191))]  # stops of the magma colour scale FLIP maps use


def _magma_bar(w, h):
    xs = np.linspace(0, 1, w)
    stops = np.array([s for s, _ in MAGMA])
    row = np.stack([np.interp(xs, stops, [c[i] for _, c in MAGMA]) for i in range(3)], axis=1).astype(np.uint8)
    return Image.fromarray(np.repeat(row[None], h, axis=0))


def render(rows, col_titles, title, subtitle, out_prefix, crop=False, flip_cols=(), rows_per_page=4, cell_w=None):
    """rows: [{"label": str, "notes": [str], "cells": [image path or None]}]. Writes
    <out_prefix>_01.jpg ... and returns the paths."""
    n = len(col_titles)
    cell_w = cell_w or (620 if n <= 3 else 540 if n <= 4 else 470)
    f_title, f_sub, f_col, f_row, f_note = font(40, True), font(24), font(24, True), font(26, True), font(21)
    label_w, gap, head_h = 270, 8, 150
    pages = [rows[i:i + rows_per_page] for i in range(0, len(rows), rows_per_page)]
    out = []
    for pi, page in enumerate(pages, 1):
        imgs = []
        for r in page:
            cells = []
            for p in r["cells"]:
                if not p or not os.path.exists(p):
                    cells.append(None)
                    continue
                im = Image.open(p).convert("RGB")
                if crop:
                    w, h = im.size
                    im = im.crop((w // 3, h // 4, 2 * w // 3, 3 * h // 4))
                cells.append(im.resize((cell_w, round(cell_w * im.height / im.width)), Image.LANCZOS))
            imgs.append(cells)
        cell_h = next(c.height for cs in imgs for c in cs if c)
        W = label_w + n * (cell_w + gap)
        H = head_h + len(page) * (cell_h + gap) + 10
        sheet = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(sheet)
        d.text((16, 12), title, font=f_title, fill=FG)
        d.text((16, 62), "%s%s   page %d of %d" % (subtitle, "   (centre crops, enlarged)" if crop else "", pi, len(pages)),
               font=f_sub, fill=MUTED)
        if flip_cols:  # the FLIP colour scale
            bar_w = 260
            bx = W - bar_w - 110
            sheet.paste(_magma_bar(bar_w, 16), (bx, 30))
            d.text((bx, 50), "0 same", font=f_note, fill=MUTED)
            d.text((bx + bar_w - 120, 50), "1 most different", font=f_note, fill=MUTED)
            d.text((bx, 6), "FLIP error", font=f_note, fill=MUTED)
        for i, t in enumerate(col_titles):
            x = label_w + i * (cell_w + gap)
            d.text((x + 4, head_h - 38), t, font=f_col, fill=ACCENT if i in flip_cols else FG)
        y = head_h
        for r, cells in zip(page, imgs):
            d.text((16, y + 10), r["label"], font=f_row, fill=FG)
            for k, note in enumerate(r.get("notes", [])):
                d.text((16, y + 50 + k * 28), note, font=f_note, fill=MUTED)
            for i, c in enumerate(cells):
                x = label_w + i * (cell_w + gap)
                if c:
                    sheet.paste(c, (x, y))
                else:
                    d.rectangle([x, y, x + cell_w, y + cell_h], outline=(60, 60, 60))
                    d.text((x + 12, y + 12), "no picture", font=f_note, fill=MUTED)
            y += cell_h + gap
        path = "%s_%02d.jpg" % (out_prefix, pi)
        sheet.save(path, quality=90)
        out.append(path)
    return out


GAME_LABELS = {"rdr2": "RDR2", "gtav": "GTA V Legacy", "gtave": "GTA V Enhanced, Direct3D 12, ray tracing"}


def _report(folder):
    p = os.path.join(folder, "report.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def _views(folder, suffix):
    """View names that have a <view>_<suffix>.png, in the report's order when it has one."""
    rep = _report(folder)
    names = list(rep.get("view_poses", {}) or rep.get("views", {}))
    present = [f[:-len("_%s.png" % suffix)] for f in os.listdir(folder) if f.endswith("_%s.png" % suffix)]
    if names:  # the report says which pictures are views (not settle-test frames)
        return [v for v in names if v in present]
    return sorted(v for v in present if not v.startswith("settle"))


def _scene(rep):
    bits = [rep.get("place") or rep.get("location") or ""]
    if rep.get("clock"):
        bits.append(rep["clock"])
    if rep.get("weather"):
        bits.append(rep["weather"].lower())
    return " · ".join(b for b in bits if b)


def _clear(folder):
    for f in os.listdir(folder):
        if f.startswith("compare_") and f.endswith(".jpg"):
            os.remove(os.path.join(folder, f))


def build_rt_dlss(folder):
    """Ray tracing x DLSS 5: neither | RT | DLSS 5 | both | FLIP RT | FLIP DLSS 5 over RT | FLIP all."""
    rep = _report(folder)
    rows = []
    for v in _views(folder, "rt_on_dlss"):
        f = {m: os.path.join(folder, "%s_%s.png" % (v, m)) for m in ("rt_off", "rt_on", "rt_off_dlss", "rt_on_dlss")}
        a, ma = flip_map(folder, f["rt_off"], f["rt_on"], v + "__rt_off__rt_on")
        b, mb = flip_map(folder, f["rt_on"], f["rt_on_dlss"], v + "__rt_on__rt_on_dlss")
        c, mc = flip_map(folder, f["rt_off"], f["rt_on_dlss"], v + "__rt_off__rt_on_dlss")
        rows.append({"label": v, "cells": [f["rt_off"], f["rt_on"], f["rt_off_dlss"], f["rt_on_dlss"], a, b, c],
                     "notes": ["FLIP RT %.3f" % ma, "FLIP DLSS 5 %.3f" % mb, "FLIP both %.3f" % mc]})
    cols = ["neither", "ray tracing", "DLSS 5", "ray tracing + DLSS 5", "FLIP: ray tracing",
            "FLIP: DLSS 5 over RT", "FLIP: neither → both"]
    title = "Ray tracing x DLSS 5 · " + _scene(rep)
    setup = {"gtave": "GTA V Enhanced, Direct3D 12, 2560x1440, the game's ray tracing + OptiScaler DLSS 5"}.get(
        rep.get("game"), "RDR2, Direct3D 12, 2560x1440, Reality Redemption 2 + OptiScaler DLSS 5")
    sub = "%s, one frozen instant per row, settle %s frames" % (setup, rep.get("settle", "?"))
    _clear(folder)
    return (render(rows, cols, title, sub, os.path.join(folder, "compare"), flip_cols={4, 5, 6}, cell_w=400) +
            render(rows, cols, title, sub, os.path.join(folder, "compare_crops"), crop=True, flip_cols={4, 5, 6},
                   cell_w=400))


def build_preset_ab(folder, note=""):
    """Reality Redemption 2: mod off | ray tracing off | on | FLIP off->on | FLIP mod off->on."""
    rep = _report(folder)
    if rep.get("kind") == "rt_dlss":
        return build_rt_dlss(folder)
    rows = []
    for v in _views(folder, "rt_on"):
        f = {m: os.path.join(folder, "%s_%s.png" % (v, m)) for m in ("mod_off", "rt_off", "rt_on")}
        rt_map, rt_mean = flip_map(folder, f["rt_off"], f["rt_on"], v + "__rt_off__rt_on")
        mod_map, mod_mean = flip_map(folder, f["mod_off"], f["rt_on"], v + "__mod_off__rt_on")
        rows.append({"label": v, "cells": [f["mod_off"], f["rt_off"], f["rt_on"], rt_map, mod_map],
                     "notes": ["FLIP RT off→on %.3f" % rt_mean, "FLIP mod off→on %.3f" % mod_mean,
                               "pixels RT off→on %.1f" % pixel_diff(f["rt_off"], f["rt_on"])]})
    cols = ["mod off", "RR2, ray tracing off", "RR2, ray tracing on", "FLIP: RT off → on", "FLIP: mod off → RT on"]
    title = "Ray tracing (Reality Redemption 2) · " + _scene(rep)
    sub = "RDR2, Direct3D 12, 2560x1440, one frozen instant per row, settle %s frames%s" % (rep.get("settle", "?"), note)
    _clear(folder)
    return (render(rows, cols, title, sub, os.path.join(folder, "compare"), flip_cols={3, 4}) +
            render(rows, cols, title, sub, os.path.join(folder, "compare_crops"), crop=True, flip_cols={3, 4}))


def build_upscaler_ab(folder, note=""):
    """DLSS 5: off | on | FLIP, plus any live variants (Direct3D 12)."""
    rep = _report(folder)
    variants = list(rep.get("variants", {}))
    rows = []
    for v in _views(folder, "on"):
        off, on = (os.path.join(folder, "%s_%s.png" % (v, m)) for m in ("off", "on"))
        if not os.path.exists(off):
            continue
        fmap, mean = flip_map(folder, off, on, v + "__off__on")
        cells, notes = [off, on, fmap], ["FLIP off→on %.3f" % mean, "pixels off→on %.1f" % pixel_diff(off, on)]
        for label in variants:
            p = os.path.join(folder, "%s_%s.png" % (v, label))
            m2, mean2 = flip_map(folder, off, p, "%s__off__%s" % (v, label))
            cells += [p, m2]
            notes.append("FLIP off→%s %.3f" % (label, mean2))
        rows.append({"label": v, "cells": cells, "notes": notes})
    cols = ["DLSS 5 off", "DLSS 5 on", "FLIP: off → on"]
    flips = {2}
    for i, label in enumerate(variants):
        cols += [label, "FLIP: off → " + label]
        flips.add(4 + 2 * i)
    title = "DLSS 5 (OptiScaler) · " + _scene(rep)
    game = GAME_LABELS.get(rep.get("game"), rep.get("game") or "RDR2, Vulkan")   # older reports: RDR2 on Vulkan
    sub = "%s, one frozen instant per row%s" % (game, note)
    _clear(folder)
    return (render(rows, cols, title, sub, os.path.join(folder, "compare"), flip_cols=flips) +
            render(rows, cols, title, sub, os.path.join(folder, "compare_crops"), crop=True, flip_cols=flips))


def build_sweep(root):
    """One start per setting: a page per view, a row per setting (off | on | FLIP)."""
    rep = _report(root)
    labels = [l for l in rep.get("settings", {}) if os.path.isdir(os.path.join(root, l))]
    order = ["strength_1.0", "strength_1.5", "strength_2.5", "strength_4.0", "style_natural", "style_cinematic"]
    labels.sort(key=lambda l: order.index(l) if l in order else 99)
    titles = {"strength_1.0": "strength 1.0, Default", "strength_1.5": "strength 1.5", "strength_2.5": "strength 2.5",
              "strength_4.0": "strength 4.0", "style_natural": "style Natural", "style_cinematic": "style Cinematic"}
    out = []
    for v in ("portrait", "medium", "npc1", "npc2", "people"):
        rows = []
        for l in labels:
            folder = os.path.join(root, l)
            off, on = (os.path.join(folder, "%s_%s.png" % (v, m)) for m in ("off", "on"))
            if not (os.path.exists(off) and os.path.exists(on)):
                continue
            fmap, mean = flip_map(folder, off, on, v + "__off__on")
            rows.append({"label": titles.get(l, l), "cells": [off, on, fmap],
                         "notes": ["FLIP off→on %.3f" % mean, "pixels off→on %.1f" % pixel_diff(off, on)]})
        if not rows:
            continue
        title = "DLSS 5 settings · view: %s" % v
        sub = "RDR2, Vulkan, Saint Denis 14:00 sunny; each row is its own game start (people and light differ between rows)"
        out += render(rows, ["DLSS 5 off", "DLSS 5 on", "FLIP: off → on"], title, sub,
                      os.path.join(root, "compare_%s" % v), flip_cols={2}, rows_per_page=6)
        out += render(rows, ["DLSS 5 off", "DLSS 5 on", "FLIP: off → on"], title, sub,
                      os.path.join(root, "compare_crops_%s" % v), crop=True, flip_cols={2}, rows_per_page=6)
    return out


def build(folder):
    folder = os.path.abspath(folder)
    parent = os.path.basename(os.path.dirname(folder))
    if parent == "preset_ab":
        return build_preset_ab(folder)
    if parent == "upscaler_ab":
        return build_upscaler_ab(folder)
    if parent == "upscaler_sweep":
        return build_sweep(folder)
    raise SystemExit("not a comparison folder: %s" % folder)


def main():
    targets = sys.argv[1:]
    if not targets:
        base = os.path.join(paths.OUT, "checks")
        targets = [os.path.join(base, kind, d) for kind in ("preset_ab", "upscaler_ab", "upscaler_sweep")
                   if os.path.isdir(os.path.join(base, kind)) for d in sorted(os.listdir(os.path.join(base, kind)))
                   if not d.startswith("_")]  # _invalid, _superseded: runs set aside
    for t in targets:
        try:
            pages = build(t)
            print("%s: %d pages" % (t, len(pages)))
        except Exception as e:  # a half-written or failed run
            print("%s: skipped (%s: %s)" % (t, type(e).__name__, e))


if __name__ == "__main__":
    main()
