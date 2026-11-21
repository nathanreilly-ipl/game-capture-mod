"""DLSS 5 (OptiScaler) settings side by side: one game start per setting, the same location,
clock and weather each time, DLSS 5 off and on captured at one frozen instant per start
(tools/upscaler_ab.py). Game-agnostic: the game is restarted through its adapter and its
OptiScaler.ini is edited in the game folder recorded by `capture install`.

    uv run --project . python tools/upscaler_sweep.py [--game rdr2] [--location ID]

The settings OptiScaler only reads at start (TransferStrength, Style) cannot be switched live on
Vulkan, hence one start each. People differ between starts (the world is loaded fresh), so the
across-settings sheets compare like with like only for the player and the buildings; each start's
own off/on sheet is the exact comparison. OptiScaler.ini is put back as it was at the end.
Writes out/checks/upscaler_sweep/<stamp>/: one folder per setting, the across-settings sheets,
report.json.

Each setting's captures run in a process of their own (tools/upscaler_ab.py): the process that
restarted RDR2 could not bring its window to the front afterwards, a new one can (2026-11-20).
"""
import argparse
import os
import subprocess
import sys
import time

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import adapters_registry, config, paths  # noqa: E402
from capture.install import installer  # noqa: E402
from capture.install.plan import Ini  # noqa: E402
from capture.util import stamp, write_json  # noqa: E402
from capture.util import read_json  # noqa: E402

AB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upscaler_ab.py")

SETTINGS = [  # label, title, [DlssNr] keys
    ("strength_1.0", "strength 1.0", {"TransferStrength": "1.0", "Style": "0"}),
    ("strength_1.5", "strength 1.5", {"TransferStrength": "1.5", "Style": "0"}),
    ("strength_2.5", "strength 2.5", {"TransferStrength": "2.5", "Style": "0"}),
    ("strength_4.0", "strength 4.0", {"TransferStrength": "4.0", "Style": "0"}),
    ("style_natural", "style Natural", {"TransferStrength": "1.0", "Style": "1"}),
    ("style_cinematic", "style Cinematic", {"TransferStrength": "1.0", "Style": "2"}),
]
SHEETS = {
    "strength": ["strength_1.0", "strength_1.5", "strength_2.5", "strength_4.0"],
    "style": ["strength_1.0", "style_natural", "style_cinematic"],
}


def close_game(exe, log):
    subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True)
    for _ in range(60):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe, "/NH"], capture_output=True, text=True).stdout
        if exe.lower() not in out.lower():
            break
        time.sleep(1)
    time.sleep(3)
    log("closed %s" % exe)


