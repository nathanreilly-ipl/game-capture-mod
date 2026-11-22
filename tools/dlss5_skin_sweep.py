"""DLSS 5's skin controls swept at one frozen instant (OptiScaler's DLSS 5 fork, Direct3D 12).

OptiScaler's live settings file (dlssnr-set.txt) takes only Passes, Style and PreSr, not the model
controls, so they are set through OptiScaler's own menu, live: End opens it, the DLSS 5 page is
scrolled to its end ("Model tuning (intensity, structure, skin)" expanded once by hand), ctrl+click
on the Skin structure slider types a value, a click toggles Auto skin mask, End closes it. Each
change rebuilds the model; OptiScaler logs "DLSS-NR running at ..." on every build, which confirms it.
The run itself is tools/upscaler_ab.py's (views, close views of people, DLSS 5 off/on), with these
as its variants; the settings go back to -1 and the mask on at the end.

    uv run --project . python tools/dlss5_skin_sweep.py --game gtave --location gtave-vinewood-walk-001 --clock 14:00

Skin structure: -1 follows local structure (the model's default); 0 and above set skin on its own.
Auto skin mask: the model finds skin itself rather than treating the frame uniformly.
Menu positions were measured at 2560x1440 with OptiScaler 10.0.0-dev's menu (GTA V Enhanced,
2026-11-21); another window size or menu layout needs them measured again.
Writes out/checks/upscaler_ab/<label>/: the frames, upscaler_ab's sheets, skin_faces.jpg.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import adapters_registry, config, paths  # noqa: E402
import upscaler_ab as u  # noqa: E402

SLIDER = (605, 415)      # Skin structure, in a 1280x720 frame of the window, page scrolled to its end
MASK_BOX = (540, 430)    # Auto skin mask
PANEL = (680, 400)
u32 = ctypes.windll.user32


class OptiMenu:
    """Sets SkinStructure and AutoMask through OptiScaler's menu; confirms each by a model rebuild."""
    DEFAULT = {"SkinStructure": "-1", "AutoMask": "true"}

    def __init__(self, adapter, game_dir, log=print):
        from adapters.common import window
        self.window, self.adapter, self.log = window, adapter, log
        self.h = adapter.hwnd
        self.W, self.H = window.client_size(self.h)
        self.optilog = os.path.join(game_dir, "OptiScaler.log")
        self.state = dict(self.DEFAULT)

    def _scr(self, x, y):
        pt = wt.POINT(int(x * self.W / 1280), int(y * self.H / 720))
        u32.ClientToScreen(self.h, ctypes.byref(pt))
        return pt.x, pt.y

    def _vk(self, vk, up=False, ext=False):
        i = self.window._INPUT(type=1)
        i.ki = self.window._KEYBDINPUT(vk, 0, (0x0002 if up else 0) | (0x0001 if ext else 0), 0, 0)
        u32.SendInput(1, ctypes.byref(i), ctypes.sizeof(self.window._INPUT))

    def _tap(self, vk, ext=False):
        self._vk(vk, ext=ext)
        time.sleep(0.06)
        self._vk(vk, up=True, ext=ext)
        time.sleep(0.08)

    def _move(self, x, y):
        u32.SetCursorPos(*self._scr(x, y))
        time.sleep(0.25)

    def _click(self, x, y, ctrl=False):
        self._move(x, y)
        if ctrl:
            self._vk(0x11)
            time.sleep(0.05)
        u32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.06)
        u32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.05)
        if ctrl:
            self._vk(0x11, up=True)
        time.sleep(0.3)

    def _rebuilt_since(self, since):
        with open(self.optilog, encoding="utf-8", errors="replace") as f:
            return any(m and m.group(1) > since
                       for m in (re.match(r"\[(\d\d:\d\d:\d\d\.\d+)\].*DLSS-NR running at", line) for line in f))

    def apply(self, values):
        want = dict(self.DEFAULT, **{k: str(v).lower() for k, v in values.items() if k in self.DEFAULT})
        if want == self.state:
            return
        since = time.strftime("%H:%M:%S.000000")
        if not self.window.focus(self.h):
            raise RuntimeError("the game window is not in front")
        self._tap(0x23, ext=True)              # End: open the menu
        time.sleep(1.0)
        self._move(*PANEL)
        u32.mouse_event(0x0800, 0, 0, ctypes.c_uint32((-40 * 120) & 0xFFFFFFFF).value, 0)   # the page's end
        time.sleep(0.6)
        if want["SkinStructure"] != self.state["SkinStructure"]:
            self._click(*SLIDER, ctrl=True)    # ImGui: ctrl+click types a value
            self._vk(0x11), self._tap(0x41), self._vk(0x11, up=True)
            for ch in want["SkinStructure"]:
                self._tap({".": 0xBE, "-": 0xBD}.get(ch, ord(ch)))
            self._tap(0x0D)
        if want["AutoMask"] != self.state["AutoMask"]:
            self._click(*MASK_BOX)
        self._move(1250, 700)
        self._tap(0x23, ext=True)              # End: close
        time.sleep(4.0)                         # the model is rebuilt
        ok = self._rebuilt_since(since)
        self.log("  skin structure %s, auto skin mask %s (model rebuilt: %s)" % (want["SkinStructure"], want["AutoMask"], ok))
        if not ok:
            raise RuntimeError("the model was not rebuilt after setting %s" % want)
        self.state = want


