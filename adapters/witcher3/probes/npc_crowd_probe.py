"""Do people avoid, stop at or turn from the hidden player during a take? The whole crowd around
the rig's centre, tracked through time steps. (AGENTS.md: "The player does not exist for the
scene"; npc_influence_probe.py followed one walker and too often picked someone standing.)

    uv run --project . python -m adapters.witcher3.probes.npc_crowd_probe [--location <id>] [--trials 3]

Each trial: the world runs 8 s, the player is put per mode and the world runs 2 s more, then it is
held and stepped 3 s in even 1/30 s steps (as takes do), every person within --radius m of the
centre located every 3 steps and followed from sample to sample (nearest within 0.4 m; people walk
at most about 0.2 m between samples). Modes, in turn:
    ghost     the player at the centre, hidden, not seen by people and without collisions
              (cm_park in place: the capture method)
    hidden    the player at the centre, hidden only (as takes were until 2026-11-23)
    side      as ghost, but 15 m to the side of the centre (the baseline: nobody's way is blocked
              at the centre; further away the crowd goes with him)
Reported per trial and per mode: people followed, how many moved more than 0.5 m, their mean
speed, how many passed within 1.0 m and 0.5 m of the centre, and the closest any came.
Report: out/probes/witcher3/npc_crowd/report.json.

Found (Hierarch Square's centre, 2026-11-23): few people move there (0 to 2 of about 12 per
trial) and none came within 3.7 m of the centre in any mode, so it decided nothing; see
npc_watch_probe.py.
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
from ..session import Session
from .npc_influence_probe import people

STEP = 1.0 / 30
MODES = ("ghost", "hidden", "side")


def follow(s, ex, centre, radius, steps, frame_s, every=3):
    """Tracks of everyone near the centre over `steps` even steps: lists of (x, y, z)."""
    tracks = [[p["pos"]] for p in people(s, centre, radius)]
    open_ = list(range(len(tracks)))
    for i in range(steps):
        mark = s.log_size()
        r = s.cmd("stepe", STEP, 8, frame_s)
        if s.wait_line("t", r.seq, mark, timeout=30.0) is None:
            raise SystemExit("a time step did not end")
        if (i + 1) % every:
            continue
        now = [p["pos"] for p in people(s, centre, radius + 1.0)]
        pairs = sorted((float(np.linalg.norm((tracks[t][-1] - q)[:2])), t, j)
                       for t in open_ for j, q in enumerate(now))
        used_t, used_j, still = set(), set(), []
        for dist, t, j in pairs:
            if dist > 0.4 or t in used_t or j in used_j:
                continue
            used_t.add(t)
            used_j.add(j)
            tracks[t].append(now[j])
            still.append(t)
        for j, q in enumerate(now):
            if j not in used_j:
                tracks.append([q])
                still.append(len(tracks) - 1)
        open_ = still
    return tracks


def measure(tracks, centre, seconds):
    c = np.array(centre)
    moving, speeds, within1, within05, closest = 0, [], 0, 0, None
    for tr in tracks:
        if len(tr) < 5:
            continue
        pts = np.array(tr)
        path = float(np.sum(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)))
        if path < 0.5:
            continue
        moving += 1
        speeds.append(path / (seconds * (len(tr) - 1)))       # seconds: game time between samples
        d = float(np.min(np.linalg.norm(pts[:, :2] - c[:2], axis=1)))
        within1 += d < 1.0
        within05 += d < 0.5
        closest = d if closest is None else min(closest, d)
    return {"followed": len(tracks), "moving": moving, "speed_m_s": round(float(np.mean(speeds)), 3) if speeds else None,
            "within_1m": within1, "within_0.5m": within05, "closest_m": round(closest, 2) if closest is not None else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="witcher3-hierarch-square-centre-001")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--radius", type=float, default=8.0)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--side", type=float, default=15.0)
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    centre = [float(v) for v in loc["position"]]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "npc_crowd")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("hud", 0)
    s.cmd("hide", 1)
    rows = []
    steps = int(round(a.seconds / STEP))
    try:
        for trial in range(a.trials * len(MODES)):
            mode = MODES[trial % len(MODES)]
            s.cmd("unfreeze")
            s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
            s.cmd("hide", 1)
            time.sleep(8)
            if mode == "ghost":
                s.cmd("park", centre[0], centre[1], centre[2] + 0.05)
            elif mode == "hidden":
                s.cmd("teleport", centre[0], centre[1], centre[2] + 0.05, 0)
            else:
                s.cmd("park", centre[0] + a.side, centre[1], centre[2] + 0.05)
            time.sleep(2)
            s.cmd("freeze")
            player = s.state().get("player")
            frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
            tracks = follow(s, ex, centre, a.radius, steps, frame_s)
            row = dict(measure(tracks, centre, STEP * 3), mode=mode, trial=trial, player=player)
            rows.append(row)
            print("trial %d %-6s %s" % (trial, mode, json.dumps({k: v for k, v in row.items() if k not in ("mode", "trial")})))
    finally:
        s.cmd("unfreeze")
        s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
    summary = {}
    for mode in MODES:
        rs = [r for r in rows if r["mode"] == mode]
        if rs:
            summary[mode] = {"trials": len(rs), "moving": sum(r["moving"] for r in rs),
                             "within_1m": sum(r["within_1m"] for r in rs), "within_0.5m": sum(r["within_0.5m"] for r in rs),
                             "speed_m_s": round(float(np.mean([r["speed_m_s"] for r in rs if r["speed_m_s"]])), 3) if any(r["speed_m_s"] for r in rs) else None,
                             "closest_m": min((r["closest_m"] for r in rs if r["closest_m"] is not None), default=None)}
            print("%-6s %s" % (mode, json.dumps(summary[mode])))
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump({"trials": rows, "summary": summary}, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
