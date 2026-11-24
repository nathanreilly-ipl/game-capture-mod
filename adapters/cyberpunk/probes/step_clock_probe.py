"""During a time step between clip frames, how far do the simulation and the real-time clock
(the one our clock plug-in holds, which screens, holograms and blinking lights run on) each move?

A take's step (adapter.advance) should move both by exactly 1/fps. Phases, each measured as the
simulation time (sim_time), the real time, and the hooked clock's own time (real time minus the
change of the plug-in's lag_ms), plus frames rendered and the game's frame time (real_dt):

    running            world running, clock running: the baseline
    running@<s>        world running (no time dilation), clock held at scale s: does the
                       game's frame time, and so the simulation, follow the hooked clock?
    held               the take's hold: dilation 1e-7, clock at clock_scale
    step:run           a step as takes did it until now: clock released for the step
    step:clock<s>      a step with the clock held at scale s during it, dilation as before
    step:only<s>       a step with no time dilation at all, only the clock at scale s
    step:step          the session's step command, as takes do it since 2026-11-23

clock_s is real time minus the change of the plug-in's lag, both read through the session, so it is
only good to about 0.15 s; for the session's step command the per-frame trace gives the clock's
advance directly (trace_clock_ms, against trace_sim_ms).

    uv run --project . python -m adapters.cyberpunk.probes.step_clock_probe [--location ID]
        [--phases running,running@0.1,held,step:run,step:clock0.1,step:only0.1] [--seconds 3]
"""
import json
import os
import sys
import time

from capture import locations, paths as capture_paths

from ..adapter import CyberpunkAdapter


def arg(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    phases = arg(argv, "--phases", "running,running@0.1,held,step:run,step:clock0.1,step:only0.1").split(",")
    seconds = float(arg(argv, "--seconds", 3))
    ad = CyberpunkAdapter({"devices_off_m": 0, "hold_clock": False})
    ad.ensure_ready(restart=False)
    ad.open()
    sess = ad.sess
    hold_scale = float(ad.settings["clock_scale"])
    report = {"phases": []}
    mode = ["run"]

    def clock(verb):
        mode[0] = verb
        return sess.cmd("rtclock", verb)

    def lag():
        # re-sending the mode in force re-bases the clock where it is (no jump) and writes the status
        return float(clock(mode[0])["clock_lag_ms"]) / 1000.0

    def sample():
        st = sess.cmd("state")
        return float(st["sim_time"]), int(st["tick"]), float(st.get("real_dt", 0)), time.time(), lag()

    def record(name, a, b, extra=None):
        d_sim, d_tick, d_real = b[0] - a[0], b[1] - a[1], b[3] - a[3]
        d_clock = d_real - (b[4] - a[4])
        r = {"phase": name, "sim_s": round(d_sim, 6), "real_s": round(d_real, 3), "clock_s": round(d_clock, 4),
             "frames": d_tick, "real_dt_end": round(b[2], 5), **(extra or {})}
        report["phases"].append(r)
        print(json.dumps(r), flush=True)

    try:
        if "--location" in argv:
            loc = locations.get(capture_paths.LOCATIONS, arg(argv, "--location", None))
            report["location"] = loc["id"]
            ad.go_to(loc["position"], loc["facing_deg"])
        for ph in phases:
            if ph == "running" or ph.startswith("running@"):
                sess.cmd("unfreeze")
                clock("run" if ph == "running" else "hold %s" % ph.split("@")[1])
                a = sample()
                time.sleep(seconds)
                record(ph, a, sample())
            elif ph == "held":
                sess.cmd("freeze")
                clock("hold %.9g" % hold_scale)
                a = sample()
                time.sleep(seconds)
                record(ph, a, sample())
            elif ph.startswith("step:"):
                kind = ph.split(":", 1)[1]
                sess.cmd("freeze")
                clock("hold %.9g" % hold_scale)
                sess.cmd("wait", 10)
                a = sample()
                if kind == "run":
                    clock("run")
                    r = sess.cmd("advance", "%.9f %.6f" % (1 / 30, 0.1), timeout=300)
                elif kind.startswith("clock"):
                    clock("hold %s" % kind[len("clock"):])
                    r = sess.cmd("advance", "%.9f %.6f" % (1 / 30, 0.1), timeout=600)
                elif kind == "step":   # the session's step command (what the adapter uses since 2026-11-23)
                    r = sess.cmd("step", "%.9f %.9g" % (1 / 30, hold_scale), timeout=600)
                else:   # only<s>: no dilation (largest dilation 1), the clock alone slows the world
                    clock("hold %s" % kind[len("only"):])
                    r = sess.cmd("advance", "%.9f %.6f" % (1 / 30, 1.0), timeout=600)
                clock("hold %.9g" % hold_scale)
                extra = {"advanced_s": float(r["advanced_s"]), "advance_frames": int(r["frames"])}
                if r.get("trace"):
                    # per frame: simulation advanced (ms) / real frame (ms) / clock scale in force (the
                    # scale sent before; it takes effect about a frame later). The clock's advance from
                    # it is better than clock_s, whose two status readings are a frame or more apart
                    # from the real-time readings (up to about 0.15 s off)
                    rows = [e.split("/") for e in r["trace"].split()]
                    extra["trace_sim_ms"] = round(sum(float(x[0]) for x in rows), 3)
                    extra["trace_clock_ms"] = round(sum(float(x[1]) * float(x[2] or 0) for x in rows[1:]), 3)
                    extra["trace"] = r["trace"]
                record(ph, a, sample(), extra)
    finally:
        try:
            sess.cmd("freeze")
            clock("run")
        except Exception as e:
            print("restore:", e)
        ad.close()
    out = os.path.join(capture_paths.OUT, "probes", "cyberpunk_step_clock")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, time.strftime("%Y%m%d_%H%M%S") + ".json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
