"""Does holding the real-time clock (our clock plug-in, addons/clock) stop what a held world
does not: video ads, holograms, blinking lights?

One pose in a held world, with devices left on, is captured many times a few frames apart in
phases: the clock running, then held (all hooked clocks, or only the exe's, or only Bink's),
one frame per capture. For each phase: how much the captures differ per pixel (the share of
pixels whose standard deviation is over 4 levels), the brightness, the frame time, and the
plug-in's call counts (does the game call the hooked clocks at all, and keep rendering).

    uv run --project . python -m adapters.cyberpunk.probes.clock_probe [--location ID] [--pitch 8]
        [--count 10] [--gap 6] [--phases run,hold,exe,bink,run] [--scale 0]
"""
import json
import os
import sys
import time

import numpy as np
from PIL import Image

from capture import locations, paths as capture_paths

from ..adapter import CyberpunkAdapter

MASKS = {"hold": "ffffffff", "exe": "0000000f", "bink": "00000f00"}


def arg(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    count, gap = int(arg(argv, "--count", 10)), int(arg(argv, "--gap", 6))
    phases = arg(argv, "--phases", "run,hold,exe,bink,run").split(",")
    scale, pitch = float(arg(argv, "--scale", 0)), float(arg(argv, "--pitch", 8))
    ad = CyberpunkAdapter({"devices_off_m": 0, "accumulate": 1, "hold_clock": False})
    ad.ensure_ready(restart=False)
    ad.open()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_clock")
    os.makedirs(out, exist_ok=True)
    report = {"count": count, "gap_frames": gap, "scale": scale, "phases": {}}
    try:
        print("clock plug-in:", ad.sess.cmd("rtclock", "state").get("clock_module0"))
        if "--location" in argv:
            loc = locations.get(capture_paths.LOCATIONS, arg(argv, "--location", None))
            report["location"] = loc["id"]
            ad.go_to(loc["position"], loc["facing_deg"])
            if loc.get("clock"):
                ad.set_clock(loc["clock"])
        st = ad.subject_state()
        fwd, right, up = (np.array(v) for v in ad.heading_basis(st["facing_deg"]))
        p = np.radians(pitch)
        fwd, up = fwd * np.cos(p) + up * np.sin(p), up * np.cos(p) - fwd * np.sin(p)
        eye = np.array(st["position"]) + np.array([0, 0, 1.6])
        ad.hide_subject(True)
        ad.begin_frozen({"pos": eye, "right": right, "fwd": fwd, "up": up, "vfov_deg": 60.0})
        sheet = []
        for n, phase in enumerate(phases):
            t0 = time.time()
            phase, _, s = phase.partition("@")   # a phase may name its own scale: exe@0.001
            if phase == "run":
                c = ad.sess.cmd("rtclock", "run")
            else:
                c = ad.sess.cmd("rtclock", "hold %g %s" % (float(s) if s else scale, MASKS[phase]))
            print(phase, "clock", c.get("clock_state"), c.get("clock_scale"), c.get("clock_mask"), flush=True)
            ad.wait_frames(30)
            s0 = ad.sess.cmd("rtclock", "state")
            frames = []
            for i in range(count):
                path = os.path.join(out, "c.bmp")
                info = ad.capture(path, gap)
                frames.append(np.asarray(Image.open(path).convert("RGB").resize((1280, 720), Image.BOX), dtype=np.float32))
                os.remove(path)
            s1 = ad.sess.cmd("rtclock", "state")
            f = np.stack(frames)
            sd = f.std(axis=0).mean(axis=2)
            calls = lambda s, m: dict(kv.split(":") for kv in s.get("clock_calls%d" % m, "").split())  # noqa: E731
            rep = {"state": c.get("clock_state"), "mask": c.get("clock_mask"),
                   "seconds": round(time.time() - t0, 1), "frame_s": float(ad.sess.state.get("real_dt", 0)),
                   "sim_time": info.get("sim_time"), "brightness": [round(float(x.mean()), 2) for x in f],
                   "next_to_next": round(float(np.mean([np.abs(f[i] - f[i + 1]).mean() for i in range(count - 1)])), 4),
                   "per_pixel_std_mean": round(float(sd.mean()), 4),
                   "share_std_over_4": round(float((sd > 4).mean()), 5),
                   "share_std_over_12": round(float((sd > 12).mean()), 5),
                   "lag_ms": s1.get("clock_lag_ms"),
                   "calls_during_exe": {k: int(v) - int(calls(s0, 0).get(k, 0)) for k, v in calls(s1, 0).items()},
                   "calls_during_bink": {k: int(v) - int(calls(s0, 1).get(k, 0)) for k, v in calls(s1, 1).items()},
                   "problems": ad.health()["problems"], "scale": c.get("clock_scale")}
            name = "%d_%s" % (n, phase)
            report["phases"][name] = rep
            print(phase, json.dumps({k: rep[k] for k in ("share_std_over_4", "share_std_over_12", "next_to_next", "frame_s", "lag_ms")}),
                  flush=True)
            with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:   # kept if a later phase ends the game
                json.dump(report, fh, indent=1)
            Image.fromarray(np.clip(sd * 16, 0, 255).astype(np.uint8)).save(os.path.join(out, name + "_std_x16.jpg"), quality=88)
            Image.fromarray(f.mean(axis=0).astype(np.uint8)).save(os.path.join(out, name + "_average.jpg"), quality=90)
            sheet.append((name, Image.fromarray(f[0].astype(np.uint8)).resize((640, 360)),
                          Image.fromarray(np.clip(sd * 16, 0, 255).astype(np.uint8)).convert("RGB").resize((640, 360))))
        ad.sess.cmd("rtclock", "run")
        side = Image.new("RGB", (1280, 360 * len(sheet)))
        for i, (_, a, b) in enumerate(sheet):
            side.paste(a, (0, 360 * i))
            side.paste(b, (640, 360 * i))
        side.save(os.path.join(out, "sheet.jpg"), quality=85)
        ad.end_frozen()
    finally:
        ad.close()
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("phases (frame | std x16):", ", ".join(report["phases"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
