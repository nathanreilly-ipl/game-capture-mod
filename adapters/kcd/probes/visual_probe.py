"""The game's own graphics settings compared at one held instant: what does each set change?

    uv run --project . python -m adapters.kcd.probes.visual_probe [--location kcd-loc-001] [--sets high,ultra]

The world is held at a location, and its four preview headings (and a close one of people, if
--people) are captured under each named set of console variables (SETS), applied in the held
world and given 120 frames to take effect. Writes out/probes/kcd/visual/<set>_<view>.jpg, a sheet
per view (sets side by side) and report.json with the mean change of each set against the first
and the frame rate under each.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import look, paths
from ..session import Session

SPEC = ["sys_spec_GameEffects", "sys_spec_ObjectDetail", "sys_spec_Particles", "sys_spec_Physics", "sys_spec_PostProcessing",
        "sys_spec_Shading", "sys_spec_Shadows", "sys_spec_Texture", "sys_spec_Vegetation", "sys_spec_VolumetricEffects",
        "sys_spec_Water", "sys_spec_light"]
SETS = {
    "high": dict({k: 3 for k in SPEC}, r_AntialiasingMode=2, e_LodRatio=25, e_ViewDistRatio=100, e_MergedMeshesViewDistRatio=70),
    "ultra": dict({k: 4 for k in SPEC}, r_AntialiasingMode=3, e_LodRatio=100, e_ViewDistRatio=100, e_MergedMeshesViewDistRatio=100,
                  e_ViewDistRatioVegetation=100),
    # level 7: Engine\Config\ultraspec.cfg (sys_spec_Full 7), the spec groups' top level; "ultra" (4) is
    # veryhighspec.cfg's. The view distance its ObjectDetail group sets (e_ViewDistRatio 125) is kept.
    "ultra7": dict({k: 7 for k in SPEC}, r_AntialiasingMode=3, e_LodRatio=100, e_ViewDistRatio=125, e_MergedMeshesViewDistRatio=100,
                   e_ViewDistRatioVegetation=100),
}
# the capture look (look.VISUAL) with 1x1, 2x2 and 3x3 supersampling
SETS.update({"top%d" % n: dict(look.VISUAL, r_Supersampling=n) for n in (1, 2, 3)})


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="kcd-loc-001")
    ap.add_argument("--sets", default="high,ultra")
    ap.add_argument("--run-s", type=float, default=0.0,
                    help="seconds the world runs after each set is applied, before it is held again (the eye "
                         "adapts meanwhile; a switch of supersampling resets it)")
    a = ap.parse_args()
    from PIL import Image
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    x, y, z = loc["position"][0], loc["position"][1], loc["position"][2] + 1.6
    h0 = float(loc.get("facing_deg", 0.0))
    views = {"front": h0, "right": h0 - 90, "back": h0 + 180, "left": h0 + 90}
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "kcd", "visual")
    os.makedirs(out, exist_ok=True)
    s.cmd("unfreeze")
    s.cmd("teleport", x, y, z - 1.5, h0)
    time.sleep(8)
    report = {"location": a.location, "sets": {}}
    imgs = {}
    try:
        s.cmd("hud", 0)
        s.cmd("ghost", 1)
        s.cmd("freeze")
        for name in a.sets.split(","):
            for k, v in SETS[name].items():
                s.cmd("cvar", k, v)
            if a.run_s:      # the eye adapts on game time only: let the world run (eye fast) after a switch
                s.cmd("cvar", "r_HDREyeAdaptationSpeed", 30)
                s.cmd("unfreeze")
                time.sleep(a.run_s)
                s.cmd("freeze")
                s.cmd("cvar", "r_HDREyeAdaptationSpeed", 3)
            frames.wait(ex, 120)
            got = {k: s.cmd("cvar", k).data[0] for k in SETS[name]}
            wrong = {k: v for k, v in got.items() if _num(v) != _num(SETS[name][k])}
            fps = frames.frame_rate(ex, 1.0)
            report["sets"][name] = {"fps": round(fps, 1), "read_back": got, "not_taken": wrong}
            for view, heading in views.items():
                s.cmd("pose", x, y, z, 0.0, 0.0, heading, 60.0)
                time.sleep(s.console_clear_in())
                r = frames.shoot(ex, "visual/%s_%s" % (name, view), after=60)
                with Image.open(r["path"]) as im:
                    imgs[(name, view)] = np.asarray(im.convert("RGB"), dtype=np.float32)
                    im.convert("RGB").save(os.path.join(out, "%s_%s.jpg" % (name, view)), quality=92)
                os.remove(r["path"])
            print("%s: %.1f frames/s, not taken: %s" % (name, fps, wrong or "none"))
        names = a.sets.split(",")
        for name in names[1:]:
            report["sets"][name]["mean_change_vs_%s" % names[0]] = {
                v: round(float(np.abs(imgs[(name, v)] - imgs[(names[0], v)]).mean()), 2) for v in views}
            print(name, "against", names[0], report["sets"][name]["mean_change_vs_%s" % names[0]])
        for view in views:
            row = [Image.fromarray(imgs[(n, view)].astype(np.uint8)).resize((1280, 720)) for n in names]
            sheet = Image.new("RGB", (1280 * len(row), 720))
            for i, im in enumerate(row):
                sheet.paste(im, (1280 * i, 0))
            sheet.save(os.path.join(out, "sheet_%s.jpg" % view), quality=90)
    finally:
        s.cmd("release")
        s.cmd("unfreeze")
        s.cmd("ghost", 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("frames in", out)


if __name__ == "__main__":
    main()
