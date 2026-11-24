"""The take loop, against the Adapter interface.

    go to the location -> set the clock -> place the rig on the ground -> shot list
    -> hide the subject -> freeze -> for each clip frame: capture every shot, step 1/fps
    -> unfreeze -> show the subject

Every shot is checked twice: the adapter's health (focus, subject hidden, paused, ...)
and the picture itself (capture/checks.py). A failed shot gets adapter.recover() and is
captured again, but only while the frozen instant is unchanged (adapter.instant()); a
take whose instant moved cannot be continued and fails.

Moving things in the cameras (adapters with the "obstacles" capability, capture/obstacles.py):
at the start of the take, frozen at its first clip frame, anything holding a camera position of
this take is deleted; nothing is deleted after that. Before each clip frame's shots, a camera of
that frame inside or right against something raises Retake while fewer than retake_before of
the shots are captured (the worker starts the take again); after that the take is finished
and the shots are marked in the capture log and take.json.
"""
import json
import os
import shutil
import time
import uuid

import numpy as np

from . import obstacles
from .checks import PictureCheck
from .placement import Placement
from .shots import build, select_cameras, subset
from .util import now_iso, write_json


class TakeFailed(RuntimeError):
    pass


class Retake(RuntimeError):
    """The take must be captured again from the start (a camera ended up inside something)."""

    def __init__(self, reason, progress):
        super().__init__("%s (at %.0f%% of the shots)" % (reason, 100 * progress))
        self.reason, self.progress = reason, progress


DEFAULT_SETTINGS = {
    "clock": "12:00",        # time of day; None keeps the game's
    "last_frame": 0,         # 0 = every clip frame (a sample stops earlier)
    "sweep_stride": 1,       # keep every n-th pose of the frozen sweeps (samples)
    "cameras": None,         # rig camera name patterns to capture (None = all)
    "shot_attempts": 3,      # captures of one shot before the take fails
    "keep_raw": True,        # keep raw frames after packaging
    "obstacle_check": True,  # clear and check moving things in the cameras (adapter capability)
    "obstacle_margin": 0.15, # metres around a person/animal/vehicle box that count as inside
    "retake_before": 2 / 3,  # a camera inside something before this share of shots: retake
    "max_retakes": 3,        # retakes of one job before it fails
    "qc": "flag",            # the rig provider's check of the package: flag (record), fail, off
    "adapter": {},           # passed to the adapter (e.g. settle ticks)
}


def merged_settings(settings):
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in (settings or {}).items() if v is not None or k == "clock"})
    return out


