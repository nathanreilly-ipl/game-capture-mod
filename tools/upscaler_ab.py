"""DLSS 5 (OptiScaler) on and off at the same frozen instant, and whether it is safe for
multi-view captures. Game-agnostic: everything goes through the game's adapter, and DLSS 5 is
switched live with OptiScaler's toggle key (F13, set by capture install --optiscaler), so both
pictures come from one frozen world.

    uv run --project . python tools/upscaler_ab.py [--game rdr2]

The game must be running with OptiScaler installed (capture install <game> --optiscaler).
Four views around the player (portrait, medium, wide, landscape), each captured with DLSS 5 off
and on; then, for one view and both modes:
  - settle: after a cut from another view, the frame at 3..80 frames against one at 160
    (how long the picture takes to stop changing after a camera move)
  - repeat: the same pose captured twice, each after a cut (what the same camera gives twice)
Writes out/checks/upscaler_ab/<stamp>/: the frames, side-by-side images, report.json.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import adapters_registry, config, paths  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture import obstacles as obstacles_geom  # noqa: E402
from capture.util import stamp, write_json  # noqa: E402

TOGGLE_KEY = "F13"
NPC_VFOV = 32.0   # close views of people
VIEW_VFOVS = (35.0, 50.0, 60.0, 60.0, NPC_VFOV, 45.0)   # every view's field of view (views, npc_views)
SETTLES = (3, 6, 12, 24, 40, 80)
REFERENCE_SETTLE = 160


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def look_at(pos, target, vfov):
    up_w = np.array([0.0, 0.0, 1.0])
    fwd = _unit(np.asarray(target, float) - np.asarray(pos, float))
    right = _unit(np.cross(fwd, up_w))
    up = np.cross(right, fwd)
    return {"pos": [float(v) for v in pos], "fwd": list(fwd), "right": list(right), "up": list(up), "vfov_deg": vfov}


UP = np.array([0.0, 0.0, 1.0])
TURNS = (0, 30, -30, 60, -60, 90, -90, 135, -135, 180)


def clear_traffic(adapter, center, radius, log):
    """Deletes vehicles and animals near the player (with their drivers and riders), so a passing
    carriage does not stand in a view; people on foot stay. Nothing a game script owns."""
    if "obstacles" not in adapter.capabilities:
        return
    obs = adapter.obstacles(center, radius)
    ids = [o["id"] for o in obs if o["kind"] in ("vehicle", "animal") and not o.get("owned")]
    r = adapter.remove_obstacles(ids)
    adapter.wait_frames(30)
    log("  cleared %d vehicles and animals within %.0f m (%d kept: owned by a script)" % (
        r["removed"], radius, len(r["skipped"])))


def people(adapter, center, radius=40.0):
    if "obstacles" not in adapter.capabilities:
        return []
    return adapter.obstacles(center, radius)  # people, and any vehicle or animal left


def clear_line(adapter, boxes, cam, target, skip=None):
    """True if nothing (a person, a vehicle, or the static scene) stands between cam and target."""
    cam, target = np.asarray(cam, float), np.asarray(target, float)
    seg = [cam + (target - cam) * t for t in np.linspace(0.0, 0.9, 24)]
    others = [b for b in boxes if b is not skip]
    if others and obstacles_geom.hits(others, seg, 0.05):
        return False
    if "raycast" in adapter.capabilities:
        # both ways: a ray that starts inside a wall does not hit it from within
        hit, _, _ = adapter.raycast([cam, target - (target - cam) * 0.05], [cam + (target - cam) * 0.95, cam])
        if hit.any():
            return False
    return True


def views(adapter, st, boxes=()):
    """Views of the player and the street, each turned around the player until nothing stands
    between the camera and what it looks at."""
    p = np.asarray(st["position"], float)
    fwd0, right0, _ = (np.asarray(v, float) for v in adapter.heading_basis(st["facing_deg"]))
    head, chest = p + UP * 1.55, p + UP * 1.2

    def make(name, f, r):
        if name == "portrait":
            return look_at(p + f * 1.6 + UP * 1.6, head, 35.0), head
        if name == "medium":
            return look_at(p + _unit(f + r) * 3.5 + UP * 1.7, chest, 50.0), chest
        if name == "wide":
            return look_at(p - f * 7.0 + r * 2.0 + UP * 3.0, p + f * 6.0, 60.0), chest
        return look_at(p + f * 0.6 + UP * 1.7, p + f * 30.0 + UP * 1.0, 60.0), p + f * 10.0 + UP * 1.5

    out = {}
    for name in ("portrait", "medium", "wide", "landscape"):
        for turn in TURNS:
            a = np.radians(turn)
            f = fwd0 * np.cos(a) + right0 * np.sin(a)
            pose, target = make(name, f, np.cross(f, UP))
            if clear_line(adapter, boxes, pose["pos"], target):
                break
        out[name] = pose
    return out


class Switch:
    """DLSS 5 on/off with OptiScaler's toggle key. It starts on (OptiScaler.ini Enabled=true);
    the key only flips it, so the state is tracked here, and the pictures show whether it took."""

    def __init__(self, adapter, log):
        self.adapter, self.log = adapter, log
        self.mode = "on"

    def set(self, mode):
        if mode == self.mode:
            return True
        self.adapter.press_key(TOGGLE_KEY)
        time.sleep(4.0)  # OptiScaler's "DLSS Neural Rendering On/Off" notice shows for 2 s
        self.mode = mode
        self.log("  DLSS 5 %s" % mode)
        return True


class LiveSettings:
    """OptiScaler's dlssnr-set.txt (beside OptiScaler: the game's exe folder, or the adapter's
    dlss5.folder where it lives elsewhere, as in Cyberpunk's bin\\x64\\plugins): [DlssNr] settings
    applied live, read about once a second and deleted. Only on Direct3D 12, and not
    TransferStrength."""
    BASE = {"Passes": "1", "Style": "0", "PreSr": "0"}

    def __init__(self, folder, log):
        self.folder = folder
        self.path, self.log = os.path.join(folder, "dlssnr-set.txt"), log

    def ini_values(self, keys, defaults):
        """The [DlssNr] values OptiScaler.ini gives these keys (what a variant is undone to)."""
        from adapters.common.optiscaler_live import OptiScalerLive
        ini = OptiScalerLive(self.folder)
        return {k: ini.ini_value("DlssNr", k, defaults.get(k, "auto")) for k in keys}

    def apply(self, values):
        with open(self.path, "w") as f:
            f.write("".join("%s=%s\n" % kv for kv in dict(self.BASE, **values).items()))
        t = time.time()
        while os.path.exists(self.path) and time.time() - t < 8:
            time.sleep(0.1)
        if os.path.exists(self.path):
            os.remove(self.path)
            raise RuntimeError("OptiScaler did not read %s (it does only on Direct3D 12)" % self.path)
        time.sleep(3.0)  # a changed pass count or style rebuilds the model


def parse_variants(items):
    """["passes2:Passes=2", "strong:Passes=2,Style=1"] -> [("passes2", {"Passes": "2"}), ...]"""
    out = []
    for item in items or ():
        label, _, kvs = item.partition(":")
        out.append((label, dict(kv.split("=", 1) for kv in kvs.split(",") if kv)))
    return out


def columns_sheet(out, names, cols, path, crop=False):
    """Rows: views. Columns: (file suffix, title), e.g. ("off", "DLSS 5 off"); all one instant."""
    cell_w = 420 if crop else 520
    rows = []
    for name in names:
        cells = []
        for suffix, _ in cols:
            p = os.path.join(out, "%s_%s.png" % (name, suffix))
            if not os.path.exists(p):
                cells = None
                break
            im = Image.open(p).convert("RGB")
            if crop:
                w, h = im.size
                im = im.crop((w // 2 - w // 6, h // 2 - h // 4, w // 2 + w // 6, h // 2 + h // 4))
            cells.append(im.resize((cell_w, round(cell_w * im.height / im.width)), Image.LANCZOS))
        if cells:
            rows.append((name, cells))
    if not rows:
        return None
    head, gap = 30, 5
    sheet_im = Image.new("RGB", (len(cols) * (cell_w + gap) - gap, head + sum(r[1][0].height + gap for r in rows)), (18, 18, 18))
    d = ImageDraw.Draw(sheet_im)
    for i, (_, title) in enumerate(cols):
        d.text((i * (cell_w + gap) + 8, 9), title, fill=(255, 255, 255))
    y = head
    for name, cells in rows:
        for i, im in enumerate(cells):
            sheet_im.paste(im, (i * (cell_w + gap), y))
        d.rectangle([3, y + 3, 10 + 7 * len(name), y + 18], fill=(0, 0, 0))
        d.text((6, y + 5), name, fill=(255, 255, 255))
        y += cells[0].height + gap
    sheet_im.save(path, quality=88)
    return path


def load(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def diff(a, b):
    d = np.abs(load(a) - load(b))
    return {"mean": round(float(d.mean()), 3), "p99": round(float(np.percentile(d.max(axis=2), 99)), 1)}


def side_by_side(a, b, out, labels=("DLSS 5 off", "DLSS 5 on"), crop=None):
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if crop:
        ia, ib = ia.crop(crop), ib.crop(crop)
        ia = ia.resize((ia.width * 2, ia.height * 2), Image.LANCZOS)
        ib = ib.resize((ib.width * 2, ib.height * 2), Image.LANCZOS)
    w, h = ia.size
    im = Image.new("RGB", (w * 2 + 8, h), (20, 20, 20))
    im.paste(ia, (0, 0))
    im.paste(ib, (w + 8, 0))
    d = ImageDraw.Draw(im)
    for i, text in enumerate(labels):
        d.rectangle([i * (w + 8) + 8, 8, i * (w + 8) + 8 + 9 * len(text), 30], fill=(0, 0, 0))
        d.text((i * (w + 8) + 13, 12), text, fill=(255, 255, 255))
    im.save(out, quality=92)


def npc_views(adapter, st, count, log, boxes=()):
    """Close views of the nearest people (faces where their facing is known), and one of the
    group, checked for a clear line of sight. Taken in the frozen world, so nobody moves."""
    if count <= 0 or "obstacles" not in adapter.capabilities:
        return {}
    p = np.asarray(st["position"], float)
    people = [o for o in boxes if o["kind"] == "human"]
    people.sort(key=lambda o: np.linalg.norm(np.asarray(o["center"][:2]) - p[:2]))
    log("  %d people within 40 m" % len(people))
    out = {}
    for o in people:
        if len(out) >= count:
            break
        c = np.asarray(o["center"], float)
        head = c + np.array([0.0, 0.0, o["half"][2] * 0.82])
        sides = []
        if o.get("approx") in ("obb", "stock size"):   # a box on the entity's own axes (Cyberpunk: stock size)
            sides.append(np.asarray(o["axes"][1], float))          # in front of them
        d = np.array([p[0] - c[0], p[1] - c[1], 0.0])
        if np.linalg.norm(d) > 0.5:
            sides.append(d / np.linalg.norm(d))                    # from the player's side
        for f in sides:
            for turn in (0, 25, -25, 50, -50):
                a = np.radians(turn)
                g = f * np.cos(a) + np.cross(f, UP) * np.sin(a)
                cam = head + g * 2.3 + np.array([0.0, 0.0, 0.05])
                inside = obstacles_geom.hits([b for b in boxes if b is not o], [cam], 0.15)
                if not inside and clear_line(adapter, boxes, cam, head + g * 0.35, skip=o) and                         clear_line(adapter, boxes, cam, c, skip=o):
                    out["npc%d" % (len(out) + 1)] = look_at(cam, head - np.array([0.0, 0.0, 0.25]), NPC_VFOV)
                    break
            else:
                continue
            break
    if len(people) >= 2:
        group = np.mean([o["center"] for o in people[:5]], axis=0)
        eye = p + np.array([0.0, 0.0, 1.7])
        out["people"] = look_at(eye, group + np.array([0.0, 0.0, 0.6]), 45.0)
    return out


def sheet(out, names, path, crop=False):
    """Rows of DLSS 5 off | on, one per view."""
    cell_w = 800
    rows = []
    for name in names:
        a, b = (os.path.join(out, "%s_%s.png" % (name, m)) for m in ("off", "on"))
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if crop:
            w, h = ia.size
            box = (w // 2 - w // 6, h // 2 - h // 4, w // 2 + w // 6, h // 2 + h // 4)
            ia, ib = ia.crop(box), ib.crop(box)
        ch = round(cell_w * ia.height / ia.width)
        rows.append((name, ia.resize((cell_w, ch), Image.LANCZOS), ib.resize((cell_w, ch), Image.LANCZOS)))
    if not rows:
        return None
    head, gap = 34, 6
    im = Image.new("RGB", (cell_w * 2 + gap, head + sum(r[1].height + gap for r in rows)), (18, 18, 18))
    d = ImageDraw.Draw(im)
    for i, text in enumerate(("DLSS 5 off", "DLSS 5 on")):
        d.text((i * (cell_w + gap) + 10, 10), text, fill=(255, 255, 255))
    y = head
    for name, ia, ib in rows:
        im.paste(ia, (0, y))
        im.paste(ib, (cell_w + gap, y))
        d.rectangle([4, y + 4, 12 + 7 * len(name), y + 20], fill=(0, 0, 0))
        d.text((8, y + 6), name, fill=(255, 255, 255))
        y += ia.height + gap
    im.save(path, quality=90)
    return path


def run(adapter, out, location=None, npcs=3, settle_test=True, clock=None, weather=None, log=print,
        variants=(), game_dir=None, close_ups=False):
    """One comparison in the running game: the views with DLSS 5 on and off at one frozen
    instant, the sheets, and (settle_test) the settle and repeat measurements. Returns the report."""
    os.makedirs(out, exist_ok=True)
    switch = Switch(adapter, log)
    report = {"views": {}, "settle": {}, "repeat": {}}
    try:
        if location:
            loc = locs.get(paths.LOCATIONS, location)
            log("going to %s" % location)
            adapter.go_to(loc["position"], loc["facing_deg"])
            report["location"] = location
        if weather:
            report["weather"] = adapter.set_weather(weather)
        if clock:
            report["clock"] = adapter.set_clock(clock)
        st = adapter.subject_state()
        clear_traffic(adapter, st["position"], 30.0, log)
        st = adapter.subject_state()
        report["place"] = st.get("title")
        if hasattr(adapter, "prepare_take"):
            # an adapter that renders a whole take at one field of view (Cyberpunk) renders at the
            # widest view's and cuts the narrower ones out of it; close-ups alone keep faces native
            fovs = [NPC_VFOV] if close_ups else list(VIEW_VFOVS)
            adapter.prepare_take({"steps": [{"shots": [{"vfov_deg": v} for v in fovs]}]})
        adapter.begin_frozen(views(adapter, st)["portrait"])
        st = adapter.subject_state()  # the player may have moved before the freeze
        boxes = people(adapter, st["position"])  # in the frozen world: nobody moves from here
        vs = views(adapter, st, boxes)
        vs.update(npc_views(adapter, st, npcs, log, boxes))
        cut_views = dict(vs)   # every view stays available to cut away to before a shot
        if close_ups:
            vs = {k: v for k, v in vs.items() if k.startswith("npc")}
            settle_test = False
            if not vs:
                raise RuntimeError("no person with a clear close view near %s" % (st["position"],))
        report["view_poses"] = vs

        def shot(name, view, mode, settle, cut_from=None):
            if mode in ("on", "off"):
                switch.set(mode)
            if cut_from:
                adapter.set_camera(cut_views[cut_from])
                adapter.wait_frames(40)
            adapter.set_camera(vs[view])
            path = os.path.join(out, "%s_%s.bmp" % (name, mode))
            adapter.capture(path, settle)
            png = path[:-4] + ".png"
            Image.open(path).save(png)
            os.remove(path)
            return png

        log("%d views (settle 40), DLSS 5 on, then off:" % len(vs))
        for mode in ("on", "off"):
            for name in vs:
                shot(name, name, mode, 40, cut_from="landscape" if name != "landscape" else "portrait")
        for name in vs:
            a_, b_ = (os.path.join(out, "%s_%s.png" % (name, m)) for m in ("off", "on"))
            report["views"][name] = {"off_vs_on": diff(a_, b_)}
            side_by_side(a_, b_, os.path.join(out, "compare_%s.jpg" % name))
            log("  %-9s off vs on: %s" % (name, report["views"][name]["off_vs_on"]))
        report["sheet"] = sheet(out, list(vs), os.path.join(out, "sheet.jpg"))
        close = [n for n in vs if n == "portrait" or n.startswith("npc")]
        report["sheet_faces"] = sheet(out, close, os.path.join(out, "sheet_faces.jpg"), crop=True)

        if variants:
            live = LiveSettings(adapter.dlss5.folder if getattr(adapter, "dlss5", None) else game_dir, log)
            touched = sorted({k for _, values in variants for k in values})
            # undone to the ini's values; a settings hook without ini_values (dlss5_skin_sweep.py's
            # menu) is undone to its own defaults by an empty apply
            undo = live.ini_values(touched, {"SkinStructure": "-1", "AutoMask": "true"}) if hasattr(live, "ini_values") else {}
            switch.set("on")
            report["variants"] = {}
            for label, values in variants:
                live.apply(values)
                log("  variant %s %s" % (label, values))
                for name in vs:
                    shot(name, name, label, 40, cut_from="landscape" if name != "landscape" else "portrait")
                report["variants"][label] = {"values": values, "vs_off": {
                    n: diff(os.path.join(out, "%s_off.png" % n), os.path.join(out, "%s_%s.png" % (n, label))) for n in vs}}
                log("    vs off: %s" % ", ".join("%s %.2f" % (n, x["mean"]) for n, x in report["variants"][label]["vs_off"].items()))
            live.apply(undo)   # the swept keys back to the ini's values
            cols = [("off", "DLSS 5 off"), ("on", "DLSS 5 on (default)")] + [(l, l) for l, _ in variants]
            report["sheet_variants"] = columns_sheet(out, list(vs), cols, os.path.join(out, "sheet_variants.jpg"))
            report["sheet_variants_faces"] = columns_sheet(out, close, cols, os.path.join(out, "sheet_variants_faces.jpg"),
                                                           crop=True)

        if settle_test:
            log("settle after a cut and repeat (medium view):")
            for mode in ("off", "on"):
                ref = shot("settle_ref", "medium", mode, REFERENCE_SETTLE, cut_from="wide")
                curve = {}
                for k in SETTLES:
                    curve[k] = diff(shot("settle_%03d" % k, "medium", mode, k, cut_from="wide"), ref)["mean"]
                again = shot("settle_040b", "medium", mode, 40, cut_from="landscape")
                first = os.path.join(out, "settle_040_%s.png" % mode)
                report["settle"][mode] = curve
                report["repeat"][mode] = diff(first, again)
                log("  %-3s settle (mean difference to %d frames): %s" % (
                    mode, REFERENCE_SETTLE, ", ".join("%d: %.2f" % (k, v) for k, v in curve.items())))
                log("  %-3s same pose twice: %s" % (mode, report["repeat"][mode]))
    finally:
        try:
            switch.set("on")
        except Exception:
            pass
    write_json(os.path.join(out, "report.json"), report)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="rdr2", choices=adapters_registry.names())
    ap.add_argument("--location", help="a saved location id to go to first (default: where the player is)")
    ap.add_argument("--npcs", type=int, default=3, help="close views of this many nearby people (default 3)")
    ap.add_argument("--clock", help="time of day to set first, HH:MM")
    ap.add_argument("--weather", help="weather to set and hold first (SUNNY, CLOUDS, OVERCAST, ...)")
    ap.add_argument("--no-settle", action="store_true", help="only the comparison views, no settle or repeat test")
    ap.add_argument("--close-ups", action="store_true",
                    help="only the close views of people (--npcs of them), rendered at their own field of view; "
                         "no settle test")
    ap.add_argument("--out", help="output folder (default out/checks/upscaler_ab/<stamp>)")
    ap.add_argument("--variant", action="append", metavar="LABEL:KEY=VALUE[,KEY=VALUE]",
                    help="also capture DLSS 5 with these [DlssNr] settings, switched live (Direct3D 12 only), "
                         "e.g. passes2:Passes=2")
    a = ap.parse_args()
    out = a.out or os.path.join(paths.OUT, "checks", "upscaler_ab", stamp())
    adapter = adapters_registry.get(a.game)()
    adapter.ensure_ready(restart=False)
    adapter.open()
    try:
        report = run(adapter, out, a.location, a.npcs, not a.no_settle, a.clock, a.weather,
                     variants=parse_variants(a.variant), game_dir=config.game(a.game).get("game_dir"),
                     close_ups=a.close_ups)
    finally:
        adapter.close()
    report["game"] = a.game
    write_json(os.path.join(out, "report.json"), report)
    import compare_sheets
    print("sheets with FLIP maps: %d pages" % len(compare_sheets.build_upscaler_ab(out)))
    print("wrote %s" % out)


if __name__ == "__main__":
    main()
