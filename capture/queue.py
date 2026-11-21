"""A job queue in a folder, so workers on one machine or several (with the folder on a
shared drive) can take jobs without a server.

    <root>/pending/<job id>.json
    <root>/claimed/<job id>.json  + <job id>.lease   (the worker touches the lease while it runs)
    <root>/done/<job id>.json     the job plus its result
    <root>/failed/<job id>.json   the job plus its error
    <root>/rigs/<rig>-<hash>.json every rig file submitted with the "file" provider, never changed
    <root>/providers/<key>_<hash>.py   rig providers from outside the repository, as submitted

A worker claims a job by renaming it from pending/ to claimed/ (atomic on one volume, so
two workers never get the same job). A claim whose lease is older than `stale_s` belongs
to a worker that died; requeue_stale() puts it back in pending/.

A job:
    {"schema": "capture_job/v1", "id": ..., "game": "rdr2",
     "location": {...copy of the location entry...},
     "rig": {"kind": "provider", "provider": "camrigs", "version": ..., "settings": {...},
             "subject": {...}, "scene": {...}, "rig_id": ..., "digest": ...},   (capture/providers.py)
     "settings": {...see capture/runner.py DEFAULT_SETTINGS...},
     "submitted": ..., "attempts": 0}
The id is a hash of game, location, rig and settings: submitting the same job again is a
no-op unless forced.
"""
import os
import time

from .providers import make_source
from .util import digest_json, now_iso, read_json, write_json

SCHEMA = "capture_job/v1"
STATES = ("pending", "claimed", "done", "failed")


class Queue:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        for d in STATES + ("rigs",):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def _path(self, state, job_id, ext=".json"):
        return os.path.join(self.root, state, job_id + ext)

    def find(self, job_id):
        for state in STATES:
            if os.path.exists(self._path(state, job_id)):
                return state
        return None

    def add_provider(self, key_or_path, settings=None, subject=None, scene=None):
        """A rig source for a rig provider (capture/providers.py); files it needs are kept in the
        queue folder (rigs/, providers/) so every worker reads the same ones."""
        return make_source(key_or_path, settings, subject, scene, store=self.root)

    def add_rig(self, rig_path):
        """A camrig/v1 pose file used as it is (the "file" provider)."""
        return self.add_provider("file", {"path": rig_path})

    def submit(self, game, location, rig_source, settings, force=False):
        key = {"game": game, "location": location["id"], "position": location["position"],
               "facing_deg": location.get("facing_deg"), "rig": rig_source["digest"], "settings": settings}
        job_id = "%s-%s-%s" % (location["id"], rig_source["rig_id"], digest_json(key)[:8])
        state = self.find(job_id)
        if state and not force:
            return job_id, state, False
        if state:
            os.remove(self._path(state, job_id))
        job = {"schema": SCHEMA, "id": job_id, "game": game, "location": location, "rig": rig_source,
               "settings": settings, "submitted": now_iso(), "attempts": 0}
        write_json(self._path("pending", job_id), job)
        return job_id, "pending", True

    def claim(self, worker, game=None):
        """The oldest pending job for this game, now claimed by worker; None if there is none."""
        pending = []
        for name in os.listdir(os.path.join(self.root, "pending")):
            if name.endswith(".json"):
                p = os.path.join(self.root, "pending", name)
                try:
                    job = read_json(p)
                except (OSError, ValueError):
                    continue
                if game and job.get("game") != game:
                    continue
                pending.append((job.get("submitted", ""), name))
        for _, name in sorted(pending):
            src = os.path.join(self.root, "pending", name)
            dst = os.path.join(self.root, "claimed", name)
            try:
                os.rename(src, dst)
            except OSError:
                continue  # another worker took it
            job = read_json(dst)
            job["attempts"] = job.get("attempts", 0) + 1
            job["claimed_by"] = worker
            job["claimed"] = now_iso()
            write_json(dst, job)
            self.touch(job["id"], worker)
            return job
        return None

    def touch(self, job_id, worker):
        with open(self._path("claimed", job_id, ".lease"), "w", encoding="utf-8") as f:
            f.write("%s %s\n" % (worker, now_iso()))

    def _release(self, job_id):
        try:
            os.remove(self._path("claimed", job_id, ".lease"))
        except OSError:
            pass

    def finish(self, job, result):
        write_json(self._path("done", job["id"]), dict(job, result=result, finished=now_iso()))
        os.remove(self._path("claimed", job["id"]))
        self._release(job["id"])

    def fail(self, job, error):
        write_json(self._path("failed", job["id"]), dict(job, error=error, failed=now_iso()))
        try:
            os.remove(self._path("claimed", job["id"]))
        except OSError:
            pass
        self._release(job["id"])

    def retry(self, job_id):
        """Moves a failed job back to pending."""
        job = read_json(self._path("failed", job_id))
        job.pop("error", None)
        job.pop("failed", None)
        write_json(self._path("pending", job_id), job)
        os.remove(self._path("failed", job_id))

    def requeue_stale(self, stale_s=900):
        moved = []
        for name in os.listdir(os.path.join(self.root, "claimed")):
            if not name.endswith(".json"):
                continue
            job_id = name[:-5]
            lease = self._path("claimed", job_id, ".lease")
            age = time.time() - os.path.getmtime(lease) if os.path.exists(lease) else float("inf")
            if age > stale_s:
                os.rename(self._path("claimed", job_id), self._path("pending", job_id))
                self._release(job_id)
                moved.append(job_id)
        return moved

    def status(self):
        out = {}
        for state in STATES:
            out[state] = sorted(n[:-5] for n in os.listdir(os.path.join(self.root, state)) if n.endswith(".json"))
        return out

    def load(self, job_id):
        state = self.find(job_id)
        return state, (read_json(self._path(state, job_id)) if state else None)
