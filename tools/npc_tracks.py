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
- pop: appearing or vanishing between the first and last clip frame more than EDGE_M inside the
  reach of the obstacle list (the take's cameras' reach around the rig centre + 6 m, as the take loop
  asks for); at the edge it is someone walking in or out, listed in events but not flagged;
- player: coming within 2 m of the hidden player's parked spot (take.json subject_position), and
  how its path bends there: people must not react to the player (step aside, stop, turn);
- overlap: two people (or animals) whose centres stand under OVERLAP_M apart in a clip frame, bodies
  inside each other (The Witcher 3's crowd spawned stacked with the player parked away, QC round 6);
  every such pair and frame is listed in overlaps.

Per track also headings_deg (from the box's forward axis, per clip frame) and facing_off_player_deg
(0 = facing the hidden player's spot): people turning toward an empty spot show there.

And per shot (with the take's shots.json): the nearest person, animal or vehicle in front of each
camera, inside its view; under CLOSE_M (1.5 m) it is listed in close_to_camera: a stranger filling
the picture at lens distance (GTA V Alamo Sea, round 1).

And per clip frame (events): who entered or left the list, with the distance from the rig centre
and the reach (QC round 5 asked for it: a walker entering at 8.8 m of an 8.7 m reach is not a spawn).

    --draw near_temporal_00[,near_moving]   the tracks drawn onto those cameras' frames: each box
        projected into the picture (its corners' outline), the track's name and distance beside it,
        entering and leaving in yellow, flagged steps in red; one image per clip frame under
        <out>/npc_tracks_<camera>/ and a contact sheet npc_tracks_<camera>.jpg (--sheet-only: the sheet)

Writes <out>/npc_tracks.json (tracks, per-step speeds, flags, events) and npc_tracks_map.png (a
top-down map of the paths, flagged steps in red, the rig centre and the player's spot), and prints a
summary.
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
EDGE_M = 1.0      # appearing or vanishing this near the reach's edge: walking in or out, not a pop
OVERLAP_M = 0.5   # two people's centres nearer than this (horizontally, at similar heights): inside each other
REACH_PAD_M = 6.0 # the take loop's reach: its cameras' reach around the rig centre + this (capture/runner.py)


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


def rig_reach(take):
    """(rig centre, reach in metres) from the take's shots.json, as the take loop computes them, or
    (None, None)."""
    p = os.path.join(take, "shots.json")
    if not os.path.exists(p):
        return None, None
    with open(p, encoding="utf-8") as f:
        shots = json.load(f)
    centre = (shots.get("placement") or {}).get("rig_center_world")
    pos = [s["pos"] for st in shots.get("steps", []) for s in st["shots"]]
    if centre is None or not pos:
        return None, None
    d = np.linalg.norm(np.asarray(pos, float) - np.asarray(centre, float), axis=1)
    return [float(v) for v in centre], float(d.max()) + REACH_PAD_M


def analyse(take, fps=None):
    rows, t = load(take)
    if not rows:
        return {"take": take, "error": "no npc_tracks.jsonl rows"}
    fps = fps or 30.0
    frames = [r["frame"] for r in rows]
    first, lastf = frames[0], frames[-1]
    player = t.get("subject_position")
    centre, reach = rig_reach(take)
    events = []

    def where(th):
        if centre is None:
            return None, "unknown"
        d = float(np.linalg.norm(np.asarray(th["center"], float) - np.asarray(centre, float)))
        return round(d, 2), ("edge" if d > reach - EDGE_M else "inside")

    out = []
    linked = link(rows)
    name_of = {}
    for key, pts in linked.items():
        for fr_i, th in pts:
            name_of[(fr_i, tuple(round(float(v), 3) for v in th["center"]))] = "%s:%s" % key
    overlaps = []
    for r in rows:
        bodies = [th for th in r["things"] if th.get("kind") in ("human", "animal")]
        for i in range(len(bodies)):
            for j in range(i + 1, len(bodies)):
                a, b = np.asarray(bodies[i]["center"], float), np.asarray(bodies[j]["center"], float)
                dh = float(np.linalg.norm(a[:2] - b[:2]))
                if dh < OVERLAP_M and abs(a[2] - b[2]) < 1.0:
                    overlaps.append({"frame": r["frame"], "distance_m": round(dh, 3), "tracks": [
                        name_of.get((r["frame"], tuple(round(float(v), 3) for v in x["center"])), "?") for x in (bodies[i], bodies[j])]})
    first_overlap = {}
    for o in overlaps:
        for t_ in o["tracks"]:
            first_overlap.setdefault(t_, o)
    for key, pts in linked.items():
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
            d, at = where(pts[0][1])
            events.append({"frame": fr[0], "track": "%s:%s" % key, "kind": kind, "what": "enters" if at == "edge" else "appears",
                           "distance_m": d, "reach_m": round(reach, 2) if reach else None, "at": at})
            if at != "edge":
                flags.append({"flag": "pop", "frame": fr[0], "what": "appears", "distance_m": d})
        if fr[-1] < lastf:
            d, at = where(pts[-1][1])
            events.append({"frame": fr[-1] + 1, "track": "%s:%s" % key, "kind": kind, "what": "leaves" if at == "edge" else "vanishes",
                           "distance_m": d, "reach_m": round(reach, 2) if reach else None, "at": at})
            if at != "edge":
                flags.append({"flag": "pop", "frame": fr[-1] + 1, "what": "vanishes", "distance_m": d})
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
        ov = first_overlap.get("%s:%s" % key)
        if ov:
            flags.append({"flag": "overlap", "frame": ov["frame"], "with": [t_ for t_ in ov["tracks"] if t_ != "%s:%s" % key],
                          "distance_m": ov["distance_m"],
                          "frames": sorted({o["frame"] for o in overlaps if "%s:%s" % key in o["tracks"]})})
        near = None
        if player:
            d = np.linalg.norm(c[:, :2] - np.asarray(player[:2], float), axis=1)
            near = round(float(d.min()), 2)
            if d.min() < 2.0:
                flags.append({"flag": "player", "frame": fr[int(np.argmin(d))], "closest_m": near})
        out.append({"track": "%s:%s" % key, "kind": kind, "owned": bool(pts[0][1].get("owned")), "frames": [fr[0], fr[-1]],
                    "distance_from_centre_m": [where(pts[0][1])[0], where(pts[-1][1])[0]],
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
            "player": player, "centre": centre, "reach_m": round(reach, 2) if reach else None, "tracks": len(out),
            "flag_counts": counts, "close_to_camera": close, "events": sorted(events, key=lambda e: (e["frame"], e["track"])),
            "overlaps": overlaps,
            "by_track": sorted(out, key=lambda tr: -len(tr["flags"]))}


def keys_by_thing(rows):
    """{(clip frame, rounded centre): track name} for drawing."""
    out = {}
    for key, pts in link(rows).items():
        for fr, th in pts:
            out[(fr, tuple(round(float(v), 3) for v in th["center"]))] = "%s:%s" % key
    return out


def draw_on_frames(take, rep, camera, out_dir, frames=True):
    """Each clip frame of one camera with every listed box projected into it (the outline of its
    corners), the track's name and distance from the lens beside it. Returns the contact sheet's path."""
    from PIL import Image, ImageDraw, ImageFont
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from take_frames import frame_file
    rows, _ = load(take)
    names = keys_by_thing(rows)
    with open(os.path.join(take, "shots.json"), encoding="utf-8") as f:
        shots = json.load(f)
    by_frame = {r["frame"]: r["things"] for r in rows}
    files = {}
    with open(os.path.join(take, "capture_log.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("accepted"):
                files[r["id"]] = r["file"]
    bad = {(tr["track"], fl["frame"]) for tr in rep["by_track"] for fl in tr["flags"]}
    moving = {(e["track"], e["frame"]) for e in rep.get("events", [])}
    d = os.path.join(out_dir, "npc_tracks_%s" % camera)
    if frames:
        os.makedirs(d, exist_ok=True)
    thumbs = []
    for st in shots["steps"]:
        sh = next((s for s in st["shots"] if s["name"].split("_", 1)[1].rsplit("_", 1)[0] == camera), None)
        if sh is None or sh["id"] not in files:
            continue
        p = frame_file(take, files[sh["id"]])
        if not p:
            continue
        im = Image.open(p).convert("RGB")
        W, H = im.size
        dr = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default(size=max(14, H // 36))
        except TypeError:          # Pillow before 10.1
            font = ImageFont.load_default()
        pos = np.asarray(sh["pos"], float)
        R, U, F = (np.asarray(sh[k], float) for k in ("right", "up", "fwd"))
        foc = (H / 2) / math.tan(math.radians(float(sh["vfov_deg"]) / 2))

        def proj(q):
            v = np.asarray(q, float) - pos
            z = float(v @ F)
            if z < 0.05:
                return None
            return (W / 2 + float(v @ R) / z * foc, H / 2 - float(v @ U) / z * foc)

        fr = st["frame"]
        for th in by_frame.get(fr, []):
            ax = np.asarray(th.get("axes") or np.eye(3), float)
            hf = np.asarray(th.get("half") or [0.3, 0.3, 0.9], float)
            c = np.asarray(th["center"], float)
            corners = [c + sum(s * hf[i] * ax[i] for i, s in enumerate(sg)) for sg in
                       [(a, b, e) for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)]]
            pts = [q for q in (proj(q) for q in corners) if q]
            if len(pts) < 8:
                continue
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            if max(xs) < 0 or min(xs) > W or max(ys) < 0 or min(ys) > H:
                continue
            name = names.get((fr, tuple(round(float(v), 3) for v in th["center"])), "?")
            col = (255, 60, 60) if (name, fr) in bad else (255, 220, 0) if (name, fr) in moving else (90, 220, 255)
            dr.rectangle([min(xs), min(ys), max(xs), max(ys)], outline=col, width=max(2, W // 640))
            dr.text((min(max(min(xs), 0), W - W // 5) + 4, min(max(min(ys) - H // 30, 0), H - H // 20)), "%s %s %.1f m" % (name, th.get("kind", ""), float(np.linalg.norm(c - pos))),
                    fill=col, font=font)
        dr.text((8, 8), "%s clip frame %d" % (camera, fr), fill=(255, 255, 0), font=font)
        if frames:
            im.save(os.path.join(d, "frame_%02d.jpg" % fr), quality=88)
        thumbs.append(im.resize((480, int(480 * H / W))))
    if not thumbs:
        return None
    cols = 6
    tw, th_ = thumbs[0].size
    sheet = Image.new("RGB", (tw * cols, th_ * ((len(thumbs) + cols - 1) // cols)))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * th_))
    path = os.path.join(out_dir, "npc_tracks_%s.jpg" % camera)
    sheet.save(path, quality=85)
    return path


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
    ap.add_argument("--draw", help="cameras to draw the tracks onto, comma-separated (near_temporal_00,near_moving)")
    ap.add_argument("--sheet-only", action="store_true", help="with --draw: the contact sheet alone, not every frame")
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
        for e in rep["events"]:
            print("  clip frame %2d: %-8s %s %-7s at %s m of a %s m reach (%s)" % (
                e["frame"], e["what"], e["track"], e["kind"], e["distance_m"], e["reach_m"], e["at"]))
        for cam in (a.draw or "").split(","):
            if cam:
                print("drew", draw_on_frames(a.take, rep, cam.strip(), out, frames=not a.sheet_only))
    else:
        print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