def faces_sheet(folder, faces, path):
    """Face close-ups: DLSS 5 off, default, skin 0 / 0.5 / 2, and |skin 0 - default|, |skin 2 - default| x6."""
    cols = [("off", "DLSS 5 off"), ("on", "default (-1)"), ("skin0", "skin 0"), ("skin05", "skin 0.5"),
            ("skin2", "skin 2"), ("d0", "|skin 0 - default| x6"), ("d2", "|skin 2 - default| x6")]
    cw = 360
    font = ImageFont.truetype(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "arialbd.ttf"), 22)
    rows = []
    for v, (x0, y0, x1, y1) in faces.items():
        imgs = {}
        for m in ("off", "on", "skin0", "skin05", "skin2"):
            im = Image.open(os.path.join(folder, "%s_%s.png" % (v, m))).convert("RGB")
            w, h = im.size
            imgs[m] = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
        on = np.asarray(imgs["on"], float)
        for k, m in (("d0", "skin0"), ("d2", "skin2")):
            d = np.clip(np.abs(np.asarray(imgs[m], float) - on).mean(axis=2) * 6, 0, 255).astype(np.uint8)
            imgs[k] = Image.fromarray(d).convert("RGB")
        rows.append([imgs[k].resize((cw, round(cw * imgs[k].height / imgs[k].width)), Image.LANCZOS) for k, _ in cols])
    ch = rows[0][0].height
    sheet = Image.new("RGB", (len(cols) * (cw + 6), 40 + len(rows) * (ch + 6)), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    for i, (_, t) in enumerate(cols):
        d.text((i * (cw + 6) + 6, 8), t, font=font, fill=(255, 196, 92) if t.startswith("|") else (240, 240, 240))
    for r, cells in enumerate(rows):
        for i, c in enumerate(cells):
            sheet.paste(c, (i * (cw + 6), 40 + r * (ch + 6)))
    sheet.save(path, quality=90)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="gtave", choices=adapters_registry.names())
    ap.add_argument("--location")
    ap.add_argument("--clock")
    ap.add_argument("--weather", default=None)
    ap.add_argument("--npcs", type=int, default=4)
    ap.add_argument("--values", default="0,0.5,1,2", help="Skin structure values to try (comma-separated)")
    ap.add_argument("--label", default="skin_sweep")
    ap.add_argument("--faces", default="", help='face crops for skin_faces.jpg as JSON {"view": [x0, y0, x1, y1]} (fractions)')
    a = ap.parse_args()
    game_dir = config.game(a.game).get("game_dir")
    out = os.path.join(paths.OUT, "checks", "upscaler_ab", "%s_%s" % (a.game, a.label))
    adapter = adapters_registry.get(a.game)()
    adapter.ensure_ready(restart=False)
    adapter.open()
    holder = {}

    class MenuSettings:   # upscaler_ab's live-settings hook, through the menu instead of the file
        def __init__(self, _game_dir, log):
            holder.setdefault("m", OptiMenu(adapter, game_dir, log))

        def apply(self, values):
            holder["m"].apply(values)

    u.LiveSettings = MenuSettings
    variants = [("skin" + v.replace(".", "").replace("-", "m"), {"SkinStructure": v}) for v in a.values.split(",")]
    variants.append(("nomask", {"AutoMask": "false"}))
    try:
        rep = u.run(adapter, out, location=a.location, npcs=a.npcs, settle_test=False, clock=a.clock, weather=a.weather,
                    variants=variants, game_dir=game_dir)
    finally:
        adapter.close()
    rep["game"] = a.game
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1)
    if a.faces and all(os.path.exists(os.path.join(out, "%s_skin%s.png" % (v, s))) for v in json.loads(a.faces) for s in ("0", "05", "2")):
        print("wrote", faces_sheet(out, json.loads(a.faces), os.path.join(out, "skin_faces.jpg")))
    print("wrote", out)


if __name__ == "__main__":
    main()
