"""Client for lua/jobs/cam_session.lua: starts the job through capture_loader.lua
and sends it commands one at a time.

CAPTURES is the folder the game-side scripts and the ReShade add-on exchange files in
(fixed in capture_loader.lua and ReShade.ini). Frames only pass through it: callers move
them to their own output folder."""
import math
import os
import time

CAPTURES = os.path.join(os.environ["USERPROFILE"], "Documents", "RDR2Modding", "captures")
HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_JOB = os.path.join(HERE, "lua", "jobs", "cam_session.lua")


def heartbeat_age():
    try:
        return time.time() - os.path.getmtime(os.path.join(CAPTURES, "heartbeat.txt"))
    except OSError:
        return float("inf")


def _read_kv(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    kv = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # The game may have the target open for reading at this moment; retry briefly.
    for attempt in range(200):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def vec(s):
    return tuple(float(v) for v in s.split())


def look_at(pos, target):
    """(pitch, yaw) in degrees, rotation order 2, for a camera at pos looking at target."""
    dx, dy, dz = (target[i] - pos[i] for i in range(3))
    return math.degrees(math.atan2(dz, math.hypot(dx, dy))), math.degrees(math.atan2(-dx, dy))


class CamSession:
    def __init__(self, job_id=None, idle_s=300, timeout_s=3600):
        if heartbeat_age() > 5:
            raise RuntimeError("capture_loader.lua is not running (stale heartbeat)")
        self.job_id = job_id or time.strftime("cam_session_%Y%m%d_%H%M%S")
        self.job_dir = os.path.join(CAPTURES, "jobs", self.job_id)
        self.seq = 0
        for name in ("session_in.txt", "session_out.txt"):
            try:
                os.remove(os.path.join(CAPTURES, name))
            except OSError:
                pass
        _write_atomic(os.path.join(CAPTURES, "command.txt"),
                      "id=%s\nfile=%s\ntimeout_s=%d\nidle_s=%d\n" % (self.job_id, SESSION_JOB, timeout_s, idle_s))
        self.state = self._wait_for(0, 30)

    def _wait_for(self, seq, timeout):
        deadline = time.time() + timeout
        out_path = os.path.join(CAPTURES, "session_out.txt")
        while time.time() < deadline:
            kv = _read_kv(out_path)
            if kv and kv.get("seq") == str(seq):
                return kv
            result = _read_kv(os.path.join(self.job_dir, "result.txt"))
            if result:
                raise RuntimeError("session job ended: %s %s" % (result.get("status"), result.get("message")))
            time.sleep(0.005)
        raise TimeoutError("no answer to command %d" % seq)

    def cmd(self, name, *args, timeout=30):
        self.seq += 1
        _write_atomic(os.path.join(CAPTURES, "session_in.txt"),
                      "seq=%d\ncmd=%s\nargs=%s\n" % (self.seq, name, " ".join(str(a) for a in args)))
        kv = self._wait_for(self.seq, timeout)
        if kv.get("status") != "ok":
            raise RuntimeError("%s failed: %s" % (name, kv.get("message")))
        self.state = kv
        return kv

    def pose(self, pos, pitch, yaw, fov=50.0):
        return self.cmd("pose", "%.6f %.6f %.6f %.6f %.6f %.6f" % (pos[0], pos[1], pos[2], pitch, yaw, fov))

    def end(self):
        try:
            self.cmd("end")
        except RuntimeError:
            pass
