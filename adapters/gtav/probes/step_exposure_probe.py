"""What moves GTA V's exposure across time steps? In 30-clip-frame takes, and in
tools/hold_step_check.py at Vinewood (2026-11-23), the whole frame got 1.2-1.4 levels of 255
brighter or darker from one step to the next, though the game does not re-adapt in a held world
(tools/exposure_check.py).

One view (the target) in a held world; between captures of it, one of these, each `--repeat`
times, and the target's mean brightness after each:

    held        nothing (the drift of a held world over the same frames)
    pause       the game paused and unpaused, no frame run (what a step does around its frames)
    step        a time step of 1/30 s looking at the target
    away        the camera on another view (`--other`, brighter or darker) for as many frames as a
                step's, held, then back
    step_away   a step while the camera looks at the other view, then back (what a take does)

    uv run --project . python -m adapters.gtav.probes.step_exposure_probe [--location ID]
        [--target wide] [--other medium] [--repeat 4] [--cases held,pause,step,away,step_away]
        [--before "<lua body run once before the cases>"]
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
from capture import locations, paths as capture_paths  # noqa: E402
import upscaler_ab as u  # noqa: E402

from ..adapter import GTAVEnhancedAdapter  # noqa: E402


def luma(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="gtave-vinewood-blvd-001")
    ap.add_argument("--target", default="wide")
    ap.add_argument("--other", default="medium")
    ap.add_argument("--repeat", type=int, default=4)
    ap.add_argument("--cases", default="held,pause,step,away,step_away")
    ap.add_argument("--before", help="Lua body (function(ctx, native)) run once before the cases")
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "gtave_step_exposure", time.strftime("%Y%m%d_%H%M%S") + ("_" + a.label if a.label else ""))
    os.makedirs(out)
    ad = GTAVEnhancedAdapter()
    ad.ensure_ready(restart=False)
    ad.open()
    report = {"location": a.location, "target": a.target, "other": a.other, "cases": {}}
    n = [0]

    def shot(settle):
        n[0] += 1
        p = os.path.join(out, "%03d.bmp" % n[0])
        ad.capture(p, settle)
        v = luma(p)
        Image.open(p).resize((480, 270)).save(p[:-4] + ".png")
        os.remove(p)
        return round(v, 3)

    try:
        loc = locations.get(capture_paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        st = ad.subject_state()
        vs = u.views(ad, st, u.people(ad, st["position"]))
        ad.hide_subject(True)
        ad.begin_frozen(vs[a.target])
        if a.before:
            with open(os.path.join(ad.exchange, "eval_in.lua"), "w", encoding="utf-8", newline="\n") as f:
                f.write("return function(ctx, native)\n%s\nend\n" % a.before)
            report["before"] = {"code": a.before, "answer": {k: v for k, v in ad.sess.cmd("eval").items() if k[:1] == "r"}}
        settle = int(ad.settings["settle"])
        frames = max(1, int(round((1 / 30) / float(ad.settings["step_frame_s"]))))
        ad.set_camera(vs[a.target])
        base = shot(settle)
        report["start"] = base
        for case in a.cases.split(","):
            vals = []
            for _ in range(a.repeat):
                if case == "pause":
                    ad.sess.cmd("pause", 1)
                    ad.sess.cmd("pause", 0)
                elif case == "step":
                    ad.advance(1 / 30)
                elif case == "away":
                    ad.set_camera(vs[a.other])
                    ad.wait_frames(frames)
                    ad.set_camera(vs[a.target])
                elif case == "step_away":
                    ad.set_camera(vs[a.other])
                    ad.wait_frames(settle)
                    ad.advance(1 / 30)
                    ad.set_camera(vs[a.target])
                vals.append(shot(settle))
            report["cases"][case] = vals
            print("%-10s %s" % (case, " ".join("%.2f" % v for v in vals)), flush=True)
    finally:
        try:
            ad.end_frozen()
            ad.hide_subject(False)
        finally:
            ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
