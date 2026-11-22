"""ReShade presets side by side at one frozen instant, switched live by key (ReShade's preset
shortcuts). Game-agnostic. Made for Reality Redemption 2 in RDR2 (capture install rdr2 --api d3d12
--ray-tracing), whose three presets are on F16 (mod off), F15 (ray tracing off), F14 (on). A game
with its own ray tracing that its adapter switches live (GTA V Enhanced) takes --with-dlss5.

    uv run --project . python tools/preset_ab.py --location rdr2-city-street-001 --clock 14:00 --weather SUNNY
    uv run --project . python tools/preset_ab.py --game gtave --with-dlss5 --location gtave-vinewood-walk-001 --clock 14:00
    uv run --project . python tools/preset_ab.py --game gtave --dlss-modes quality,dlaa --with-dlss5 --location gtave-vinewood-walk-001

Views: the player and the street, people nearby (tools/upscaler_ab.py), and views it finds for
materials and reflections: building fronts in up to four directions (found with the scene probes),
the ground (wet ground, puddles), and a high overview (roofs, shadows, occlusion).
With --settle-test, how many frames the last preset needs to settle after a camera cut.
Writes out/checks/preset_ab/<stamp>/: frames, sheets (all views; centre crops), report.json.
"""
import argparse
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import adapters_registry, paths  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture.util import stamp, write_json  # noqa: E402
import upscaler_ab as u  # noqa: E402

MODES = [("mod_off", "F16", "Reality Redemption 2 off"), ("rt_off", "F15", "RR2, ray tracing off"),
         ("rt_on", "F14", "RR2, ray tracing on")]
# --with-dlss5: ray tracing off/on x DLSS 5 off/on (OptiScaler's toggle, F13; it starts on). Ordered so
# DLSS 5 is switched once.
MODES_DLSS = [("rt_on_dlss", "F14", "ray tracing + DLSS 5", True), ("rt_off_dlss", "F15", "DLSS 5 only", True),
              ("rt_off", "F15", "neither", False), ("rt_on", "F14", "ray tracing only", False)]
SETTLES = (10, 20, 40, 60, 90, 120)


def surface_views(adapter, st, boxes, count=4):
    """Building fronts around the player: rays outward at eye height in 16 directions; for walls
    5-30 m away, a camera part of the way there looking at the wall."""
    if "raycast" not in adapter.capabilities:
        return {}
    p = np.asarray(st["position"], float)
    eye = p + u.UP * 1.7
    dirs = [np.array([np.cos(a), np.sin(a), 0.0]) for a in np.radians(np.arange(0, 360, 22.5))]
    hit, pts, nrm = adapter.raycast([eye] * len(dirs), [eye + d * 40.0 for d in dirs])
    found = []
    for d, h, q, n in zip(dirs, hit, pts, nrm):
        dist = np.linalg.norm(q - eye)
        if h and 5.0 < dist < 30.0 and abs(n[2]) < 0.35:   # a wall, not ground or a roof
            found.append((dist, d, q, n))
    out, used = {}, []
    for dist, d, q, n in sorted(found, key=lambda f: f[0]):
        if len(out) >= count or any(np.dot(d, e) > 0.8 for e in used):
            continue
        n_xy = u._unit(np.array([n[0], n[1], 0.0]))
        cam = q + n_xy * min(6.0, dist * 0.6) + u.UP * 0.3     # in front of the wall, facing it
        target = q + u.UP * 1.0
        if u.clear_line(adapter, boxes, cam, target):
            out["facade%d" % (len(out) + 1)] = u.look_at(cam, target, 55.0)
            used.append(d)
    return out


def extra_views(adapter, st):
    p = np.asarray(st["position"], float)
    fwd, right, _ = (np.asarray(v, float) for v in adapter.heading_basis(st["facing_deg"]))
    return {"ground": u.look_at(p - fwd * 1.0 + u.UP * 2.2, p + fwd * 5.0, 60.0),
            "overview": u.look_at(p - fwd * 14.0 + right * 6.0 + u.UP * 12.0, p, 60.0)}


