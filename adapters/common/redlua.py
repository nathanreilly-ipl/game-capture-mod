"""Driving a game through RedLua (it has RDR2 and GTA V builds): the job loader and a client
for a long session job that takes one command at a time.

lua/capture_loader.lua runs inside the game (RedLua, Autorun on). It watches an exchange folder,
where the game-side scripts and the capture add-on swap files:

    command.txt              start a job (id, file, timeout_s, idle_s, extra key=value args)
    heartbeat.txt            rewritten about once a second while the loader runs
    session_in.txt / _out    one command and its answer (seq, cmd, args / seq, status, state)
    request.txt / ack.txt    a frame asked of the capture add-on, and its answer
    jobs/<id>/               job.log, result.txt, the frames a job captured

Frames only pass through the exchange folder: callers move them to their own output folder.
Each game has its own exchange folder; the loader is installed with it written in.
"""
import math
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOADER = os.path.join(HERE, "lua", "capture_loader.lua")


def loader_text(exchange=None):
    """The loader script, watching `exchange` (None: the folder written in the file, RDR2's)."""
    text = open(LOADER, encoding="utf-8").read()
    if exchange is None:
        return text
    lua_path = "'" + exchange.replace("\\", "\\\\").replace("'", "\\'") + "'"
    new, n = re.subn(r"^local OUT_DIR = .*$", lambda m: "local OUT_DIR = " + lua_path, text, count=1, flags=re.M)
    if n != 1:
        raise ValueError("capture_loader.lua has no OUT_DIR line")
    return new


def heartbeat_age(exchange):
    try:
        return time.time() - os.path.getmtime(os.path.join(exchange, "heartbeat.txt"))
    except OSError:
        return float("inf")


def read_kv(path):
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


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # The game may have the target open for reading at this moment; retry briefly.
    for _ in range(200):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def vec(s):
    return tuple(float(v) for v in s.split())


def look_at(pos, target):
    """(pitch, yaw) in degrees, rotation order 2 (RAGE: RDR2 and GTA V), for a camera at pos
    looking at target. World +Z up, heading counter-clockwise from +Y."""
    dx, dy, dz = (target[i] - pos[i] for i in range(3))
    return math.degrees(math.atan2(dz, math.hypot(dx, dy))), math.degrees(math.atan2(-dx, dy))


CONSOLE_TITLE = "RedLua debug console"


def minimize_console():
    """Minimizes RedLua's debug console, which opens on top of the game window (it covered part
    of GTA V's window in screen grabs, 2026-11-21). Returns how many were minimized."""
    from . import window
    n = 0
    for h in window.windows_titled(CONSOLE_TITLE):
        window.user32.ShowWindow(h, 7)   # SW_SHOWMINNOACTIVE
        n += 1
    return n


def run_job(exchange, job_file, timeout_s=60, wait=True, **args):
    """Runs one Lua job through the loader; returns its result.txt as a dict (waits for it)."""
    if heartbeat_age(exchange) > 5:
        raise RuntimeError("capture_loader.lua is not running in the game (no heartbeat in %s)" % exchange)
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.splitext(os.path.basename(job_file))[0])
    job_id = "%s_%s" % (stem, time.strftime("%Y%m%d_%H%M%S"))
    lines = ["id=%s" % job_id, "file=%s" % os.path.abspath(job_file), "timeout_s=%d" % timeout_s]
    lines += ["%s=%s" % (k, v) for k, v in args.items()]
    result = os.path.join(exchange, "jobs", job_id, "result.txt")
    write_atomic(os.path.join(exchange, "command.txt"), "\n".join(lines) + "\n")
    if not wait:
        return {"id": job_id}
    deadline = time.time() + timeout_s + 15
    while time.time() < deadline:
        kv = read_kv(result)
        if kv and kv.get("id") == job_id:
            kv["job_dir"] = os.path.dirname(result)
            return kv
        time.sleep(0.1)
    raise TimeoutError("job %s did not finish" % job_id)


class Session:
    """A long job (job_file) driven one command at a time: cmd(name, *args) -> answer dict."""

    def __init__(self, exchange, job_file, job_id=None, idle_s=300, timeout_s=3600):
        if heartbeat_age(exchange) > 5:
            raise RuntimeError("capture_loader.lua is not running (stale heartbeat in %s)" % exchange)
        self.exchange = exchange
        self.job_id = job_id or time.strftime("cam_session_%Y%m%d_%H%M%S")
        self.job_dir = os.path.join(exchange, "jobs", self.job_id)
        self.seq = 0
        for name in ("session_in.txt", "session_out.txt"):
            try:
                os.remove(os.path.join(exchange, name))
            except OSError:
                pass
        write_atomic(os.path.join(exchange, "command.txt"),  # the loader runs in the game's folder
                     "id=%s\nfile=%s\ntimeout_s=%d\nidle_s=%d\n" % (self.job_id, os.path.abspath(job_file), timeout_s, idle_s))
        self.state = self._wait_for(0, 30)

    def _wait_for(self, seq, timeout):
        deadline = time.time() + timeout
        out_path = os.path.join(self.exchange, "session_out.txt")
        while time.time() < deadline:
            kv = read_kv(out_path)
            if kv and kv.get("seq") == str(seq):
                return kv
            result = read_kv(os.path.join(self.job_dir, "result.txt"))
            if result:
                raise RuntimeError("session job ended: %s %s" % (result.get("status"), result.get("message")))
            time.sleep(0.005)
        raise TimeoutError("no answer to command %d" % seq)

    def cmd(self, name, *args, timeout=30):
        self.seq += 1
        write_atomic(os.path.join(self.exchange, "session_in.txt"),
                     "seq=%d\ncmd=%s\nargs=%s\n" % (self.seq, name, " ".join(str(a) for a in args)))
        kv = self._wait_for(self.seq, timeout)
        if kv.get("status") != "ok":
            raise RuntimeError("%s failed: %s" % (name, kv.get("message")))
        self.state = kv
        return kv

    def end(self):
        try:
            self.cmd("end", timeout=10)
        except (RuntimeError, TimeoutError):
            pass   # the job already ended, or the game is gone


if __name__ == "__main__":
    # python -m adapters.common.redlua <exchange folder> <job.lua> [timeout_s] [key=value ...]
    import sys
    ex, job = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    t = int(rest.pop(0)) if rest and rest[0].isdigit() else 60
    res = run_job(ex, job, t, **dict(a.split("=", 1) for a in rest))
    for k, v in res.items():
        print("%s=%s" % (k, v))
    log = os.path.join(res["job_dir"], "job.log")
    if os.path.exists(log):
        print("--- job.log")
        print(open(log, encoding="utf-8", errors="replace").read()[-4000:])
