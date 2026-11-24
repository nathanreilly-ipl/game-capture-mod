"""Does a walker react to the hidden player put in their way during a take? (AGENTS.md: "The player
does not exist for the scene".) The walker is followed by handle inside the game (cm_watch,
cm_watched), so it is always the same person.

    uv run --project . python -m adapters.witcher3.probes.npc_watch_probe [--location <id>] [--trials 4] [--lead 3]

Each trial, with the world running: everyone within 20 m of the location is watched, two looks
0.4 s apart give each one's velocity, and someone walking (0.6 to 2.2 m/s) is chosen. The world
is held, the player put --lead m ahead of the walker on their way, and the world stepped --seconds
in even 1/30 s steps (as takes do), the walker's position read every 3 steps. Modes, in turn:
    none      the player left where he is (at the location, not in the walker's way): the baseline
    ghost     at the spot, hidden, not seen by people and without collisions (cm_park: the method)
    hidden    at the spot, hidden only (as takes were until 2026-11-23)
Reported: the walker's speed during the steps against before, whether they walked past the spot,
how close they came to it, and how far they strayed sideways from their line.
Report: out/probes/witcher3/npc_watch/report.json.
"""
import argparse
import json
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, vec

STEP = 1.0 / 30
MODES = ("none", "ghost", "hidden")


def watched(s):
    out = {}
    for line in s.cmd("watched").data:
        parts = line.split()
        if len(parts) >= 2 and parts[1] != "gone":
            out[int(parts[0])] = np.array(vec(parts[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="witcher3-hierarch-square-centre-001")
    ap.add_argument("--trials", type=int, default=4)
    ap.add_argument("--lead", type=float, default=3.0)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    c = [float(v) for v in loc["position"]]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "npc_watch")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    rows = []
    steps = int(round(a.seconds / STEP))
    try:
        for trial in range(a.trials * len(MODES)):
            mode = MODES[trial % len(MODES)]
            s.cmd("unfreeze")
            s.cmd("unpark", c[0], c[1], c[2] + 0.1, 0)
            s.cmd("hide", 1)
            time.sleep(6)
            pick = None
            for _ in range(10):
                s.cmd("watch", c[0], c[1], c[2], 20.0)
                t0 = time.time()
                p0 = watched(s)
                time.sleep(0.4)
                p1 = watched(s)
                dt = time.time() - t0
                best = None
                for i in p0:
                    if i in p1:
                        v = p1[i] - p0[i]
                        v[2] = 0.0
                        sp = float(np.linalg.norm(v)) / dt
                        if 0.6 <= sp <= 2.2 and (best is None or sp > best[1]):
                            best = (i, sp)
                if best:
                    pick = best
                    break
                time.sleep(1.0)
            if not pick:
                print("trial %d: nobody walking" % trial)
                continue
            i, speed = pick
            s.cmd("freeze")
            now = watched(s)
            before = p1[i]
            if i not in now:
                print("trial %d: the walker is gone" % trial)
                continue
            d = now[i] - before
            d[2] = 0.0
            if float(np.linalg.norm(d)) < 0.05:
                d = p1[i] - p0[i]
                d[2] = 0.0
            d = d / float(np.linalg.norm(d))
            start = now[i]
            spot = start + a.lead * d
            if mode == "ghost":
                s.cmd("park", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05)
            elif mode == "hidden":
                s.cmd("teleport", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05, 0)
            frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
            path = [start]
            for k in range(steps):
                mark = s.log_size()
                r = s.cmd("stepe", STEP, 8, frame_s)
                if s.wait_line("t", r.seq, mark, timeout=30.0) is None:
                    raise SystemExit("a time step did not end")
                if (k + 1) % 3 == 0:
                    w = watched(s)
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
        s.cmd("unpark", c[0], c[1], c[2] + 0.1, 0)
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
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump({"trials": rows, "summary": summary}, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
