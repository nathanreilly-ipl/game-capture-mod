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
    ap.add_argument("--conditions", default=",".join(CONDITIONS),
                    help="comma-separated; sky<metres>[_ghost] parks at that height, e.g. sky30_ghost")
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
        for run, cond in enumerate(conditions):
            label = "%d_%s" % (run, cond)  # a condition may repeat; keep each run's files and numbers
            ghost = cond.endswith("ghost")
            ad.sess.cmd("ghost", 1 if ghost else 0)
            if cond.startswith("sky"):
                digits = cond[3:].split("_")[0]
                height = float(digits) if digits else args.height
                ad.sess.cmd("park", "%.3f %.3f %.3f" % (x, y, z + height))
                ad.sess.cmd("focus", "%.3f %.3f %.3f" % (x, y, z))
            else:
                ad.sess.cmd("focus", "clear")
                ad.go_to(loc["position"], loc["facing_deg"])
                ad.sess.cmd("ghost", 1 if ghost else 0)  # after the teleport, so collision follows the condition
            # invisible only; the conditions decide the natives (adapter.hide_subject would add them)
            ad.sess.cmd("player_visible", 0)
            ad.subject_hidden = True
            samples = []
            steps = max(1, int(args.run_s / 5))
            for _ in range(steps):
                ad.sess.cmd("wait", 300, timeout=60)
                pop = ad.sess.cmd("population", "%.3f %.3f %.3f" % (x, y, z))
                samples.append({"peds": [int(v) for v in pop["peds"].split()],
                                "vehicles": [int(v) for v in pop["vehicles"].split()]})
            law = ad.sess.cmd("law")
            ad.begin_frozen(shots[0])
            files = []
            for s in shots:
                dst = os.path.join(out, "%s_%s.bmp" % (label, s["name"]))
                ad.set_camera(s)
                ad.capture(dst, 60)
                files.append(dst)
            ad.end_frozen()
            mean = lambda kind, k: round(sum(s[kind][k] for s in samples) / len(samples), 1)  # noqa: E731
            report[label] = {"player": ad.sess.cmd("state")["player"], "wanted_score": law.get("wanted_score"),
                            "law_incident": law.get("law_incident"), "bounty": law.get("bounty"),
                            "population_samples": samples,
                            "peds_mean_15_30_60": [mean("peds", k) for k in (1, 2, 3)],
                            "vehicles_mean_15_30_60": [mean("vehicles", k) for k in (1, 2, 3)],
                            "peds_loaded_mean": mean("peds", 0), "files": files}
            print("%-13s player z %-9s incident %-5s  people within 15/30/60 m %s  vehicles %s  loaded %s" % (
                label, report[label]["player"].split()[2][:8], law.get("law_incident"),
                report[label]["peds_mean_15_30_60"], report[label]["vehicles_mean_15_30_60"],
                report[label]["peds_loaded_mean"]), flush=True)
            rows.append((label, files))
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
