"""The camera's field of view in a held world.

The first-person camera eases towards a new field of view in world time (about a second), so
while the world is held (time dilation near zero) a new value never arrives: SetFOV, the fov
property, zoom, re-activating or toggling the component and a time dilation of the player's own
all left the rendered field of view unchanged over 15 to 120 frames (2026-11-21). A rig has
cameras of more than one field of view at the same instant, so the value the camera is easing
from is written in the game's memory instead, as RDR2's render camera is.

Finding it (once per game start, the world running): the field of view is set to a marker value
and left to arrive, memory is searched for that float, the world is held and a second marker
set: the copies that did not follow are the eased value. Each is tried with a third marker until
the rendered field of view reports it.

    uv run --project . python -m adapters.cyberpunk.fov      # find it in the running game and test it
"""
import struct
import time

import numpy as np

from ..common import mem
from . import paths

MARKS = (47.34375, 61.71875, 39.15625)   # exactly representable, unlikely to be in memory by chance
NEAR = 0x400                             # bytes between the component's target and its eased value, at most


class FovWriter:
    def __init__(self):
        self.proc = None
        self.addrs = None      # the addresses written together (usually one)
        self.found_in_s = None
        self.candidates = None

    def _rendered(self, sess, frames=3):
        return float(sess.cmd("wait", frames)["rendered_fov"])

    def _scan(self, value):
        want = np.float32(value)
        hits = []
        for base, size, prot, _ in self.proc.regions(writable_only=True):
            if not prot & (mem.PAGE_READWRITE | mem.PAGE_EXECUTE_READWRITE) or size > (1 << 31):
                continue
            raw = self.proc.read(base, size)
            if raw:
                f = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype=np.float32)
                hits += [base + 4 * int(i) for i in np.flatnonzero(f == want)]
        return hits

    def _read(self, addr):
        raw = self.proc.read(addr, 4)
        return struct.unpack("<f", raw)[0] if raw and len(raw) == 4 else None

    def find(self, sess, restore_fov=None, log=lambda m: None, dry_run=False):
        """Finds the eased field-of-view value. The world must be running (not held) and is left
        running, the field of view back at restore_fov (default: what it was)."""
        t0 = time.time()
        self.proc = self.proc or mem.Process(mem.find_pid(paths.EXE_NAME), write=True)
        st = sess.cmd("state")
        if st.get("frozen") == "1":
            raise RuntimeError("find the field of view while the world runs, not while it is held")
        before = float(st["rendered_fov"]) if restore_fov is None else float(restore_fov)
        m1, m2, m3 = MARKS
        sess.cmd("fov", m1)
        for _ in range(60):
            if abs(self._rendered(sess, 10) - m1) < 1e-4:
                break
        else:
            raise RuntimeError("the field of view did not arrive at %s" % m1)
        hits = self._scan(m1)
        log("%d copies of the marker in memory" % len(hits))
        # With a new target and the world still running, the copies that are the target jump to
        # it, the eased value (and what is derived from it each frame) lies in between, and
        # everything else is some other float that happened to match. Only the eased ones are
        # ever written: a test value written into the others crashed the game (2026-11-21).
        sess.cmd("fov", m2)
        sess.cmd("wait", 4)
        sess.cmd("freeze")
        try:
            sess.cmd("wait", 3)
            now = np.float32(float(sess.state["rendered_fov"]))   # where the easing stands, held
            values = {a: self._read(a) for a in hits}
            targets = [a for a, v in values.items() if v == np.float32(m2)]
            same = [a for a, v in values.items() if v == now]
            # the eased value lives in the camera component, beside its target (a few hundred
            # bytes apart); the other copies are per-frame camera data made from it
            eased = sorted((a for a in same if any(abs(a - t) <= NEAR for t in targets)),
                           key=lambda a: min(abs(a - t) for t in targets))
            self.candidates = len(eased)
            log("%d follow the target (%s); %d hold the eased value %.4f, %d of them beside a target (%s)" % (
                len(targets), ", ".join("0x%x" % t for t in targets), len(same), now, len(eased),
                ", ".join("%+d" % min((a - t for t in targets), key=abs) for a in eased)))
            if dry_run:
                return None
            found = None
            for a in eased:
                self.proc.write(a, struct.pack("<f", m3))
                if abs(self._rendered(sess) - m3) < 1e-4:
                    found = [a]
                    break
                self.proc.write(a, struct.pack("<f", values[a]))
            if found is None:
                raise RuntimeError("no eased value drives the rendered field of view (%d candidates)" % len(eased))
            self.addrs = found
        finally:
            sess.cmd("fov", before)
            if self.addrs:
                self.set(before)
            sess.cmd("unfreeze")
        self.found_in_s = round(time.time() - t0, 1)
        log("field of view at %s, found in %.1f s" % (", ".join("0x%x" % a for a in self.addrs), self.found_in_s))
        return self.addrs

    def set(self, vfov_deg):
        """Makes the camera render this vertical field of view (degrees) from the next frame."""
        if not self.addrs:
            raise RuntimeError("FovWriter.find has not run")
        data = struct.pack("<f", float(vfov_deg))
        for a in self.addrs:
            self.proc.write(a, data)

    def close(self):
        if self.proc is not None:
            self.proc.close()
        self.proc, self.addrs = None, None


if __name__ == "__main__":
    from ..common import redlua
    from .adapter import SESSION_JOB
    s = redlua.Session(paths.exchange(), SESSION_JOB, idle_s=300, timeout_s=900, staged=True)
    w = FovWriter()
    try:
        import sys
        if w.find(s, log=print, dry_run="--dry-run" in sys.argv) is None:
            sys.exit(0)
        s.cmd("freeze")
        for v in (30.0, 54.698, 75.923, 54.698):
            w.set(v)
            s.cmd("fov", v)
            print("asked %.3f, rendered %.4f after 3 frames, %.4f after 120" % (v, float(s.cmd("wait", 3)["rendered_fov"]),
                                                                              float(s.cmd("wait", 120)["rendered_fov"])))
        s.cmd("unfreeze")
    finally:
        w.close()
        s.end()