def run_take(adapter, job, rig, rig_path, take_dir, log=print):
    """Captures one take into take_dir. Returns take.json's content."""
    settings = merged_settings(job.get("settings"))
    location = job["location"]
    raw_dir = os.path.join(take_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    if os.listdir(raw_dir):
        raise TakeFailed(raw_dir + " is not empty")

    t_start = time.time()
    take = {
        "schema": "capture_take/v1",
        "job_id": job.get("id"), "game": adapter.name, "location": location,
        "rig_source": job.get("rig"), "rig_file": os.path.abspath(rig_path), "rig": rig.get("rig"),
        "settings": settings,
        # One id per run, never reused: no two runs share a world state until the adapter
        # can snapshot and restore it (BACKLOG.md: shot reuse).
        "world_state_id": uuid.uuid4().hex,
        "started": now_iso(), "status": "running",
    }
    write_json(os.path.join(take_dir, "take.json"), take)

    log("going to %s" % location["id"])
    adapter.enter_place(location.get("place"))
    adapter.go_to(location["position"], location.get("facing_deg", 0.0))
    if settings.get("clock"):
        take["clock"] = adapter.set_clock(settings["clock"])
    origin = adapter.ground_point(location["position"])
    placement = Placement(origin, adapter.rig_rotation(location.get("facing_deg", 0.0)))
    shots = select_cameras(subset(build(rig, placement), settings["last_frame"], settings["sweep_stride"]),
                           settings.get("cameras"))
    write_json(os.path.join(take_dir, "shots.json"), shots, indent=None)
    total = shots["n_shots"]
    log("rig origin at %s; %d clip frames, %d shots, %d camera frames" % (
        ", ".join("%.3f" % v for v in origin), len(shots["steps"]), total, shots["n_camera_frames"]))
    take.update({"placement": shots["placement"], "n_shots": total, "n_camera_frames": shots["n_camera_frames"],
                 "sample": shots.get("sample")})

    if hasattr(adapter, "prepare_take"):   # optional: what an adapter must set before the world is held
        adapter.prepare_take(shots)
    check = PictureCheck()
    fps = float(shots.get("fps") or 30)
    cap_log = open(os.path.join(take_dir, "capture_log.jsonl"), "w", encoding="utf-8")
    steps_log = open(os.path.join(take_dir, "steps.jsonl"), "w", encoding="utf-8")
    settle = settings["adapter"].get("settle")
    done = retries = 0
    t_shots = None
    use_obstacles = settings.get("obstacle_check") and "obstacles" in adapter.capabilities
    margin = float(settings.get("obstacle_margin") or 0.0)
    all_pos = np.array([s["pos"] for st in shots["steps"] for s in st["shots"]])
    centre = shots["placement"]["rig_center_world"]
    reach_m = obstacles.reach(all_pos, centre) + 6.0  # + the size of a wagon and its horses
    take["obstructions"] = []
    try:
        adapter.hide_subject(True)
        first = shots["steps"][0]["shots"][0]
        adapter.begin_frozen(first)
        take["render"] = adapter.render_settings()
        if use_obstacles:
            _clear_cameras(adapter, all_pos, centre, reach_m, margin, log, take)
        # Optional (adapter attribute preroll_steps, 0 by default, so other games are unchanged):
        # time steps between holding the world and clip frame 1, for a game whose picture changes
        # once on its first steps (RDR2's shadows, docs/VISUAL_CHECKS.md D3)
        preroll = int(getattr(adapter, "preroll_steps", 0) or 0) if len(shots["steps"]) > 1 else 0
        for _ in range(preroll):
            adapter.advance(1.0 / fps)
        if preroll:
            take["preroll_steps"] = preroll
        t_shots = time.time()
        prev = None
        for st in shots["steps"]:
            if prev is not None:
                for _ in range(st["frame"] - prev):
                    r = adapter.advance(1.0 / fps)
                    steps_log.write(json.dumps(dict(r, to_frame=st["frame"])) + "\n")
            prev = st["frame"]
            instant = adapter.instant()
            blocked = {}
            if use_obstacles:
                blocked = _check_frame(adapter, st, centre, reach_m, margin)
                if blocked:
                    progress = done / total
                    what = sorted({b["kind"] for b in blocked.values()})
                    if progress < float(settings.get("retake_before", 2 / 3)):
                        raise Retake("clip frame %d: %d cameras inside or against a %s" % (
                            st["frame"], len(blocked), "/".join(what)), progress)
                    take["obstructions"].append({"frame": st["frame"], "shots": sorted(blocked),
                                                 "kinds": what, "progress": round(progress, 3)})
                    log("clip frame %d: %d cameras inside or against a %s; past %.0f%%, finishing the take" % (
                        st["frame"], len(blocked), "/".join(what), 100 * progress))
            for shot in st["shots"]:
                retries += _capture_shot(adapter, shot, st["frame"], raw_dir, take_dir, settle, check, instant,
                                         settings["shot_attempts"], cap_log, log, blocked.get(shot["id"]))
                done += 1
                if done % 250 == 0 or done == total:
                    el = time.time() - t_shots
                    log("%d/%d shots, %.2f s per shot, about %.0f min left" % (
                        done, total, el / done, (total - done) * el / done / 60))
            cap_log.flush()
            steps_log.flush()
        take["render"] = adapter.render_settings()  # again, now that frames exist
        adapter.end_frozen()
        take["status"] = "captured"
    except Exception as e:
        take["status"] = "retake" if isinstance(e, Retake) else "failed"
        take["error"] = "%s: %s" % (type(e).__name__, e)
        try:
            adapter.end_frozen()
        except Exception:
            pass
        raise
    finally:
        cap_log.close()
        steps_log.close()
        try:
            adapter.hide_subject(False)
        except Exception:
            pass
        take.update({"shots_captured": done, "shots_recaptured": retries, "finished": now_iso(),
                     "seconds": round(time.time() - t_start, 1),
                     "seconds_per_shot": round((time.time() - t_shots) / done, 3) if done and t_shots else None})
        write_json(os.path.join(take_dir, "take.json"), take)
    log("take captured in %.1f min (%d shots recaptured)" % (take["seconds"] / 60, retries))
    return take


def _clear_cameras(adapter, positions, centre, reach_m, margin, log, take):
    """At the start of a take: deletes everything holding any camera position of the take.
    Records what it found in take["cleared"] (also when it raises Retake)."""
    obs = adapter.obstacles(centre, reach_m)
    hit = obstacles.hits(obs, positions, margin)
    ids = [obs[k]["id"] for k in hit]
    res = adapter.remove_obstacles(ids)
    record = {"near": len(obs), "in_cameras": [{"kind": obs[k]["kind"], "cameras": len(v), "box": obs[k]["approx"]}
                                                for k, v in hit.items()],
              "removed": res["removed"], "skipped": res["skipped"]}
    log("start of take: %d people/animals/vehicles near the rig, %d hold cameras; %d entities deleted%s" % (
        len(obs), len(hit), res["removed"], ", %d not (owned by a game script)" % len(res["skipped"])
        if res["skipped"] else ""))
    take["cleared"] = record
    if res["skipped"]:
        raise Retake("a camera is inside something a game script owns, which is never deleted", 0.0)
    if ids:
        adapter.wait_frames(10)  # let the deletion reach the rendered frame
    return record


def _check_frame(adapter, step, centre, reach_m, margin):
    """{shot id: {"kind": ...}} for this clip frame's cameras inside or against something."""
    obs = adapter.obstacles(centre, reach_m)
    pos = [s["pos"] for s in step["shots"]]
    out = {}
    for k, idx in obstacles.hits(obs, pos, margin).items():
        for i in idx:
            out[step["shots"][i]["id"]] = {"kind": obs[k]["kind"]}
    return out


def _capture_shot(adapter, shot, frame, raw_dir, take_dir, settle, check, instant, attempts, cap_log, log,
                  obstructed=None):
    """Captures one shot, retrying after a failed check. Returns the number of retries."""
    for attempt in range(attempts):
        dst = os.path.join(raw_dir, "%s.bmp" % shot["id"])
        adapter.set_camera(shot)
        info = adapter.capture(dst, settle)
        pic_problems, stats = check.check(dst)
        problems = list(info.get("health", {}).get("problems", [])) + pic_problems
        if problems:
            kept = dst + ".rejected%d" % attempt
            shutil.move(dst, kept)
        else:
            kept = dst
        rec = {"id": shot["id"], "name": shot["name"], "frame": frame, "file": os.path.relpath(kept, take_dir),
               "attempt": attempt, "accepted": not problems, "problems": problems, "picture": stats,
               **{k: v for k, v in info.items() if k != "health"}}
        if obstructed:
            rec["camera_inside"] = obstructed["kind"]  # captured anyway: the take was past retake_before
        cap_log.write(json.dumps(rec) + "\n")
        if not problems:
            return attempt
        log("shot %s (%s): %s" % (shot["id"], shot["name"], "; ".join(problems)))
        cap_log.flush()
        if not adapter.recover():
            raise TakeFailed("could not recover from: " + "; ".join(problems))
        if adapter.instant() != instant:
            raise TakeFailed("the frozen instant moved while recovering; the take cannot continue")
    raise TakeFailed("shot %s failed its checks %d times" % (shot["id"], attempts))
