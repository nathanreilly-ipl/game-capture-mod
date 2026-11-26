"""Finds world transforms (Decima's WorldTransform: position as three doubles, then a 3x3 rotation
as nine floats, rows right, forward, up) near a point: the entities around the camera, Sam among
them. How Sam's transform was found (2026-11-25).

    python -m adapters.deathstranding.probes.transform_probe [--radius 6] [--upright]
"""
import argparse
import struct

import numpy as np

from adapters.common import mem

from ..plugin import Plugin

CHUNK = 64 << 20


def scan(proc, center, radius, upright):
    cx, cy, cz = center
    hits = []
    for base, size, _, typ in proc.regions():
        off = 0
        while off < size:
            n = min(CHUNK, size - off)
            raw = proc.read(base + off, n)
            off += n
            if not raw or len(raw) < 64:
                continue
            d = np.frombuffer(raw[: len(raw) - len(raw) % 8], dtype=np.float64)
            with np.errstate(invalid="ignore"):
                m = (np.abs(d[:-8] - cx) < radius) & (np.abs(d[1:-7] - cy) < radius) & (np.abs(d[2:-6] - cz) < radius)
            for i in np.nonzero(m)[0]:
                b = 8 * int(i)
                if b + 60 > len(raw):
                    continue
                rot = np.array(struct.unpack_from("<9f", raw, b + 24)).reshape(3, 3)
                if not np.all(np.isfinite(rot)):
                    continue
                if np.abs(rot @ rot.T - np.eye(3)).max() > 1e-3:
                    continue
                if upright and np.abs(rot[2] - [0, 0, 1]).max() > 1e-3:
                    continue
                pos = struct.unpack_from("<3d", raw, b)
                hits.append((base + off - n + b, pos, rot))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--radius", type=float, default=6.0)
    ap.add_argument("--upright", action="store_true")
    a = ap.parse_args()
    cam = Plugin().game_camera()[0]
    proc = mem.Process(exe="ds.exe")
    hits = scan(proc, cam, a.radius, a.upright)
    print("camera at %.3f %.3f %.3f; %d transforms within %.1f m" % (*cam, len(hits), a.radius))
    for addr, pos, rot in sorted(hits, key=lambda h: np.linalg.norm(np.array(h[1]) - cam)):
        fwd = rot[1]
        print("%s  pos %.3f %.3f %.3f  dist %.2f  fwd %.3f %.3f %.3f" % (hex(addr), *pos, np.linalg.norm(np.array(pos) - cam), *fwd))


if __name__ == "__main__":
    main()
