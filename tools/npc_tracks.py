"""People, animals and vehicles near the rig through a take's clip frames, and what in their motion
is implausible. Game-agnostic: reads a take's npc_tracks.jsonl (written by the take loop from the
adapter's obstacles() at every clip frame, since 2026-11-25) and take.json (fps, the hidden player's
parked spot). For the QC loop's NPC categories (docs/QC_LOOP.md); runs on a round's data alone.

    uv run --project . python tools/npc_tracks.py <take folder> [--out DIR] [--fps 30]

Tracks are linked by position (the adapters' ids are list positions, not stable): each clip frame
the closest pairs of the same kind within a gate per step (human 0.5 m, animal 1 m, vehicle 3 m),
then a thing ending and one starting within 15 m in the same step are joined as a jump. Flags, per
track:

- teleport: a step faster than the kind can move (human 9 m/s, animal 20 m/s, vehicle 60 m/s);
- jerk: the speed changing by more than a kind's limit in one step (human 4 m/s, animal 8, vehicle
  10 per 1/30 s), e.g. a walker stopping dead or starting at full speed;
- stop: moving above 0.8 m/s and then still (under 0.1 m/s) for the rest of the take;
- lift: a person or animal rising more than 0.35 m from its lowest height, or a vehicle more than
  0.5 m (flung, flying, a cart lifting off);
- turn: a moving person turning more than 90 degrees in one step;
- pop: appearing or vanishing inside the rig's reach between the first and last clip frame (not
  at the reach's edge);
- player: coming within 2 m of the hidden player's parked spot (take.json subject_position), and
  how its path bends there: people must not react to the player (step aside, stop, turn).

Per track also headings_deg (from the box's forward axis, per clip frame) and facing_off_player_deg
(0 = facing the hidden player's spot): people turning toward an empty spot show there.

And per shot (with the take's shots.json): the nearest person, animal or vehicle in front of each
camera, inside its view; under CLOSE_M (1.5 m) it is listed in close_to_camera: a stranger filling
the picture at lens distance (GTA V Alamo Sea, round 1).

Writes <out>/npc_tracks.json (tracks, per-step speeds, flags) and npc_tracks_map.png (a top-down
map of the paths, flagged steps in red, the rig centre and the player's spot), and prints a summary.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

LIMITS = {  # kind: (max speed m/s, max speed change per step m/s, max rise m)
    "human": (9.0, 4.0, 0.35), "animal": (20.0, 8.0, 0.35), "vehicle": (60.0, 10.0, 0.5)}
GATE = {"human": 0.5, "animal": 1.0, "vehicle": 3.0}   # metres per step: linked as one thing moving
JUMP_M = 15.0     # a track ending and one starting this near in the same step: one thing that jumped
CLOSE_M = 1.5     # a thing nearer than this to a camera, in its view, is listed


def load(take):
    rows = []
    with open(os.path.join(take, "npc_tracks.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["frame"])
    t = {}
    p = os.path.join(take, "take.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            t = json.load(f)
    return rows, t


def link(rows):
    """{track key: [(frame, thing)]}, linked by position: the adapters' ids are each call's list
    positions, not stable (every adapter, 2026-11-25), so they are not used. Each clip frame, the
    closest pairs of the same kind within GATE go first; a track that ends and one that starts in the
    same step, same kind, within JUMP_M, are one thing that jumped (flagged as a teleport)."""
    tracks, live = {}, {}      # live: key -> (frame, thing) of tracks seen in the frame before
    nxt = 0
    for r in rows:
        f = r["frame"]
        things = list(r["things"])
        pairs = []
        for k, (fr, prev) in live.items():
            if fr != f - 1:
                continue
            for j, th in enumerate(things):
                if th.get("kind") != prev.get("kind"):
                    continue
                d = float(np.linalg.norm(np.asarray(th["center"], float) - np.asarray(prev["center"], float)))
                pairs.append((d, k, j))
        pairs.sort()
        used_k, used_j, new_live = set(), set(), {}
        for d, k, j in pairs:      # within the gate first, then the jumps
            if k in used_k or j in used_j or d > GATE.get(things[j].get("kind"), 2.0):
                continue
            used_k.add(k); used_j.add(j)
            tracks[k].append((f, things[j])); new_live[k] = (f, things[j])
        for d, k, j in pairs:
            if k in used_k or j in used_j or d > JUMP_M:
                continue
            used_k.add(k); used_j.add(j)
            tracks[k].append((f, dict(things[j], jumped_m=round(d, 2)))); new_live[k] = (f, things[j])
        for j, th in enumerate(things):
            if j not in used_j:
                key = ("n", nxt)
                nxt += 1
                tracks[key] = [(f, th)]
                new_live[key] = (f, th)
        live = new_live
    return tracks


def close_to_cameras(take, rows):
    """[{clip_frame, camera, kind, id, distance_m}] for things in a camera's view nearer than CLOSE_M
    (distance from the lens to the box's centre minus its largest horizontal half extent)."""
    p = os.path.join(take, "shots.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        shots = json.load(f)
    by_frame = {r["frame"]: r["things"] for r in rows}
    out = []
    for st in shots.get("steps", []):
        things = by_frame.get(st["frame"])
        if not things:
            continue
        for sh in st["shots"]:
            pos, fwd = np.asarray(sh["pos"], float), np.asarray(sh["fwd"], float)
            # the horizontal half angle of a 16:9 picture, and a little more (a body's edge in the picture)
            half = math.degrees(math.atan(math.tan(math.radians(float(sh.get("vfov_deg") or 60) / 2)) * 16 / 9))
            cos_half = math.cos(math.radians(min(85.0, half + 10)))
            best = None
            for th in things:
                v = np.asarray(th["center"], float) - pos
                dist = float(np.linalg.norm(v))
                if dist < 1e-6 or (v @ fwd) / dist < cos_half:
                    continue
                d = max(0.0, dist - max(th.get("half", [0.3, 0.3, 0.9])[:2]))
                if best is None or d < best[0]:
                    best = (d, th)
            if best and best[0] < CLOSE_M:
                out.append({"clip_frame": st["frame"], "camera": sh["name"].split("_", 1)[1].rsplit("_", 1)[0],
                            "kind": best[1].get("kind"), "id": best[1].get("id"), "distance_m": round(best[0], 2)})
    return out


def analyse(take, fps=None):
    rows, t = load(take)
    if not rows:
        return {"take": take, "error": "no npc_tracks.jsonl rows"}
    fps = fps or 30.0
    frames = [r["frame"] for r in rows]
    first, lastf = frames[0], frames[-1]
    player = t.get("subject_position")
    centre = ((t.get("placement") or {}).get("rig_center_world")) if isinstance(t.get("placement"), dict) else None
    out = []
    for key, pts in link(rows).items():
        kind = pts[0][1].get("kind", "human")
        vmax, dvmax, rise = LIMITS.get(kind, LIMITS["human"])
        c = np.array([p[1]["center"] for p in pts], float)
        fr = [p[0] for p in pts]
        flags = []
        speeds = []
        for i in range(1, len(pts)):
            dt = (fr[i] - fr[i - 1]) / fps
            v = float(np.linalg.norm(c[i, :2] - c[i - 1, :2]) / dt) if dt > 0 else 0.0
            speeds.append(round(v, 3))
            if v > vmax:
                flags.append({"flag": "teleport", "frame": fr[i], "speed_m_s": round(v, 2)})
        for i in range(1, len(speeds)):
            if abs(speeds[i] - speeds[i - 1]) > dvmax:
                flags.append({"flag": "jerk", "frame": fr[i + 1], "from_m_s": speeds[i - 1], "to_m_s": speeds[i]})
        for i in range(len(speeds) - 1):
            if speeds[i] > 0.8 and all(s < 0.1 for s in speeds[i + 1:]) and len(speeds) - i > 3:
                flags.append({"flag": "stop", "frame": fr[i + 1], "was_m_s": speeds[i]})
                break
        z = c[:, 2]
        if len(z) > 1 and float(z.max() - z.min()) > rise:
            flags.append({"flag": "lift", "frame": fr[int(np.argmax(z))], "rise_m": round(float(z.max() - z.min()), 2)})
        if kind == "human":
            for i in range(2, len(pts)):
                a, b = c[i - 1, :2] - c[i - 2, :2], c[i, :2] - c[i - 1, :2]
                if np.linalg.norm(a) * fps > 0.5 and np.linalg.norm(b) * fps > 0.5:
                    ang = math.degrees(math.acos(float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))))
                    if ang > 90:
                        flags.append({"flag": "turn", "frame": fr[i], "degrees": round(ang, 1)})
        if fr[0] > first:
            flags.append({"flag": "pop", "frame": fr[0], "what": "appears"})
        if fr[-1] < lastf:
            flags.append({"flag": "pop", "frame": fr[-1] + 1, "what": "vanishes"})
        # heading per clip frame from the box's forward axis (degrees, counter-clockwise from +x), and
        # how far it is from facing the hidden player's spot
        headings, off_player = [], []
        for fr_i, th in pts:
            ax = th.get("axes")
            if ax and len(ax) > 1:
                fx, fy = float(ax[1][0]), float(ax[1][1])
                headings.append(round(math.degrees(math.atan2(fy, fx)), 1))
                if player:
                    to = np.asarray(player[:2], float) - np.asarray(th["center"][:2], float)
                    if np.linalg.norm(to) > 1e-6 and math.hypot(fx, fy) > 1e-6:
                        cosv = (fx * to[0] + fy * to[1]) / (math.hypot(fx, fy) * np.linalg.norm(to))
                        off_player.append(round(math.degrees(math.acos(max(-1.0, min(1.0, cosv)))), 1))
        near = None
        if player:
            d = np.linalg.norm(c[:, :2] - np.asarray(player[:2], float), axis=1)
            near = round(float(d.min()), 2)
            if d.min() < 2.0:
                flags.append({"flag": "player", "frame": fr[int(np.argmin(d))], "closest_m": near})
        out.append({"track": "%s:%s" % key, "kind": kind, "owned": bool(pts[0][1].get("owned")), "frames": [fr[0], fr[-1]],
                    "path_m": round(float(np.linalg.norm(np.diff(c[:, :2], axis=0), axis=1).sum()) if len(c) > 1 else 0.0, 2),
                    "mean_speed_m_s": round(float(np.mean(speeds)), 2) if speeds else 0.0,
                    "closest_to_player_m": near, "speeds": speeds, "flags": flags,
                    "headings_deg": headings, "facing_off_player_deg": off_player,
                    "path": [[round(float(x), 2), round(float(y), 2)] for x, y in c[:, :2]]})
    counts = {}
    for tr in out:
        for f in tr["flags"]:
            counts[f["flag"]] = counts.get(f["flag"], 0) + 1
    close = close_to_cameras(take, rows)
    if close:
        counts["close_to_camera"] = len(close)
    return {"take": os.path.basename(os.path.normpath(take)), "clip_frames": [first, lastf], "fps": fps,
            "player": player, "centre": centre, "tracks": len(out), "flag_counts": counts, "close_to_camera": close,
            "by_track": sorted(out, key=lambda tr: -len(tr["flags"]))}


