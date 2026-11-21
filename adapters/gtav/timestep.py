"""GTA V's minimum time step, the reason SET_TIME_SCALE(0) is not a freeze.

At time scale 0 the engine still advances the world by a minimum step of 1/3000 s per frame
(measured 2026-11-21: GET_FRAME_TIME 0.000333 s, people walking on, the game timer unchanged);
RDR2 shows the same 0.33 ms. The step is one writable float in GTA5.exe's image (found by
probes/timestep_probe.py: the only writable 1/3000 in the image, offset 0x1e7c090 in Legacy
1.0.3889.0). Lowering it while the world is held at time scale 0 makes the freeze nearly exact
while the script camera still renders; it is put back when the freeze ends.

The address is found by value on every start (the image moves with each launch, and a game
update moves the variable), and the frame time read back confirms it.
"""
import struct

import numpy as np

from ..common import mem

DEFAULT = np.float32(1.0 / 3000.0)


class MinStep:
    def __init__(self, exe):
        self.exe = exe
        self.proc = None
        self.addr = None
        self.original = None

    def find(self):
        """The address of the game's minimum step: the single writable float32 1/3000 in the exe's image."""
        if self.addr is not None:
            return self.addr
        self.proc = self.proc or mem.Process(mem.find_pid(self.exe), write=True)
        base, size = self.proc.module(self.exe)
        found = []
        for rb, rs, prot, _ in self.proc.regions(writable_only=True):
            # read-write pages only (the image's other 1/3000 is in a copy-on-write page)
            if rb + rs <= base or rb >= base + size or not prot & (mem.PAGE_READWRITE | mem.PAGE_EXECUTE_READWRITE):
                continue
            raw = self.proc.read(rb, rs)
            if raw:
                f = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype=np.float32)
                found += [rb + 4 * int(i) for i in np.flatnonzero(f == DEFAULT)]
        if len(found) != 1:
            raise RuntimeError("expected one writable 1/3000 in %s, found %d (a game update?)" % (self.exe, len(found)))
        self.addr = found[0]
        self.original = self.proc.read(self.addr, 4)
        return self.addr

    def set(self, seconds):
        addr = self.find()
        self.proc.write(addr, struct.pack("<f", seconds))

    def restore(self):
        if self.addr is not None and self.original is not None:
            try:
                self.proc.write(self.addr, self.original)
            except OSError:
                pass   # the game is gone

    def close(self):
        self.restore()
        if self.proc is not None:
            self.proc.close()
        self.proc, self.addr, self.original = None, None, None
