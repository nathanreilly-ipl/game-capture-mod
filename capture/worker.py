"""A worker: one game instance taking jobs from the queue until there are none.

For each job: make sure the game is up (restart it if not), capture the take, package it,
make its sheets, and mark the job done, or failed with the reason. A failed job stays in
failed/ until someone retries it.
"""
import os
import shutil
import socket
import threading
import time
import traceback

from . import adapters_registry
from .package import package
from .queue import Queue
from .rigs import resolve
from .runner import run_take
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


def take_dir_for(takes_root, job):
    return os.path.join(takes_root, job["location"]["id"], job["rig"]["rig_id"], "%s_%s" % (stamp(), job["id"][-8:]))


def run_worker(game, queue_root, takes_root, worker_id=None, once=False, wait_s=30, restart=True,
               adapter_settings=None, log=print):
    worker_id = worker_id or "%s-%s" % (socket.gethostname(), game)
    queue = Queue(queue_root)
    for job_id in queue.requeue_stale():
        log("requeued stale job %s" % job_id)
    adapter = adapters_registry.get(game)(adapter_settings)
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
        try:
            adapter.ensure_ready(restart=restart)
            adapter.settings.update(job.get("settings", {}).get("adapter", {}))
            adapter.open()
            rig, rig_path = resolve(job["rig"], base_dir=queue.root, location=job["location"])
            take = run_take(adapter, job, rig, rig_path, take_dir, log=log)
            adapter.close()
            meta = package(take_dir, log=log)
            sheets = make_sheets(take_dir, log=log)
            if not take["settings"].get("keep_raw", True):
                shutil.rmtree(os.path.join(take_dir, "raw"), ignore_errors=True)
            queue.finish(job, {"take_dir": take_dir, "package": os.path.join(take_dir, "package"),
                               "cameras": len(meta["cameras"]), "shots": take["n_shots"],
                               "shots_recaptured": take["shots_recaptured"], "seconds": take["seconds"],
                               "sheets": sheets, "worker": worker_id})
            log("job %s done: %s" % (job["id"], take_dir))
        except Exception as e:
            log("job %s failed: %s: %s" % (job["id"], type(e).__name__, e))
            queue.fail(job, {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc(),
                             "take_dir": take_dir, "worker": worker_id})
            try:
                adapter.close()
            except Exception:
                pass
        finally:
            lease.stop.set()
        if once:
            break
    return n
