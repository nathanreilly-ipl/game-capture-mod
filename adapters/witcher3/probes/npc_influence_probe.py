"""Do people react to the hidden player over time steps? (AGENTS.md: "The player does not exist for
the scene".) Superseded by npc_watch_probe.py: finding the walker again by position, from outside
the game, picked someone standing nearby too often (even the baseline showed walkers at 0 m/s).

    uv run --project . python -m adapters.witcher3.probes.npc_influence_probe [--location <id>] [--trials 3] [--height 25]

At a place with people walking, each trial: with the world running, find someone walking (moving
at least 0.6 m/s between two looks 0.4 s apart), hold the world, find them again, take the spot 2 m
ahead of them on their way, and
    none      leave the invisible player where he stands (the baseline: he is not in their way),
    ghost     put him at the spot invisible to people and with his collisions off (cm_park),
    side      the same as ghost, but --far metres to the side of the spot, or
    hidden    put the invisible player at the spot (as takes did first),
then step the world 3 s in even 1/30 s steps (cm_stepe, as takes do), logging that person's
position every 3 steps. (Holding first matters: the commands between finding them and holding took
2-3 s, in which they walked past the spot, 2026-11-23.)
(The game puts a teleported player on the ground whatever his physics, so he cannot be parked in
the air as in RDR2. Parked 80 m to the side he took the crowd with him: people within 15 m of the
spot went from 59 to 7 and 22 to 1 in a few seconds, so --far is 15 m.) Reported per trial: how close they came to the spot, how far they strayed
sideways from the straight line they were on, and their average speed; the modes take turns.
Someone who walks around, stops at or turns away from an empty spot shows a larger sideways stray
and a lower speed with the player at it than with him far away.

Report: out/probes/witcher3/npc_influence/report.json.
"""
import argparse
import json
import math
import os
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, parse_kv, vec

STEP = 1.0 / 30
MODES = ("none", "ghost", "side", "hidden")


def people(s, centre, radius=25.0):
    out = []
    r = s.cmd("ents", centre[0], centre[1], centre[2], radius, timeout=20)
    for line in r.data:
        head, _, name = line.partition(" name=")
        head, _, _tags = head.partition(" tags=")
        e = parse_kv(head)
        if e.get("kind") == "npc" and e.get("human") == "1" and e.get("alive") == "1":
            out.append({"name": name.strip(), "pos": np.array(vec(e["pos"])), "yaw": float(e["yaw"])})
    return out


def find_walker(s, centre):
    """Someone walking: matched between two looks 0.4 s apart by nearest position (the game gives
    these townspeople no names), alone within 1.5 m so the match is not someone else."""
    a = people(s, centre)
    time.sleep(0.4)
    b = people(s, centre)
    best = None
    for p in b:
        if not a:
            break
        dists = sorted(float(np.linalg.norm((q["pos"] - p["pos"])[:2])) for q in a)
        q = min(a, key=lambda q: float(np.linalg.norm((q["pos"] - p["pos"])[:2])))
        if len(dists) > 1 and dists[1] < 1.5:
            continue
        v = (p["pos"] - q["pos"]) / 0.4
        v[2] = 0.0
        speed = float(np.linalg.norm(v))
        if 0.6 <= speed <= 2.2 and (best is None or speed > best[1]):
            best = (p, speed, v / speed)
    return best


def track(s, ex, who, steps, every=3, frame_s=1.0 / 60):
    """Their position every `every` steps: the nearest person within 0.5 m of the last position."""
    path = []
    last = who["pos"]
    for i in range(steps):
        mark = s.log_size()
        r = s.cmd("stepe", STEP, 8, frame_s)
        if s.wait_line("t", r.seq, mark, timeout=30.0) is None:
            raise SystemExit("a time step did not end")
        if (i + 1) % every == 0:
            near = [p for p in people(s, last, 3.0) if float(np.linalg.norm((p["pos"] - last)[:2])) < 0.5]
            if not near:
                path.append(None)
                continue
            p = min(near, key=lambda p: float(np.linalg.norm(p["pos"] - last)))
            last = p["pos"]
            path.append(p["pos"].tolist())
    return path


def follow_running(s, who, seconds, every=0.3):
    """The world running: their position about every `every` s, the nearest person within 1.0 m
    of the last position (people walk at most about 0.7 m in that time)."""
    path, last, t0 = [], who["pos"], time.time()
    while time.time() - t0 < seconds:
        time.sleep(every)
        near = [p for p in people(s, last, 3.0) if float(np.linalg.norm((p["pos"] - last)[:2])) < 1.0]
        if not near:
            path.append(None)
            continue
        p = min(near, key=lambda p: float(np.linalg.norm(p["pos"] - last)))
        last = p["pos"]
        path.append((time.time() - t0, p["pos"].tolist()))
    return path


