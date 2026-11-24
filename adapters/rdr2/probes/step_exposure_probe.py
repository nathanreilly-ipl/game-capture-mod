"""Does RDR2's exposure hold across time steps? In 30-clip-frame takes (CoreWeave, 2026-11-23) the
frames got steadily darker or brighter over the first ten clip frames (lakeshore 124 to 112, Saint
Denis 65.9 to 68.9). Found with it and tools/hold_step_check.py (2026-11-24): the photo-mode lock
holds across steps; the drifts came from the game's clock of day running 30 times real time, which
moved the sky's light a second per step (adapter setting clock_ms_per_minute; docs/VISUAL_CHECKS.md
A5). Results swing with the weather between runs: set --clock and compare runs made one after the
other.

One view (the take's first camera if --shots is given, else tools/upscaler_ab.py's `--view`) in
a world held as a take holds it (begin_frozen: exposure locked); between captures of it, one of
these, `--repeat` times each, and the view's mean brightness after each (plus the photo-mode
exposure value the game reports):

    held        nothing but the frames a step takes (the held world's own drift)
    step        a time step of 1/30 s (adapter.advance, as a take does)
    relock      a step, then the photo-mode exposure unlocked and locked again
    reset       a step with RESET_ADAPTATION before it (the eye snapped to its target)
    away        the camera on the other view (--other: the take's camera of that name at clip frame 1)
                for a take's settle, held, then back
    step_away   a step while the camera is on the other view, then back (what a take does: it steps
                while its last camera of the clip frame is showing)

    uv run --project . python -m adapters.rdr2.probes.step_exposure_probe --location rdr2-lakeshore-001
        [--shots <take>/shots.json] [--view wide] [--repeat 6] [--cases held,step,relock,reset] [--clock 12:00]
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

from ..adapter import RDR2Adapter  # noqa: E402


def luma(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="rdr2-lakeshore-001")
    ap.add_argument("--shots")
    ap.add_argument("--view", default="wide")
    ap.add_argument("--repeat", type=int, default=6)
    ap.add_argument("--cases", default="held,step,relock,reset")
    ap.add_argument("--clock", help="set the clock first, as the worker does (12:00)")
    ap.add_argument("--clock-before", help="set the clock to this first and let 300 ticks run (a large jump to --clock)")
    ap.add_argument("--other", default="near_temporal_16", help="with --shots: the camera for away / step_away")
    ap.add_argument("--prime", choices=("sky", "ground"), help="before the take begins, the camera looks at the sky or the ground "
                    "for 300 ticks (the eye adapted to something else when the lock is taken)")
    ap.add_argument("--step-scale", type=float, help="the time scale of a step (adapter step_scale, 0.1)")
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "rdr2_step_exposure", time.strftime("%Y%m%d_%H%M%S") + ("_" + a.label if a.label else ""))
    os.makedirs(out)
    ad = RDR2Adapter({"step_scale": a.step_scale} if a.step_scale else None)
    ad.ensure_ready(restart=False)
    ad.open()
    report = {"location": a.location, "cases": {}}
    n = [0]

    def shot():
        n[0] += 1
        p = os.path.join(out, "%03d.bmp" % n[0])
        ad.capture(p, int(ad.settings["settle"]))
        v = luma(p)
        Image.open(p).resize((480, 270)).save(p[:-4] + ".png")
        os.remove(p)
        ev = float(ad.sess.cmd("exposure", "get")["exposure"])
        return round(v, 2), round(ev, 4)

    try:
        loc = locations.get(capture_paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        if a.clock_before:
            report["clock_before"] = ad.set_clock(a.clock_before)
            ad.wait_frames(300)
        if a.clock or loc.get("clock"):
            report["clock"] = ad.set_clock(a.clock or loc["clock"])
        other = None
        if a.shots:
            with open(a.shots, encoding="utf-8") as f:
                first = json.load(f)["steps"][0]["shots"]
            view = first[0]
            other = next((sh for sh in first if sh["name"].split("_", 1)[1].rsplit("_", 1)[0] == a.other), None)
        else:
            st = ad.subject_state()
            view = u.views(ad, st, u.people(ad, st["position"]))[a.view]
        ad.hide_subject(True)
        if a.prime:
            from ..render_camera import pitch_yaw
            pitch, yaw = pitch_yaw(view["fwd"])
            ad.sess.pose(view["pos"], 80.0 if a.prime == "sky" else -80.0, yaw, view["vfov_deg"])
            ad.sess.cmd("wait", 300)
            report["primed"] = a.prime
        ad.begin_frozen(view)
        report["start"] = shot()
        for case in a.cases.split(","):
            vals = []
            for _ in range(a.repeat):
                if case == "held":
                    ad.wait_frames(20)
                elif case == "step":
                    ad.advance(1 / 30)
                elif case == "relock":
                    ad.advance(1 / 30)
                    ad.sess.cmd("exposure", "unlock")
                    ad.sess.cmd("exposure", "lock")
                elif case == "reset":
                    ad.sess.cmd("exposure", "adapt 1")
                    ad.advance(1 / 30)
                elif case in ("away", "step_away"):
                    ad.set_camera(other)
                    ad.wait_frames(int(ad.settings["settle"]))
                    if case == "step_away":
                        ad.advance(1 / 30)
                    ad.set_camera(view)
                vals.append(shot())
            report["cases"][case] = vals
            print("%-8s %s" % (case, "  ".join("%.2f (ev %.3f)" % v for v in vals)), flush=True)
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
