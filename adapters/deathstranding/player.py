"""Sam's physics body in Death Stranding's memory: where he is, and moving him (the teleport the game
has no command for). Found 2026-11-25 (1.004), adapters/deathstranding/probes:

    Sam's entity keeps his transform at +0xC8 (three doubles, then a 3x3 rotation of floats); it is
    written every frame he moves, from his character's physics, so writing it alone snaps back.
    The physics shape under it (a capsule) keeps his position as three floats at +0x80, in world
    coordinates (the physics world's origin was 0), 0.85 m above his feet: an identity rotation at
    +0x50..+0x7C, the position at +0x80, the capsule's bounds at +0x90 (-0.4029, -0.4029, -0.8029)
    and +0xA0 (0.4029, 0.4029, 0.8029). Writing the position there moves Sam: the entity followed
    within a frame and stayed (3.000 m written, 3.17 m after he settled on the slope, the world
    running).

The shape's address changes every launch, so it is found by that signature: the bounds' floats,
then the rotation and a position near the game's camera. The scan reads the game's heaps once
(about 10 s); the address is kept and checked before each use.
"""
import struct

import numpy as np

from ..common import mem
from . import paths

FEET = 0.85                         # the capsule's centre above Sam's feet (measured: 256.0526 - 255.2026)
BOUNDS = np.array([0.4029, 0.4029, 0.8029], np.float32)
CHUNK = 64 << 20


class PlayerError(RuntimeError):
    pass


def _valid(proc, d, near=None, radius=60.0):
    raw = proc.read(d + 0x50, 0x60)
    if not raw or len(raw) < 0x60:
        return False
    f = np.frombuffer(raw, dtype=np.float32)
    rot = np.array([f[0:3], f[4:7], f[8:11]])
    pos = f[12:15]
    lo, hi = f[16:19], f[20:23]
    if not np.all(np.isfinite(f)):
        return False
    if np.abs(rot - np.eye(3)).max() > 1e-4 or np.abs(hi - BOUNDS).max() > 1e-3 or np.abs(lo + BOUNDS).max() > 1e-3:
        return False
    if near is not None and np.linalg.norm(pos - np.asarray(near, np.float32)) > radius:
        return False
    return True


def find_body(proc, near, radius=60.0):
    """The address of Sam's physics shape: the capsule signature nearest to `near` (the game's camera)."""
    best, best_d = None, None
    pat = BOUNDS.tobytes()
    for base, size, _, typ in proc.regions():
        if typ != 0x20000:          # private heaps only
            continue
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            raw = proc.read(base + off, n)
            start = base + off
            off += n
            if not raw:
                continue
            a = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype=np.float32)
            with np.errstate(invalid="ignore", over="ignore"):     # heaps hold NaNs and infinities
                idx = np.nonzero(np.abs(a - BOUNDS[0]) < 2e-4)[0]
            for i in idx:
                if i + 2 >= len(a) or not (abs(float(a[i + 1]) - BOUNDS[1]) <= 2e-4 and abs(float(a[i + 2]) - BOUNDS[2]) <= 2e-4):
                    continue
                d = start + 4 * int(i) - 0xA0
                if (d - start) % 16 or not _valid(proc, d, near, radius):
                    continue
                p = np.array(proc.read_floats(d + 0x80, 3))
                dist = float(np.linalg.norm(p - np.asarray(near)))
                if best is None or dist < best_d:
                    best, best_d = d, dist
    if best is None:
        raise PlayerError("Sam's physics shape was not found within %.0f m of the camera" % radius)
    return best


class Player:
    """Sam's position and a teleport, through his physics shape."""

    def __init__(self, write=True):
        self.proc = mem.Process(exe=paths.EXE_NAME, write=write)
        self.body = None

    def _body(self, near):
        if self.body is None or not _valid(self.proc, self.body):
            self.body = find_body(self.proc, near)
        return self.body

    def position(self, near):
        """Sam's feet, world coordinates."""
        d = self._body(near)
        p = np.array(self.proc.read_floats(d + 0x80, 3), float)
        return [float(p[0]), float(p[1]), float(p[2] - FEET)]

    def teleport(self, feet, near):
        """Puts Sam's feet at `feet` (lifted 5 cm, so he settles onto the ground rather than into it)."""
        d = self._body(near)
        self.proc.write_floats(d + 0x80, [float(feet[0]), float(feet[1]), float(feet[2]) + FEET + 0.05])
        self.body = d
        return d
