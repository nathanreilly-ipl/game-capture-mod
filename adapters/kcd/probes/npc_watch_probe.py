"""Does a walker react to the hidden player put in their way during a take? (AGENTS.md: "The player
does not exist for the scene".) People are followed by their entity id, which stays the same.

    uv run --project . python -m adapters.kcd.probes.npc_watch_probe [--location <id>] [--trials 3] [--lead 3]

Each trial, with the world running: everyone within 25 m of the location, looked at twice 0.5 s
apart, and someone walking (0.6 to 2.2 m/s) chosen. The world is held, the player put --lead m
ahead of the walker on their way, and the world stepped --seconds in even 1/30 s steps (as takes
do), the walker's position read every 3 steps. Modes, in turn:
    none      the player left where he is (away from the walker): the baseline
    hidden    at the spot, his body hidden only
    ghost     at the spot, hidden, not perceived by anyone and without physics (cm ghost: the method)
Reported: the walker's speed during the steps against before, whether they walked past the spot,
how close they came to it, how far they strayed sideways. out/probes/kcd/npc_watch/report.json.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from .. import paths  # noqa: F401
from ..session import Session, parse_kv, vec

STEP = 1.0 / 30
MODES = ("none", "hidden", "ghost")


def people(s, c, r=25.0):
    out = {}
    for line in s.cmd("people", c[0], c[1], c[2], r).data:
        parts = line.split()
        out[parts[0]] = np.array(vec(parts[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="kcd-rattay-pillory-001")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--lead", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    c = [float(v) for v in loc["position"]]
    s = Session()
    out_dir = os.path.join(capture_paths.OUT, "probes", "kcd", "npc_watch")
    os.makedirs(out_dir, exist_ok=True)
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    rows = []
    steps = int(round(a.seconds / STEP))
    try:
        for trial in range(a.trials * len(MODES)):
            mode = MODES[trial % len(MODES)]
            s.cmd("unfreeze")
            s.cmd("ghost", 0)
            s.cmd("hide", 1)
            s.cmd("teleport", c[0], c[1], c[2] + 0.1, 0)
            if mode == "ghost":           # the game's invisibility command needs the world running
                s.cmd("ghost", 1)
            time.sleep(5)
            pick = None
            for _ in range(10):
                t0 = time.time()
                p0 = people(s, c)
                time.sleep(0.5)
                p1 = people(s, c)
                dt = time.time() - t0
                best = None
                for i in p0:
                    if i in p1:
                        v = p1[i] - p0[i]
                        v[2] = 0.0
                        sp = float(np.linalg.norm(v)) / dt
                        if 0.6 <= sp <= 2.2 and (best is None or sp > best[1]):
                            best = (i, sp, v / np.linalg.norm(v))
                if best:
                    pick = best
                    break
                time.sleep(1.0)
            if not pick:
                print("trial %d: nobody walking" % trial)
                continue
            i, speed, d = pick
            s.cmd("freeze")
            now = people(s, c)
            if i not in now:
                print("trial %d: the walker is gone" % trial)
                continue
            start = now[i]
            spot = start + a.lead * d
            if mode == "hidden":
                s.cmd("teleport", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05, 0)
            elif mode == "ghost":
                s.cmd("teleport", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05, 0)
            path = [start]
            for k in range(steps):
                mark = s.log_size()
                r = s.cmd("step", STEP, 8)
                if s.wait_line("t", r.seq, mark, timeout=20.0) is None:
                    raise SystemExit("a step did not end")
                if (k + 1) % 3 == 0:
                    w = people(s, start, 15.0)
                    if i in w:
                        path.append(w[i])
            player = np.array(vec(s.state()["player"]))
            pts = np.array(path)
            side = np.array([-d[1], d[0], 0.0])
            along = (pts - start) @ d
            moved = float(np.sum(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)))
            row = {"mode": mode, "speed_before": round(speed, 3),
                   "speed_m_s": round(moved / (STEP * 3 * max(1, len(pts) - 1)), 3),
                   "passed_spot": bool(along.max() > a.lead + 0.3), "furthest_along_m": round(float(along.max()), 2),
                   "closest_to_spot_m": round(float(np.min(np.linalg.norm((pts - spot)[:, :2], axis=1))), 2),
                   "stray_m": round(float(np.max(np.abs((pts - start) @ side))), 2),
                   "player_to_spot_m": round(float(np.linalg.norm((player - spot)[:2])), 2), "samples": len(pts)}
            rows.append(row)
            print("trial %d %-6s %s" % (trial, mode, json.dumps({k: v for k, v in row.items() if k != "mode"})))
    finally:
        s.cmd("unfreeze")
        s.cmd("ghost", 0)
        s.cmd("teleport", c[0], c[1], c[2] + 0.1, 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
    summary = {}
    for mode in MODES:
        rs = [r for r in rows if r["mode"] == mode]
        if rs:
            summary[mode] = {"trials": len(rs), "passed_spot": sum(r["passed_spot"] for r in rs),
                             "speed_m_s": round(float(np.mean([r["speed_m_s"] for r in rs])), 3),
                             "speed_before": round(float(np.mean([r["speed_before"] for r in rs])), 3),
                             "closest_to_spot_m": round(float(np.mean([r["closest_to_spot_m"] for r in rs])), 2),
                             "stray_m": round(float(np.mean([r["stray_m"] for r in rs])), 2)}
            print("%-6s %s" % (mode, json.dumps(summary[mode])))
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump({"trials": rows, "summary": summary}, f, indent=1)


if __name__ == "__main__":
    main()
