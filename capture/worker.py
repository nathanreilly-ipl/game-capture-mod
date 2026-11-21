"""A worker: one game instance taking jobs from the queue until there are none.

For each job: make sure the game is up (restart it if not), capture the take, package it,
make its sheets, and mark the job done, or failed with the reason. If the game goes away
mid-take (a script fault closes it, a graphics error stops it), the worker restarts it and takes
again, up to MAX_GAME_RESTARTS times. A failed job stays in failed/ until someone retries it.
"""
import os
import shutil
import socket
import threading
import time
import traceback

from . import adapters_registry, paths, providers
from .util import write_json
from .package import package
from .queue import Queue
from .rigs import resolve
from .runner import Retake, TakeFailed, merged_settings, run_take
from .sheets import make_sheets
from .util import stamp


class _Lease(threading.Thread):
    def __init__(self, queue, job_id, worker, every_s=30):
        super().__init__(daemon=True)
        self.queue, self.job_id, self.worker, self.every_s = queue, job_id, worker, every_s
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(self.every_s):
            try:
                self.queue.touch(self.job_id, self.worker)
            except OSError:
                pass


def _provider_qc(job, queue, take_dir, rig, take, log):
    """The rig provider's own check of the packaged take (capture/providers.py qc), recorded in
    take.json; with the job setting qc = "fail" a failed check fails the job."""
    mode = merged_settings(job.get("settings")).get("qc", "flag")
    src = job["rig"]
    if mode == "off" or src.get("kind") != "provider":
        return None
    mod = providers.load_for_source(src, queue.root)
    if not hasattr(mod, "qc"):
        return None
    try:
        res = mod.qc(os.path.join(take_dir, "package"), rig, take)
    except Exception as e:
        res = {"ok": False, "message": "%s: %s" % (type(e).__name__, e)}
    log("qc (%s): %s %s" % (mod.KEY, {True: "passed", False: "FAILED", None: "-"}.get(res.get("ok")), res.get("message", "")))
    take["qc"] = res
    write_json(os.path.join(take_dir, "take.json"), take)
    if res.get("ok") is False and mode == "fail":
        raise TakeFailed("qc failed: %s" % res.get("message"))
    return res


MAX_GAME_RESTARTS = 2   # game restarts within one job before it fails


def _game_alive(adapter):
    """Whether the game is still up and drivable (the adapter's check, without restarting it)."""
    try:
        adapter.ensure_ready(restart=False)
        return True
    except Exception:
        return False


def take_dir_for(takes_root, job):
    return os.path.join(takes_root, job["location"]["id"], job["rig"]["rig_id"], "%s_%s" % (stamp(), job["id"][-8:]))


def run_worker(game, queue_root, takes_root, worker_id=None, once=False, wait_s=30, restart=True,
               adapter_settings=None, log=print):
    worker_id = worker_id or "%s-%s" % (socket.gethostname(), game)
    queue = Queue(queue_root)
    for job_id in queue.requeue_stale():
        log("requeued stale job %s" % job_id)
    adapter = adapters_registry.get(game)(adapter_settings)
    base_settings = dict(adapter.settings)  # each job starts from these, plus its own
    n = 0
    while True:
        job = queue.claim(worker_id, game=game)
        if job is None:
            if once:
                break
            time.sleep(wait_s)
            continue
        n += 1
        log("job %s (attempt %d)" % (job["id"], job["attempts"]))
        lease = _Lease(queue, job["id"], worker_id)
        lease.start()
        take_dir = take_dir_for(takes_root, job)
        retakes = []
        try:
            adapter.ensure_ready(restart=restart)
            adapter.settings = dict(base_settings, **job.get("settings", {}).get("adapter", {}))
            adapter.open()
            rig, rig_path = resolve(job["rig"], base_dir=queue.root, location=job["location"], adapter=adapter,
                                    out_dir=os.path.join(paths.OUT, "solved"),
                                    scene_dir=os.path.join(os.path.dirname(paths.LOCATIONS), "scenes"), log=log)
            max_retakes = int(merged_settings(job.get("settings"))["max_retakes"])
            first_dir = take_dir
            attempt = blocked = game_restarts = 0
            while True:
                take_dir = first_dir if attempt == 0 else "%s_retake%d" % (first_dir, attempt)
                attempt += 1
                try:
                    take = run_take(adapter, job, rig, rig_path, take_dir, log=log)
                    break
                except Retake as r:
                    # the aborted attempt keeps its logs; its frames are of no use
                    shutil.rmtree(os.path.join(take_dir, "raw"), ignore_errors=True)
                    retakes.append({"take_dir": take_dir, "reason": str(r)})
                    blocked += 1
                    log("retake %d of %d: %s" % (blocked, max_retakes, r))
                    if blocked > max_retakes:
                        raise TakeFailed("still blocked after %d retakes: %s" % (max_retakes, r))
                except Exception as e:
                    # The game itself went away mid-take (a script fault closed it, a graphics error
                    # stopped it): restart it and take again, a few times. Anything else is a failure.
                    if not restart or game_restarts >= MAX_GAME_RESTARTS or _game_alive(adapter):
                        raise
                    game_restarts += 1
                    shutil.rmtree(os.path.join(take_dir, "raw"), ignore_errors=True)
                    retakes.append({"take_dir": take_dir, "reason": "the game stopped: %s: %s" % (type(e).__name__, e)})
                    log("the game stopped mid-take (%s: %s); restarting it (%d of %d)" % (
                        type(e).__name__, e, game_restarts, MAX_GAME_RESTARTS))
                    try:
                        adapter.close()
                    except Exception:
                        pass
                    adapter.ensure_ready(restart=True)
                    adapter.open()
            adapter.close()
            meta = package(take_dir, log=log)
            sheets = make_sheets(take_dir, log=log)
            qc = _provider_qc(job, queue, take_dir, rig, take, log)
            if not take["settings"].get("keep_raw", True):
                shutil.rmtree(os.path.join(take_dir, "raw"), ignore_errors=True)
            queue.finish(job, {"take_dir": take_dir, "package": os.path.join(take_dir, "package"),
                               "cameras": len(meta["cameras"]), "shots": take["n_shots"],
                               "shots_recaptured": take["shots_recaptured"], "seconds": take["seconds"],
                               "retakes": retakes, "cleared": take.get("cleared"),
                               "obstructions": take.get("obstructions"), "qc": qc, "sheets": sheets,
                               "worker": worker_id})
            log("job %s done: %s" % (job["id"], take_dir))
        except Exception as e:
            log("job %s failed: %s: %s" % (job["id"], type(e).__name__, e))
            queue.fail(job, {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc(),
                             "take_dir": take_dir, "retakes": retakes, "worker": worker_id})
            try:
                adapter.close()
            except Exception:
                pass
        finally:
            lease.stop.set()
        if once:
            break
    return n
