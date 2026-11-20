"""The take loop, against the Adapter interface.

    go to the location -> set the clock -> place the rig on the ground -> shot list
    -> hide the subject -> freeze -> for each clip frame: capture every shot, step 1/fps
    -> unfreeze -> show the subject

Every shot is checked twice: the adapter's health (focus, subject hidden, paused, ...)
and the picture itself (capture/checks.py). A failed shot gets adapter.recover() and is
captured again, but only while the frozen instant is unchanged (adapter.instant()); a
take whose instant moved cannot be continued and fails.
"""
import json
import os
import shutil
import time
import uuid

from .checks import PictureCheck
from .placement import Placement
from .shots import build, subset
from .util import now_iso, write_json


class TakeFailed(RuntimeError):
    pass


DEFAULT_SETTINGS = {
    "clock": "12:00",        # time of day; None keeps the game's
    "last_frame": 0,         # 0 = every clip frame (a sample stops earlier)
    "sweep_stride": 1,       # keep every n-th pose of the frozen sweeps (samples)
    "shot_attempts": 3,      # captures of one shot before the take fails
    "keep_raw": True,        # keep raw frames after packaging
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
    adapter.go_to(location["position"], location.get("facing_deg", 0.0))
    if settings.get("clock"):
        take["clock"] = adapter.set_clock(settings["clock"])
    origin = adapter.ground_point(location["position"])
    placement = Placement(origin, adapter.rig_rotation(location.get("facing_deg", 0.0)))
    shots = subset(build(rig, placement), settings["last_frame"], settings["sweep_stride"])
    write_json(os.path.join(take_dir, "shots.json"), shots, indent=None)
    total = shots["n_shots"]
    log("rig origin at %s; %d clip frames, %d shots, %d camera frames" % (
        ", ".join("%.3f" % v for v in origin), len(shots["steps"]), total, shots["n_camera_frames"]))
    take.update({"placement": shots["placement"], "n_shots": total, "n_camera_frames": shots["n_camera_frames"],
                 "sample": shots.get("sample")})

    check = PictureCheck()
    fps = float(shots.get("fps") or 30)
    cap_log = open(os.path.join(take_dir, "capture_log.jsonl"), "w", encoding="utf-8")
    steps_log = open(os.path.join(take_dir, "steps.jsonl"), "w", encoding="utf-8")
    settle = settings["adapter"].get("settle")
    done = retries = 0
    t_shots = None
    try:
        adapter.hide_subject(True)
        first = shots["steps"][0]["shots"][0]
        adapter.begin_frozen(first)
        take["render"] = adapter.render_settings()
        t_shots = time.time()
        prev = None
        for st in shots["steps"]:
            if prev is not None:
                for _ in range(st["frame"] - prev):
                    r = adapter.advance(1.0 / fps)
                    steps_log.write(json.dumps(dict(r, to_frame=st["frame"])) + "\n")
            prev = st["frame"]
            instant = adapter.instant()
            for shot in st["shots"]:
                retries += _capture_shot(adapter, shot, st["frame"], raw_dir, take_dir, settle, check, instant,
                                         settings["shot_attempts"], cap_log, log)
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
        take["status"] = "failed"
        take["error"] = "%s: %s" % (type(e).__name__, e)
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


def _capture_shot(adapter, shot, frame, raw_dir, take_dir, settle, check, instant, attempts, cap_log, log):
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