def draw(rep, path):
    from PIL import Image, ImageDraw
    pts = [p for tr in rep["by_track"] for p in tr["path"]]
    if rep.get("player"):
        pts.append(rep["player"][:2])
    if not pts:
        return
    a = np.array(pts, float)
    lo, hi = a.min(axis=0) - 3, a.max(axis=0) + 3
    S = 900
    scale = S / max(float((hi - lo).max()), 1.0)
    im = Image.new("RGB", (S, S), (18, 18, 22))
    dr = ImageDraw.Draw(im)
    xy = lambda p: ((p[0] - lo[0]) * scale, S - (p[1] - lo[1]) * scale)  # noqa: E731
    colours = {"human": (120, 200, 255), "animal": (140, 230, 140), "vehicle": (240, 200, 90)}
    for tr in rep["by_track"]:
        line = [xy(p) for p in tr["path"]]
        if len(line) > 1:
            dr.line(line, fill=colours.get(tr["kind"], (200, 200, 200)), width=2)
        if line:
            dr.ellipse([line[0][0] - 3, line[0][1] - 3, line[0][0] + 3, line[0][1] + 3], outline=(255, 255, 255))
        bad = {f["frame"] for f in tr["flags"]}
        for p, fr in zip(tr["path"], range(tr["frames"][0], tr["frames"][1] + 1)):
            if fr in bad:
                x, y = xy(p)
                dr.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 40, 40), width=2)
    if rep.get("player"):
        x, y = xy(rep["player"])
        dr.rectangle([x - 6, y - 6, x + 6, y + 6], outline=(255, 0, 255), width=3)
        dr.text((x + 8, y - 6), "player (hidden)", fill=(255, 0, 255))
    dr.text((8, 8), "%s: %d tracks, flags %s (1 px = %.2f m)" % (rep["take"], rep["tracks"], rep["flag_counts"], 1 / scale),
            fill=(230, 230, 230))
    im.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("take")
    ap.add_argument("--out")
    ap.add_argument("--fps", type=float, default=30.0)
    a = ap.parse_args(argv)
    rep = analyse(a.take, a.fps)
    out = a.out or os.path.join(a.take, "qc")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "npc_tracks.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    if "error" not in rep:
        draw(rep, os.path.join(out, "npc_tracks_map.png"))
        print(json.dumps({k: rep[k] for k in ("take", "clip_frames", "tracks", "flag_counts", "player")}))
        for tr in rep["by_track"][:15]:
            if tr["flags"]:
                print("  %-14s %-7s frames %s, %.1f m, mean %.2f m/s: %s" % (
                    tr["track"], tr["kind"], tr["frames"], tr["path_m"], tr["mean_speed_m_s"],
                    "; ".join("%s@%s" % (f["flag"], f["frame"]) for f in tr["flags"][:6])))
    else:
        print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