def across(root, labels, titles, views, path, crop=False, first_off=True):
    """Rows: views. Columns: DLSS 5 off (from the first setting's start), then each setting on."""
    cols = ([(labels[0], "off", "DLSS 5 off")] if first_off else []) + [(l, "on", titles[l]) for l in labels]
    cell_w = 560 if not crop else 400
    rows = []
    for v in views:
        cells = []
        for label, mode, _ in cols:
            p = os.path.join(root, label, "%s_%s.png" % (v, mode))
            if not os.path.exists(p):
                cells = None
                break
            im = Image.open(p).convert("RGB")
            if crop:
                w, h = im.size
                im = im.crop((w // 2 - w // 6, h // 2 - h // 4, w // 2 + w // 6, h // 2 + h // 4))
            cells.append(im.resize((cell_w, round(cell_w * im.height / im.width)), Image.LANCZOS))
        if cells:
            rows.append((v, cells))
    if not rows:
        return None
    head, gap = 30, 5
    W = len(cols) * (cell_w + gap) - gap
    sheet = Image.new("RGB", (W, head + sum(r[1][0].height + gap for r in rows)), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for i, (_, _, title) in enumerate(cols):
        d.text((i * (cell_w + gap) + 8, 9), title, fill=(255, 255, 255))
    y = head
    for v, cells in rows:
        for i, im in enumerate(cells):
            sheet.paste(im, (i * (cell_w + gap), y))
        d.rectangle([3, y + 3, 10 + 7 * len(v), y + 18], fill=(0, 0, 0))
        d.text((6, y + 5), v, fill=(255, 255, 255))
        y += cells[0].height + gap
    sheet.save(path, quality=88)
    return path


def pairs(root, labels, titles, views, path):
    """Rows: settings. For each view, DLSS 5 off | on from that setting's own start (one frozen
    instant), centre crops. Starts differ in people and light, so compare within a row first."""
    cell_w = 300
    rows = []
    for label in labels:
        cells = []
        for v in views:
            for mode in ("off", "on"):
                p = os.path.join(root, label, "%s_%s.png" % (v, mode))
                if not os.path.exists(p):
                    cells.append(None)
                    continue
                im = Image.open(p).convert("RGB")
                w, h = im.size
                im = im.crop((w // 2 - w // 6, h // 2 - h // 4, w // 2 + w // 6, h // 2 + h // 4))
                cells.append(im.resize((cell_w, round(cell_w * im.height / im.width)), Image.LANCZOS))
        if any(cells):
            rows.append((label, cells))
    if not rows:
        return None
    ch = next(c for _, cells in rows for c in cells if c).height
    head, gap, side = 30, 5, 120
    W = side + len(views) * 2 * (cell_w + gap)
    sheet = Image.new("RGB", (W, head + len(rows) * (ch + gap)), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for i, v in enumerate(views):
        for j, mode in enumerate(("off", "on")):
            d.text((side + (2 * i + j) * (cell_w + gap) + 6, 9), "%s, DLSS 5 %s" % (v, mode), fill=(255, 255, 255))
    y = head
    for label, cells in rows:
        d.text((6, y + ch // 2 - 6), titles[label], fill=(255, 255, 255))
        for k, c in enumerate(cells):
            if c:
                sheet.paste(c, (side + k * (cell_w + gap), y))
        y += ch + gap
    sheet.save(path, quality=88)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="rdr2", choices=adapters_registry.names())
    ap.add_argument("--location", default="rdr2-city-street-001")
    ap.add_argument("--clock", default="14:00")
    ap.add_argument("--weather", default="SUNNY")
    ap.add_argument("--npcs", type=int, default=3)
    ap.add_argument("--only", action="append", help="setting labels to run (default all)")
    ap.add_argument("--root", help="an earlier sweep's folder to add to (its settings run again are replaced)")
    a = ap.parse_args()
    log = print
    game_dir = config.game(a.game).get("game_dir")
    ini_path = os.path.join(game_dir, "OptiScaler.ini")
    if not os.path.exists(ini_path):
        raise SystemExit("OptiScaler is not installed (capture install %s --optiscaler)" % a.game)
    exe = installer(a.game).EXE
    root = a.root or os.path.join(paths.OUT, "checks", "upscaler_sweep", stamp())
    os.makedirs(root, exist_ok=True)
    keys = sorted({k for _, _, s in SETTINGS for k in s})
    original = {k: Ini(ini_path).get("DlssNr", k) for k in keys}
    old = os.path.join(root, "report.json")
    report = read_json(old) if os.path.exists(old) else {
        "game": a.game, "location": a.location, "clock": a.clock, "weather": a.weather, "settings": {}}
    titles = {label: title for label, title, _ in SETTINGS}
    try:
        for label, title, values in SETTINGS:
            if a.only and label not in a.only:
                continue
            log("== %s %s" % (title, values))
            close_game(exe, log)
            ini = Ini(ini_path)
            for k, v in values.items():
                ini.set("DlssNr", k, v)
            ini.save()
            adapters_registry.get(a.game)().ensure_ready(restart=True)
            out = os.path.join(root, label)
            cmd = [sys.executable, AB, "--game", a.game, "--location", a.location, "--npcs", str(a.npcs),
                   "--clock", a.clock, "--weather", a.weather, "--no-settle", "--out", out]
            for attempt in range(3):
                if subprocess.run(cmd).returncode == 0:
                    break
                log("  capture failed (attempt %d), trying again in 20 s" % (attempt + 1))
                time.sleep(20)
            else:
                raise RuntimeError("captures for %s failed three times" % label)
            r = read_json(os.path.join(out, "report.json"))
            report["settings"][label] = {"values": values, "off_vs_on": {v: x["off_vs_on"] for v, x in r["views"].items()}}
            write_json(os.path.join(root, "report.json"), report)
    finally:
        log("== putting OptiScaler.ini back")
        close_game(exe, log)
        ini = Ini(ini_path)
        for k, v in original.items():
            ini.set("DlssNr", k, v)
        ini.save()
        adapter = adapters_registry.get(a.game)()
        adapter.ensure_ready(restart=True)
    views = ["portrait", "medium", "wide", "landscape", "npc1", "npc2", "npc3", "people"]
    for name, labels in SHEETS.items():
        labels = [l for l in labels if os.path.isdir(os.path.join(root, l))]
        if labels:
            across(root, labels, titles, views, os.path.join(root, "sheet_%s.jpg" % name))
            pairs(root, labels, titles, ["portrait", "npc1", "npc2"], os.path.join(root, "sheet_%s_pairs.jpg" % name))
    write_json(os.path.join(root, "report.json"), report)
    import compare_sheets
    log("sheets with FLIP maps: %d pages" % len(compare_sheets.build_sweep(root)))
    log("wrote %s" % root)


if __name__ == "__main__":
    main()
