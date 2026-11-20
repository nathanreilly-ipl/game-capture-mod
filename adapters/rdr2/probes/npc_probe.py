"""Do NPCs still react to the hidden player? Compares ways of taking the player out of the scene.

    uv run --project . python adapters/rdr2/probes/npc_probe.py --location rdr2-city-street-001 [--height 200]

Conditions, in order, each followed by --run-s seconds of the world running, then a frozen
capture of 8 near-ring views around the location:
    hidden       player invisible at the location (what takes do now)
    ghost        + natives: everyone ignores the player, law off, silent, no collision
    sky          player parked --height m above (no natives), streaming focus on the location
    sky_ghost    parked above + the natives
Writes the frames and sheet.jpg (a row per condition) to out/probes/npc/<location>/, and the law
state per condition to report.json. Ends with the player back on the ground at the location.
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from adapters.rdr2.adapter import RDR2Adapter  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture import paths  # noqa: E402
from capture.placement import Placement  # noqa: E402
from capture.shots import build, select_cameras  # noqa: E402

RIG = os.path.join(os.environ.get("USERPROFILE", ""), "repos", "gamecapture-camera-rigs-huixin", "web", "data", "demo",
                   "rig_yiming_stdm.json")
CAMERAS = ["H_near_temporal_%02d" % k for k in range(0, 32, 4)]
CONDITIONS = ("hidden", "ghost", "sky", "sky_ghost")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", required=True)
    ap.add_argument("--height", type=float, default=200.0)
    ap.add_argument("--run-s", type=float, default=30.0)
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    args = ap.parse_args()
    conditions = [c for c in args.conditions.split(",") if c]
    out = os.path.join(paths.OUT, "probes", "npc", args.location, "_".join(conditions))
    os.makedirs(out, exist_ok=True)
    loc = locs.get(paths.LOCATIONS, args.location)
    with open(RIG, encoding="utf-8") as f:
        rig = json.load(f)

    ad = RDR2Adapter()
    ad.ensure_ready(restart=False)
    ad.open()
    report, rows = {}, []
    try:
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.set_clock("12:00")
        origin = ad.ground_point(loc["position"])
        x, y, z = origin
        shots = select_cameras(build(rig, Placement(origin, ad.rig_rotation(loc["facing_deg"]))), CAMERAS)
        shots = shots["steps"][0]["shots"]
        for cond in conditions:
            ad.sess.cmd("ghost", 1 if cond.endswith("ghost") else 0)
            if cond.startswith("sky"):
                ad.sess.cmd("park", "%.3f %.3f %.3f" % (x, y, z + args.height))
                ad.sess.cmd("focus", "%.3f %.3f %.3f" % (x, y, z))
            else:
                ad.sess.cmd("focus", "clear")
                ad.go_to(loc["position"], loc["facing_deg"])
                if cond == "ghost":
                    ad.sess.cmd("ghost", 1)  # teleport restores collision; apply again
            ad.hide_subject(True)
            ad.sess.cmd("wait", int(args.run_s * 60), timeout=args.run_s * 4 + 60)
            law = ad.sess.cmd("law")
            ad.begin_frozen(shots[0])
            files = []
            for s in shots:
                dst = os.path.join(out, "%s_%s.bmp" % (cond, s["name"]))
                ad.set_camera(s)
                ad.capture(dst, 60)
                files.append(dst)
            ad.end_frozen()
            report[cond] = {"player": ad.sess.cmd("state")["player"], "wanted_score": law.get("wanted_score"),
                            "law_incident": law.get("law_incident"), "bounty": law.get("bounty"), "files": files}
            print("%-10s player %s  wanted %s  incident %s" % (cond, report[cond]["player"], law.get("wanted_score"),
                                                               law.get("law_incident")), flush=True)
            rows.append((cond, files))
        ad.sess.cmd("ghost", 0)
        ad.sess.cmd("focus", "clear")
        ad.go_to(loc["position"], loc["facing_deg"])
    finally:
        ad.close()

    w, h = 400, 225
    sheet = Image.new("RGB", (len(CAMERAS) * w // 2, len(rows) * (h + 22) * 2), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for r, (cond, files) in enumerate(rows):
        for c, f in enumerate(files):
            im = Image.open(f).convert("RGB").resize((w, h), Image.LANCZOS)
            px, py = (c % 4) * w, (r * 2 + c // 4) * (h + 22)
            sheet.paste(im, (px, py + 22))
            d.text((px + 5, py + 5), "%s  view %02d" % (cond, (c * 4)), fill=(235, 235, 235))
    sheet.save(os.path.join(out, "sheet.jpg"), quality=88)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("sheet:", os.path.join(out, "sheet.jpg"))


if __name__ == "__main__":
    main()