def running_trials(s, centre, loc, a):
    """How people react to the player put in their way is the game's AI, the same whether the
    world is held between steps or not; with the world running the walker never has to be found
    again after a hold. The player is put --lead m ahead of a walker and the walker followed."""
    rows = []
    for trial in range(a.trials * 3):
        mode = ("none", "ghost", "hidden")[trial % 3]
        s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
        s.cmd("hide", 1)
        time.sleep(3)
        found = None
        for _ in range(30):
            found = find_walker(s, centre)
            if found:
                break
            time.sleep(0.5)
        if not found:
            print("trial %d: nobody walking" % trial)
            continue
        who, speed, d = found
        spot = who["pos"] + a.lead * d
        if mode == "ghost":
            s.cmd("park", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05)
        elif mode == "hidden":
            s.cmd("teleport", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05, 0)
        path = follow_running(s, who, a.seconds + 1.0)
        pts = [np.array(p) for _, p in [q for q in path if q is not None]]
        times = [t for t, _ in [q for q in path if q is not None]]
        if len(pts) < 4:
            rows.append({"mode": mode, "lost": True})
            print("trial %d %-6s lost" % (trial, mode))
            continue
        side = np.array([-d[1], d[0], 0.0])
        along = [float((p - who["pos"]) @ d) for p in pts]
        row = {"mode": mode, "speed_before": round(speed, 3),
               "closest_to_spot_m": round(min(float(np.linalg.norm((p - spot)[:2])) for p in pts), 2),
               "stray_m": round(max(abs(float((p - who["pos"]) @ side)) for p in pts), 2),
               "passed_spot": bool(max(along) > a.lead + 0.5),
               "speed_m_s": round(float(np.linalg.norm((pts[-1] - pts[0])[:2])) / max(0.1, times[-1] - times[0]), 3),
               "points": len(pts)}
        rows.append(row)
        print("trial %d %-6s walking %.2f m/s -> %s" % (trial, mode, speed, json.dumps({k: v for k, v in row.items() if k != "mode"})))
    return rows


