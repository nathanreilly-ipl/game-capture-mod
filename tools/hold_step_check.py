"""What changes in a held world, and what changes wrongly across time steps. Game-agnostic: works
only through the game's adapter (capture/adapter.py), so every game gets the same checks
(docs/VISUAL_CHECKS.md says what each number catches).

At one location, a few fixed views (tools/upscaler_ab.py's views of the player's spot, the player
hidden as in a take) are captured:

1. **Held**: each view `--repeats` times, `--gap` frames apart, the world held. Nothing should
   change: what does is renderer noise (spread evenly) or something running on real time
   (screens, holograms, blinking lights, cloth or foliage on their own clock: bright spots in the
   map). The game's instant() must not move.
2. **Steps**: `--steps` time steps of 1/fps each (adapter.advance), as a take films over time.
   After each step every view is captured twice, `--gap` frames apart. The first captures make a
   clip per view, measured as tools/temporal_flicker.py does (each step against the average of
   its neighbours: steady motion cancels, flicker does not); the pair taken within one step says
   how much changes *without* the world moving (noise, real-time animation, history settling
   after the step). Brightness per step shows exposure drifting or flashing. Where the adapter
   has the `obstacles` capability, the people, animals and vehicles within `--radius` m are
   listed at every step: an id that leaves or arrives between steps is a person popping in or
   out (a population system at work), not motion.

    uv run --project . python tools/hold_step_check.py --game cyberpunk --location cyberpunk-kabuki-market-001
        [--views medium,wide,landscape] [--repeats 6] [--gap 6] [--steps 12] [--fps 30] [--settle N]
        [--clock 12:00] [--weather W] [--set key=value ...] [--label NAME]
        [--shots <take>/shots.json --cameras near_temporal_00,near_moving@12]   (a take's own cameras)
        [--key F15 --key-after F14]   (a key pressed after the session opens, and one at the end)

Writes out/checks/hold_step/<stamp>_<game>_<label>/: report.json; per view held_std_x8.png (per-
pixel standard deviation of the held captures, x8), steps_flicker_x8.png (the temporal map),
steps_sheet.jpg (the clip), and the frames as PNG.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import adapters_registry, paths  # noqa: E402
from capture import locations as locs  # noqa: E402
from capture.util import stamp, write_json  # noqa: E402
import temporal_flicker as tf  # noqa: E402
import upscaler_ab as u  # noqa: E402

SMALL = (480, 270)


def small(path):
    return np.asarray(Image.open(path).convert("RGB").resize(SMALL, Image.BOX), dtype=np.float32)


def luma(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return float((a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


def held_stats(paths_):
    fs = np.stack([small(p) for p in paths_])
    std = fs.std(axis=0).mean(axis=2)
    neigh = [float(np.abs(fs[i + 1] - fs[i]).mean()) for i in range(len(fs) - 1)]
    return {"captures": len(paths_), "mean_neighbour_diff": round(float(np.mean(neigh)), 3),
            "share_std_over_4": round(float((std > 4).mean()), 5), "share_std_over_12": round(float((std > 12).mean()), 5),
            "luma": [round(luma(p), 2) for p in paths_]}, std


def sheet(paths_, labels, out, cols=6):
    ims = []
    for p, lab in zip(paths_, labels):
        im = Image.open(p).convert("RGB").resize((400, 225))
        ImageDraw.Draw(im).text((4, 4), lab, fill="yellow")
        ims.append(im)
    rows = (len(ims) + cols - 1) // cols
    o = Image.new("RGB", (400 * cols, 225 * rows))
    for i, im in enumerate(ims):
        o.paste(im, ((i % cols) * 400, (i // cols) * 225))
    o.save(out, quality=88)


def settings_arg(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, choices=adapters_registry.names())
    ap.add_argument("--location", required=True)
    ap.add_argument("--views", default="medium,wide,landscape", help="views of tools/upscaler_ab.py: portrait, medium, wide, landscape")
    ap.add_argument("--shots", help="a take's shots.json: use its cameras instead (--cameras), at the take's location")
    ap.add_argument("--cameras", default="near_temporal_00,near_temporal_16",
                    help="with --shots: camera names as in the capture log (near_temporal_00, near_moving@12 = its pose at clip frame 12)")
    ap.add_argument("--repeats", type=int, default=6, help="captures of each view in the held world")
    ap.add_argument("--gap", type=int, default=6, help="frames between repeated captures of one view")
    ap.add_argument("--steps", type=int, default=12, help="time steps")
    ap.add_argument("--fps", type=float, default=30.0, help="a step is 1/fps of world time")
    ap.add_argument("--settle", type=int, help="frames after a camera cut (default: the adapter's)")
    ap.add_argument("--radius", type=float, default=40.0, help="people, animals, vehicles listed within this many metres (0: no census; it "
                    "is the heaviest script work here, and GTA V's RedLua faulted during it)")
    ap.add_argument("--clock")
    ap.add_argument("--weather")
    ap.add_argument("--set", action="append", help="an adapter setting for this run, key=value (value as JSON if it parses)")
    ap.add_argument("--key", help="a key the adapter presses once the session is open (RDR2's ReShade preset shortcuts: F15 = ray tracing off)")
    ap.add_argument("--key-after", help="the key pressed at the end to undo it (RDR2: F14)")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    out = os.path.join(paths.OUT, "checks", "hold_step", "_".join(x for x in (stamp(), a.game, a.label) if x))
    os.makedirs(out)
    log = print
    adapter = adapters_registry.get(a.game)(settings_arg(a.set) or None)
    settle = a.settle or int(adapter.settings.get("settle", 40))
    report = {"game": a.game, "location": a.location, "settle": settle, "gap": a.gap, "fps": a.fps, "key": a.key,
              "settings": settings_arg(a.set), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    adapter.ensure_ready(restart=False)
    adapter.open()
    key, key_after = a.key, a.key_after
    if key:   # e.g. a ReShade preset shortcut (RDR2: F15 = Reality Redemption 2 off), pressed after the session opens
        adapter.press_key(key)
        time.sleep(3.0)
    t0 = time.time()
    hidden = False

    def shoot(label, wait):
        path = os.path.join(out, label + ".bmp")
        r = adapter.capture(path, wait)
        png = path[:-4] + ".png"
        Image.open(path).save(png)
        os.remove(path)
        problems = (r.get("health") or {}).get("problems") if isinstance(r, dict) else r
        if problems:
            log("  %s: %s" % (label, problems))
        return png

    try:
        loc = locs.get(paths.LOCATIONS, a.location)
        adapter.go_to(loc["position"], loc["facing_deg"])
        if a.weather:
            report["weather"] = adapter.set_weather(a.weather)
        if a.clock or loc.get("clock"):
            report["clock"] = adapter.set_clock(a.clock or loc["clock"])
        st = adapter.subject_state()
        center = st["position"]
        boxes = u.people(adapter, center)
        if a.shots:
            with open(a.shots, encoding="utf-8") as f:
                take_shots = [sh for step in json.load(f)["steps"] for sh in step["shots"]]
            vs = {}
            for spec in a.cameras.split(","):
                cam, _, fr = spec.partition("@")
                hit = [sh for sh in take_shots if sh["name"].split("_", 1)[1].rsplit("_", 1)[0] == cam
                       and (not fr or int(sh["frame"]) == int(fr))]
                if not hit:
                    raise SystemExit("no shot of camera %s in %s" % (spec, a.shots))
                vs[spec.replace("@", "_f")] = hit[0]
            names = list(vs)
        else:
            allv = u.views(adapter, st, boxes)
            names = [n for n in a.views.split(",") if n]
            vs = {n: allv[n] for n in names}
        if hasattr(adapter, "prepare_take"):   # as the take loop does (capture/runner.py)
            adapter.prepare_take({"steps": [{"shots": list(vs.values())}]})
        adapter.hide_subject(True)
        hidden = True
        adapter.begin_frozen(vs[names[0]])
        report["render"] = adapter.render_settings()

        # 1. held
        report["held"] = {}
        i0 = adapter.instant()
        for n in names:
            adapter.set_camera(vs[n])
            shots = [shoot("held_%s_%02d" % (n, i), settle if i == 0 else a.gap) for i in range(a.repeats)]
            stats, std = held_stats(shots)
            report["held"][n] = stats
            Image.fromarray(np.clip(std * 8, 0, 255).astype(np.uint8)).save(os.path.join(out, "%s_held_std_x8.png" % n))
            log("held %-10s neighbour diff %.3f, std>4 %.3f%%, std>12 %.3f%%" % (
                n, stats["mean_neighbour_diff"], 100 * stats["share_std_over_4"], 100 * stats["share_std_over_12"]))
        report["held_instant_moved"] = adapter.instant() != i0

        # 2. steps
        series = {n: [] for n in names}
        within = {n: [] for n in names}
        steps, population = [], []

        def census():
            if "obstacles" not in adapter.capabilities or a.radius <= 0:   # --radius 0: no census
                return None
            return [(o["kind"], np.asarray(o["center"], float)) for o in adapter.obstacles(center, a.radius)]

        def compare(before, after, reach):
            """Matches things of one kind between two steps by position (ids are not stable in every
            game): what has no partner within reach metres left or arrived."""
            left, used = [], set()
            for kind, p in before:
                best = None
                for j, (k2, q) in enumerate(after):
                    if k2 == kind and j not in used:
                        d = float(np.linalg.norm(q - p))
                        if d <= reach and (best is None or d < best[0]):
                            best = (d, j)
                if best is None:
                    left.append((kind, [round(float(v), 1) for v in p]))
                else:
                    used.add(best[1])
            came = [(k, [round(float(v), 1) for v in q]) for j, (k, q) in enumerate(after) if j not in used]
            return left, came

        pop0 = census()
        for k in range(1, a.steps + 1):
            r = adapter.advance(1.0 / a.fps) or {}
            inst = adapter.instant()
            steps.append({"step": k, "instant": inst, **{kk: vv for kk, vv in r.items() if isinstance(vv, (int, float, str))}})
            for n in names:
                adapter.set_camera(vs[n])
                first = shoot("step%02d_%s_a" % (k, n), settle)
                second = shoot("step%02d_%s_b" % (k, n), a.gap)
                series[n].append((k, first))
                within[n].append(float(np.abs(small(first) - small(second)).mean()))
            pop = census()
            if pop is not None:
                # one step moves a person a few centimetres and a car under a metre (30 m/s)
                gone, came = compare(pop0, pop, reach=max(1.5, 40.0 / a.fps))
                population.append({"step": k, "count": len(pop), "gone": gone, "came": came})
                if gone or came:
                    log("step %d: %d gone %s, %d came %s" % (k, len(gone), gone[:4], len(came), came[:4]))
                pop0 = pop
            log("step %d: instant %s %s" % (k, inst, r))
        report["steps"] = steps
        report["population"] = population
        report["views"] = {}
        for n in names:
            m, heat = tf.measure(series[n])
            m["within_step_diff"] = round(float(np.mean(within[n])), 3)
            m["luma"] = [round(luma(p), 2) for _, p in series[n]]
            report["views"][n] = m
            Image.fromarray(np.clip(heat * 8, 0, 255).astype(np.uint8)).save(os.path.join(out, "%s_steps_flicker_x8.png" % n))
            sheet([p for _, p in series[n]], ["step %d" % k for k, _ in series[n]], os.path.join(out, "%s_steps_sheet.jpg" % n))
            log("steps %-10s roughness %.3f, over 12 %.3f%%, within a step %.3f, brightness jitter %.3f, first step x%s, "
                "exposure drift %s (range %s), luma %s" % (
                    n, m["roughness"], 100 * m["share_over_12"], m["within_step_diff"], m["brightness_jitter"],
                    m["first_step_ratio"], m["exposure_drift"], m["exposure_drift_range"], m["luma"][:3] + ["..."] + m["luma"][-2:]))
    finally:
        try:
            adapter.end_frozen()
            if hidden:
                adapter.hide_subject(False)
        except Exception as e:
            log("end_frozen: %s" % e)
        if key_after:
            adapter.press_key(key_after)
            time.sleep(3.0)
        adapter.close()
        report["minutes"] = round((time.time() - t0) / 60, 1)
        write_json(os.path.join(out, "report.json"), report)
        log("wrote %s" % out)


if __name__ == "__main__":
    main()