class PresetKeys:
    """Ray tracing by ReShade preset keys (Reality Redemption 2), or, for a game whose own ray
    tracing the adapter switches live (capability "ray_tracing_switch": GTA V Enhanced, through
    its settings menu), through the adapter."""

    def __init__(self, adapter, log, native=True, dlss_modes=False):
        self.adapter, self.log, self.mode = adapter, log, None
        self.native = native and "ray_tracing_switch" in adapter.capabilities
        self.dlss_modes = dlss_modes

    def set(self, mode, key):
        if mode == self.mode:
            return
        if self.dlss_modes:   # key is the game's DLSS mode (--dlss-modes)
            self.adapter.set_dlss_mode(key, log=self.log)
            time.sleep(2.0)
        elif self.native:
            self.adapter.set_ray_tracing(mode.startswith("rt_on"), log=self.log)
            time.sleep(2.0)
        else:
            self.adapter.press_key(key)
            time.sleep(4.0)  # ReShade blends presets over PresetTransitionDuration (1 s here)
            self.log("  preset %s (%s)" % (mode, key))
        self.mode = mode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="rdr2", choices=adapters_registry.names())
    ap.add_argument("--location")
    ap.add_argument("--clock")
    ap.add_argument("--weather")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to let the weather act before freezing")
    ap.add_argument("--npcs", type=int, default=2)
    ap.add_argument("--settle", type=int, default=90, help="frames after each camera cut (default 90)")
    ap.add_argument("--settle-test", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--with-dlss5", action="store_true",
                    help="ray tracing off/on x DLSS 5 off/on (needs OptiScaler, F13 its toggle); with --presets, "
                         "every preset with DLSS 5 on and off")
    ap.add_argument("--presets", metavar="LABEL:KEY,...",
                    help="compare these ReShade presets, switched by their shortcut keys, e.g. "
                         "plain:F14,grade:F15,grade_ss:F16 (GTA V's --preset install), instead of ray tracing")
    ap.add_argument("--dlss-modes", metavar="MODE,...",
                    help="compare the game's DLSS modes instead, switched live through its settings menu (adapter "
                         "capability dlss_mode_switch: GTA V Enhanced), e.g. quality,dlaa; the first is set again at the end")
    ap.add_argument("--restore", metavar="KEY", help="the preset key to press at the end (the capture preset)")
    ap.add_argument("--note", default="", help="a line for the sheets, e.g. the DLSS 5 settings in use")
    ap.add_argument("--clear-people", type=float, default=0.0, metavar="M",
                    help="no crowd, and people and vehicles within M metres removed once frozen (the player stays): "
                         "for comparing separate game starts, e.g. a world mod off and on")
    a = ap.parse_args()
    out = os.path.join(paths.OUT, "checks", "preset_ab", stamp() + ("_" + a.label if a.label else ""))
    os.makedirs(out)
    log = print
    adapter = adapters_registry.get(a.game)()
    if "ray_tracing_switch" in adapter.capabilities and not a.with_dlss5 and not a.presets:
        ap.error("%s has no ray tracing mod to turn off; use --with-dlss5 (ray tracing off/on x DLSS 5 off/on)" % a.game)
    if a.dlss_modes and (a.presets or "dlss_mode_switch" not in adapter.capabilities):
        ap.error("--dlss-modes: not with --presets, and only for a game whose adapter switches the DLSS mode")
    adapter.ensure_ready(restart=False)
    adapter.open()
    keys = PresetKeys(adapter, log, native=not a.presets, dlss_modes=bool(a.dlss_modes))
    pairs = [p.split(":") for p in a.presets.split(",")] if a.presets else []
    if a.dlss_modes:   # compared as presets would be, the mode as the key
        pairs = [(m, m) for m in a.dlss_modes.split(",")]
    if pairs:   # all presets with DLSS 5 on, then all with it off: one DLSS switch
        states = [True, False] if a.with_dlss5 else [None]
        modes = [(lab + ("_dlss" if d else ""), key, lab + (" + DLSS 5" if d else ""), d) for d in states for lab, key in pairs]
    elif a.with_dlss5:
        modes = [(m, k, t, d) for m, k, t, d in MODES_DLSS]
    else:
        modes = [(m, k, t, None) for m, k, t in MODES]
    dlss = {"on": True}

    def set_mode(mode, key, want_dlss):
        if want_dlss is not None and want_dlss != dlss["on"]:
            adapter.press_key("F13")
            time.sleep(4.0)
            dlss["on"] = want_dlss
            log("  DLSS 5 %s" % ("on" if want_dlss else "off"))
        if key:
            keys.set(mode, key)

    report = {"game": a.game, "location": a.location, "clock": a.clock, "weather": a.weather, "settle": a.settle,
              "modes": [list(m) for m in modes], "views": {}, "note": a.note,
              "kind": "presets" if pairs else ("rt_dlss" if a.with_dlss5 else "rt"),
              "switch": "dlss_mode" if a.dlss_modes else ("preset_keys" if pairs else "ray_tracing"),
              "presets": [lab for lab, _ in pairs], "dlss_states": [m[3] for m in modes][::max(1, len(pairs))] if pairs else None}
    if a.clear_people:
        adapter.settings["crowd"] = 0   # no walkers of our own
    try:
        if a.location:
            loc = locs.get(paths.LOCATIONS, a.location)
            log("going to %s" % a.location)
            adapter.go_to(loc["position"], loc["facing_deg"])
        if a.weather:
            report["weather"] = adapter.set_weather(a.weather)
        if a.clock:
            report["clock"] = adapter.set_clock(a.clock)
        if a.wait:
            log("  letting the weather act for %.0f s" % a.wait)
            time.sleep(a.wait)
        st = adapter.subject_state()
        u.clear_traffic(adapter, st["position"], 30.0, log)
        st = adapter.subject_state()
        report["place"] = st.get("title")
        set_mode(*modes[0][:2], modes[0][3])
        adapter.begin_frozen(u.views(adapter, st)["portrait"])
        st = adapter.subject_state()
        if a.clear_people and "obstacles" in adapter.capabilities:
            obs = adapter.obstacles(st["position"], a.clear_people)
            r = adapter.remove_obstacles([o["id"] for o in obs])
            report["cleared"] = {"found": len(obs), "removed": r["removed"], "skipped": len(r["skipped"])}
            log("  cleared %d of %d people, animals and vehicles within %.0f m" % (r["removed"], len(obs), a.clear_people))
            adapter.wait_frames(30)
        boxes = u.people(adapter, st["position"])
        vs = u.views(adapter, st, boxes)
        vs.update(surface_views(adapter, st, boxes))
        vs.update(extra_views(adapter, st))
        vs.update(u.npc_views(adapter, st, a.npcs, log, boxes))
        report["view_poses"] = vs
        log("%d views: %s" % (len(vs), ", ".join(vs)))

        def shot(name, suffix, settle, cut_from):
            adapter.set_camera(vs[cut_from])
            adapter.wait_frames(30)
            adapter.set_camera(vs[name])
            path = os.path.join(out, "%s_%s.bmp" % (name, suffix))
            adapter.capture(path, settle)
            png = path[:-4] + ".png"
            Image.open(path).save(png)
            os.remove(path)
            return png

        for mode, key, _, want_dlss in modes:
            set_mode(mode, key, want_dlss)
            for name in vs:
                shot(name, mode, a.settle, "landscape" if name != "landscape" else "portrait")
        for name in vs:
            f = {m[0]: os.path.join(out, "%s_%s.png" % (name, m[0])) for m in modes}
            if pairs:
                r, labs = {}, [lab for lab, _ in pairs]
                for d in report["dlss_states"]:
                    suf = "_dlss" if d else ""
                    for lab in labs[1:]:
                        r["%s_vs_%s%s" % (labs[0], lab, suf)] = u.diff(f[labs[0] + suf], f[lab + suf])
                report["views"][name] = r
            else:
                report["views"][name] = {"rt_off_vs_on": u.diff(f["rt_off"], f["rt_on"])}
                if a.with_dlss5:
                    report["views"][name]["neither_vs_both"] = u.diff(f["rt_off"], f["rt_on_dlss"])
                else:
                    report["views"][name]["mod_off_vs_rt_on"] = u.diff(f["mod_off"], f["rt_on"])
            log("  %-10s %s" % (name, report["views"][name]))

        if a.settle_test:
            mode, key, _, want_dlss = modes[-1]
            set_mode(mode, key, want_dlss)
            ref = shot("medium", "settle_ref", 240, "wide")
            curve = {k: u.diff(shot("medium", "settle_%03d" % k, k, "wide"), ref)["mean"] for k in SETTLES}
            report["settle_curve"] = curve
            log("  settle (%s, mean difference to 240 frames): %s" % (
                mode, ", ".join("%d: %.2f" % kv for kv in curve.items())))
    finally:
        try:
            if pairs:
                if not dlss["on"]:
                    set_mode(None, None, True)
                if a.dlss_modes:
                    keys.set(pairs[0][0], pairs[0][1])
                if a.restore:
                    adapter.press_key(a.restore)
                    time.sleep(2.0)
                    log("  preset key %s pressed (the capture preset)" % a.restore)
            else:
                set_mode("rt_on", "F14", True if a.with_dlss5 else None)
        except Exception:
            pass
        adapter.close()
    write_json(os.path.join(out, "report.json"), report)
    import compare_sheets
    log("sheets with FLIP maps: %d pages" % len(compare_sheets.build_preset_ab(out)))
    log("wrote %s" % out)


if __name__ == "__main__":
    main()