def summarise(start, direction, spot, path):
    pts = [np.array(p) for p in path if p is not None]
    if len(pts) < 2:
        return {"lost": True}
    side = np.array([-direction[1], direction[0], 0.0])
    stray = max(abs(float((p - start) @ side)) for p in pts)
    closest = min(float(np.linalg.norm((p - spot)[:2])) for p in pts)
    dist = sum(float(np.linalg.norm((pts[i + 1] - pts[i])[:2])) for i in range(len(pts) - 1))
    return {"closest_m": round(closest, 3), "stray_m": round(stray, 3),
            "speed_m_s": round(dist / (STEP * 3 * (len(pts) - 1)), 3), "points": len(pts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="witcher3-hierarch-square-centre-001")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--far", type=float, default=15.0)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--running", action="store_true", help="the world running (see running_trials)")
    ap.add_argument("--lead", type=float, default=4.0, help="with --running: metres ahead of the walker")
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    centre = loc["position"]
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "npc_influence")
    os.makedirs(out, exist_ok=True)
    s.close_menu()
    s.cmd("savelock", 1)       # nothing of this into the saves (a probe autosaved a broken state, 2026-11-23)
    s.cmd("hud", 0)
    s.cmd("unfreeze")
    s.cmd("teleport", centre[0], centre[1], centre[2] + 0.1, loc.get("facing_deg", 0.0))
    time.sleep(10)
    rows = []
    if a.running:
        try:
            rows = running_trials(s, centre, loc, a)
        finally:
            s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
            s.cmd("hide", 0)
            s.cmd("hud", 1)
            s.cmd("savelock", 0)
        for mode in ("none", "ghost", "hidden"):
            rs = [r for r in rows if r["mode"] == mode and not r.get("lost")]
            if rs:
                print("%-6s %d trials: passed the spot %d, speed %.2f m/s mean (before %.2f), closest to the spot %.2f m mean, stray %.2f m mean"
                      % (mode, len(rs), sum(r["passed_spot"] for r in rs), np.mean([r["speed_m_s"] for r in rs]),
                         np.mean([r["speed_before"] for r in rs]), np.mean([r["closest_to_spot_m"] for r in rs]),
                         np.mean([r["stray_m"] for r in rs])))
        with open(os.path.join(out, "report_running.json"), "w") as f:
            json.dump(rows, f, indent=1)
        return
    try:
        for trial in range(a.trials * 2):
            mode = MODES[trial % len(MODES)]
            found = None
            for _ in range(20):
                found = find_walker(s, centre)
                if found:
                    break
                time.sleep(1.0)
            if not found:
                print("trial %d: nobody walking near the spot" % trial)
                continue
            who, speed, d = found
            seen = time.time()
            # hold the world first, so the walker is still short of the spot when the player gets there
            s.cmd("hide", 1)
            s.cmd("freeze")
            guess = who["pos"] + speed * d * (time.time() - seen)
            near = people(s, guess, 4.0)
            if not near:
                s.cmd("unfreeze")
                print("trial %d: lost the walker while holding the world" % trial)
                continue
            who = min(near, key=lambda p: float(np.linalg.norm((p["pos"] - guess)[:2])))
            # still walking through the hold? (the nearest person to where the walker should be was
            # sometimes someone standing: the baseline showed "walkers" at 0 m/s, 2026-11-23)
            frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
            first = track(s, ex, who, 3, frame_s=frame_s)
            if not first or first[0] is None or float(np.linalg.norm((np.array(first[0]) - who["pos"])[:2])) < 0.06:
                s.cmd("unfreeze")
                print("trial %d: the person found is not walking after the hold; skipped" % trial)
                continue
            d_now = np.array(first[0]) - who["pos"]
            d_now[2] = 0.0
            d = d_now / float(np.linalg.norm(d_now))
            who = dict(who, pos=np.array(first[0]))
            spot = who["pos"] + 2.0 * d
            far = None
            if mode == "none":            # the baseline: he stays where he is
                pass
            elif mode == "hidden":        # as takes did first: invisible, standing at the spot
                s.cmd("teleport", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05, 0)
            elif mode == "ghost":         # invisible, collisions and physical movement off, at the spot
                s.cmd("park", float(spot[0]), float(spot[1]), float(spot[2]) + 0.05)
            else:                         # side: the same, a.far metres to the side of the spot
                side = np.array([-d[1], d[0], 0.0])
                far = spot + a.far * side
                s.cmd("park", float(far[0]), float(far[1]), float(far[2]) + 0.05)
            s.cmd("pose", float(spot[0]) - 6 * d[0], float(spot[1]) - 6 * d[1], float(spot[2]) + 2.5, -15,
                  math.degrees(math.atan2(-d[0], d[1])), 0, 60)
            before = people(s, spot, 15.0)
            moving_before = len(before)
            frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
            path = track(s, ex, who, int(round(a.seconds / STEP)), frame_s=frame_s)
            placed = s.state().get("player", "0,0,0")
            after = people(s, spot, 15.0)
            st = s.state()
            s.cmd("unfreeze")
            s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
            target = far if mode == "side" else spot if mode != "none" else np.array(vec(placed))
            row = dict(summarise(who["pos"], d, spot, path), mode=mode, name=who["name"], speed_before=round(speed, 3),
                       player=placed, player_off_target_m=round(float(np.linalg.norm((np.array(vec(placed)) - target)[:2])), 2),
                       people_within_15m=[moving_before, len(after)])
            rows.append(row)
            print("trial %d %-7s walking %.2f m/s -> %s, people within 15 m %d -> %d" % (
                trial, mode, speed, {k: row[k] for k in row if k in ("closest_m", "stray_m", "speed_m_s", "lost", "points", "player_off_target_m")},
                moving_before, len(after)))
            s.cmd("teleport", centre[0], centre[1], centre[2] + 0.1, loc.get("facing_deg", 0.0))
            time.sleep(4)
    finally:
        s.cmd("unfreeze")
        s.cmd("unpark", centre[0], centre[1], centre[2] + 0.1, 0)
        s.cmd("hide", 0)
        s.cmd("hud", 1)
        s.cmd("savelock", 0)
    for mode in MODES:
        rs = [r for r in rows if r["mode"] == mode and not r.get("lost")]
        if rs:
            print("%-8s %d trials: sideways stray %.2f m mean, speed %.2f m/s mean (before: %.2f), closest %.2f m"
                  % (mode, len(rs), np.mean([r["stray_m"] for r in rs]), np.mean([r["speed_m_s"] for r in rs]),
                     np.mean([r["speed_before"] for r in rs]), np.mean([r["closest_m"] for r in rs])))
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(rows, f, indent=1)
    print("report:", os.path.join(out, "report.json"))


if __name__ == "__main__":
    main()
