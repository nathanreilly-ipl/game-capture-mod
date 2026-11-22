"""Does the game's auto-exposure re-adapt between poses while the world is frozen? Game-agnostic.

In Cyberpunk 2077 it does (each sweep pose re-adapts, so brightness jumps unless exposure is
pinned). Here: one view (the target) shot after holding the camera on itself, then after holding
it on the brightest and on the darkest view found nearby (the sky straight up, the ground straight
down, the comparison views of tools/preset_ab.py), each held `--hold` frames, and the target shot
`--settle` frames after the cut (the take setting) and again much later. If exposure adapts, the
target is darker after the bright view and brighter after the dark one.

    uv run --project . python tools/exposure_check.py --game gtave --location gtave-vinewood-walk-001 --clock 14:00 --weather EXTRASUNNY

Writes out/checks/exposure/<stamp>/: frames, report.json.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import adapters_registry, paths  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture.util import stamp, write_json  # noqa: E402
import preset_ab  # noqa: E402
import upscaler_ab as u  # noqa: E402


def luma(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="gtave", choices=adapters_registry.names())
    ap.add_argument("--location", required=True)
    ap.add_argument("--clock")
    ap.add_argument("--weather")
    ap.add_argument("--target", default="medium", help="the view shot each time (a tools/preset_ab.py view name)")
    ap.add_argument("--hold", type=int, default=300, help="frames on the bright or dark view before the cut")
    ap.add_argument("--settle", type=int, default=40, help="frames after the cut, as in a take (default 40)")
    ap.add_argument("--late", type=int, default=600, help="frames after the cut for the late shot")
    a = ap.parse_args()
    out = os.path.join(paths.OUT, "checks", "exposure", stamp() + "_" + a.game)
    os.makedirs(out)
    log = print
    adapter = adapters_registry.get(a.game)()
    adapter.ensure_ready(restart=False)
    adapter.open()
    report = {"game": a.game, "location": a.location, "hold": a.hold, "settle": a.settle, "late": a.late}
    try:
        loc = locs.get(paths.LOCATIONS, a.location)
        adapter.go_to(loc["position"], loc["facing_deg"])
        if a.weather:
            report["weather"] = adapter.set_weather(a.weather)
        if a.clock:
            report["clock"] = adapter.set_clock(a.clock)
        st = adapter.subject_state()
        u.clear_traffic(adapter, st["position"], 30.0, log)
        st = adapter.subject_state()
        adapter.begin_frozen(u.views(adapter, st)["portrait"])
        st = adapter.subject_state()
        boxes = u.people(adapter, st["position"])
        vs = u.views(adapter, st, boxes)
        vs.update(preset_ab.surface_views(adapter, st, boxes))
        vs.update(preset_ab.extra_views(adapter, st))
        p = np.asarray(st["position"], float)
        sky_cam, down_cam = p + u.UP * 2.0, p + u.UP * 0.6 + np.array([1.5, 0.0, 0.0])
        vs["sky"] = u.look_at(sky_cam, sky_cam + np.array([0.05, 0.0, 1.0]), 60.0)
        vs["down"] = u.look_at(down_cam, down_cam + np.array([0.05, 0.0, -1.0]), 20.0)

        def shoot(name, label, settle):
            path = os.path.join(out, "%s.bmp" % label)
            adapter.capture(path, settle)
            png = path[:-4] + ".png"
            Image.open(path).save(png)
            os.remove(path)
            return png

        # how bright each view is (each held, so it is as adapted as it gets)
        levels = {}
        for name in vs:
            adapter.set_camera(vs[name])
            adapter.wait_frames(a.hold)
            levels[name] = round(luma(shoot(name, "view_" + name, 10)), 1)
        report["view_luma"] = levels
        others = {k: v for k, v in levels.items() if k != a.target}
        bright, dark = max(others, key=others.get), min(others, key=others.get)
        report["bright"], report["dark"] = bright, dark
        log("views by mean luma: %s" % ", ".join("%s %.0f" % kv for kv in sorted(levels.items(), key=lambda kv: kv[1])))

        shots = {}
        adapter.set_camera(vs[a.target])
        adapter.wait_frames(a.hold)
        shots["after_itself"] = shoot(a.target, "target_after_itself", a.settle)
        for kind, src in (("bright", bright), ("dark", dark), ("bright_again", bright)):
            adapter.set_camera(vs[src])
            adapter.wait_frames(a.hold)
            adapter.set_camera(vs[a.target])
            shots["after_%s" % kind] = shoot(a.target, "target_after_%s_%d" % (kind, a.settle), a.settle)
            shots["after_%s_late" % kind] = shoot(a.target, "target_after_%s_late" % kind, a.late)
        base = shots["after_itself"]
        report["target"] = a.target
        report["target_luma"] = {k: round(luma(v), 2) for k, v in shots.items()}
        report["target_diff_to_baseline"] = {k: u.diff(base, v) for k, v in shots.items() if k != "after_itself"}
        for k in shots:
            log("  %-22s luma %.2f%s" % (k, report["target_luma"][k], "  diff %s" % report["target_diff_to_baseline"][k]
                                         if k in report["target_diff_to_baseline"] else ""))
    finally:
        adapter.close()
    write_json(os.path.join(out, "report.json"), report)
    log("wrote %s" % out)


if __name__ == "__main__":
    main()
