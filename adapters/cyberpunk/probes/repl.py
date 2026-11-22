"""Runs Lua in the running game and prints what it returns: the way the game's script API was
explored for this adapter (Cyber Engine Tweaks exposes it to Lua, but only inside the game).

    uv run --project . python -m adapters.cyberpunk.probes.repl "return Game.GetPlayer():GetWorldPosition()"
    uv run --project . python -m adapters.cyberpunk.probes.repl --file probe.lua [--keep]

One session job is started per call and ended afterwards (--keep leaves it running, so E, the
table that lasts for a session, keeps its values for the next call with --keep). In the code:
out(...) adds an output line, after(frames, fn) runs fn later, and a chunk that returns ASYNC
answers when it calls done(...). Dump helpers of Cyber Engine Tweaks work too, e.g.
"return DumpType('gameTimeSystem', true)".
"""
import os
import sys

from ...common import redlua
from .. import paths

JOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lua", "jobs", "cam_session.lua")
KEEP = os.path.join(paths.exchange(), "repl_session.txt")


def run(code, sess=None, timeout=60):
    """Runs a chunk in a session (a new one if none is given); returns (state, output text)."""
    ex = paths.exchange()
    own = sess is None
    if own:
        sess = redlua.Session(ex, JOB, idle_s=600, timeout_s=3600, staged=True)
    try:
        with open(os.path.join(ex, "eval_in.lua"), "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
        st = sess.cmd("eval", timeout=timeout)
        with open(os.path.join(ex, "eval_out.txt"), encoding="utf-8", errors="replace") as f:
            return st, f.read()
    finally:
        if own:
            sess.end()


class Kept(redlua.Session):
    """Attaches to the session an earlier --keep call left running."""

    def __init__(self, exchange, job_id, seq):
        self.exchange, self.job_id, self.seq = exchange, job_id, seq
        self.job_dir = os.path.join(exchange, "jobs", job_id)
        self.state = {}


def main(argv):
    keep = "--keep" in argv
    argv = [a for a in argv if a != "--keep"]
    if argv and argv[0] == "--file":
        code = open(argv[1], encoding="utf-8").read()
    else:
        code = " ".join(argv)
    ex = paths.exchange()
    sess = None
    if keep:
        kv = redlua.read_kv(KEEP)
        hb = redlua.read_kv(os.path.join(ex, "heartbeat.txt")) or {}
        if kv and hb.get("job") == kv.get("job"):
            sess = Kept(ex, kv["job"], int(kv["seq"]))
        else:
            sess = redlua.Session(ex, JOB, idle_s=1800, timeout_s=6 * 3600, staged=True)
    st, text = run(code, sess)
    if keep:
        redlua.write_atomic(KEEP, "job=%s\nseq=%d\n" % (sess.job_id, sess.seq))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
