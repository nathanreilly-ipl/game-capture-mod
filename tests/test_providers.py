"""Rig providers without the game.

    uv run --project . python tests/test_providers.py

1. The repository's providers are found (file, camrigs, ring).
2. ring: shrinks to clear a wall, declines when nothing fits.
3. file: a pose file goes through the queue unchanged.
4. camrigs (when its repository is checked out): on an open floor it reproduces the demo rig.
5. A provider from outside the repository: copied into the queue at submit, run from the copy,
   and refused when the copy's version differs from the submitted one.
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import providers  # noqa: E402
from capture.providers import Declined, Scene  # noqa: E402
from capture.queue import Queue  # noqa: E402
from capture.rigs import resolve  # noqa: E402

LOC = {"id": "test-loc", "position": [0, 0, 0], "facing_deg": 0.0}


def wall_scene(x):
    ys, zs = np.meshgrid(np.linspace(0, 4, 20), np.linspace(-10, 10, 80))
    pts = np.stack([np.full(ys.size, x), ys.ravel(), zs.ravel()], 1)
    return Scene(np.zeros((0, 3, 3)), pts, np.tile([-1.0, 0, 0], (len(pts), 1)), "wall at x=%g" % x)


def main():
    keys = {p["key"]: p for p in providers.listing()}
    assert {"file", "camrigs", "ring"} <= set(keys), keys
    print("1 ok: providers", sorted(keys), "| camrigs available:", keys["camrigs"]["available"])

    ring = providers.find("ring")
    s = providers.settings_for(ring, {"radius_m": 4.0})
    doc = ring.solve(wall_scene(3.0), providers.DEFAULT_SUBJECT, s)
    r = doc["record"]["radius_m"]
    assert r <= 2.5 and len(doc["cameras"]) == 16, r
    xs, ys, zs = np.meshgrid(np.arange(-5, 5.01, 0.4), np.arange(0, 4.01, 0.4), np.arange(-5, 5.01, 0.4))
    dense = np.stack([xs.ravel(), ys.ravel(), zs.ravel()], 1)
    dense = dense[np.hypot(dense[:, 0], dense[:, 2]) > 1.0]  # solid all around, 1 m clear around the subject
    try:
        ring.solve(Scene(np.zeros((0, 3, 3)), dense, np.zeros_like(dense), "solid"), providers.DEFAULT_SUBJECT,
                   providers.settings_for(ring, {}))
        raise AssertionError("expected Declined")
    except Declined as e:
        print("2 ok: ring shrank to %.2f m for a wall at 3 m; declined when solid all round: %s" % (r, e))

    with tempfile.TemporaryDirectory() as d:
        q = Queue(os.path.join(d, "queue"))
        cam = providers.find("camrigs")
        demo = cam.demo_rig_file() if keys["camrigs"]["available"] else None
        if demo:
            src = q.add_rig(demo)
            got, path = resolve(src, base_dir=q.root, location=LOC, out_dir=os.path.join(d, "solved"))
            want = json.load(open(demo, encoding="utf-8"))
            assert len(got["cameras"]) == len(want["cameras"]) and got["rig"] == want["rig"]
            print("3 ok: file provider, %s -> %d cameras (%s)" % (src["rig_id"], len(got["cameras"]), src["settings"]["path"]))

            src = q.add_provider("camrigs", {"rig": "yiming_stdm"})
            got = cam.solve(None, src["subject"], src["settings"])  # scene None = open floor
            # The demo performer stood a little off the origin; the stand-in stands on it. Compare
            # poses relative to each rig's subject centre (rotations and offsets from the centre).
            names = {c["name"]: c for c in got["cameras"]}
            cw = np.array(want["record"]["center_world"]) * [1, 0, 1]
            cg = np.array(got["record"]["center_world"]) * [1, 0, 1]

            def rel(c2w, centre):
                m = np.array(c2w, float)
                m[..., :3, 3] -= centre
                return m
            dmax = max(float(np.abs(rel(c["c2w"], cw) - rel(names[c["name"]]["c2w"], cg)).max())
                       for c in want["cameras"] if c["name"] in names)
            assert len(got["cameras"]) == len(want["cameras"]) and dmax < 1e-4, (len(got["cameras"]), dmax)
            print("4 ok: camrigs %s reproduces the demo rig on an open floor (%d cameras, max diff %.1e)" % (
                src["version"][:18], len(got["cameras"]), dmax))
        else:
            print("3, 4 skipped: no checkout of the camera-rig repository")

        ext_dir = os.path.join(d, "my_rigs")
        os.makedirs(ext_dir)
        ext = os.path.join(ext_dir, "dolly.py")
        shutil.copyfile(providers.find("ring").__provider_file__, ext)
        text = open(ext, encoding="utf-8").read().replace('KEY = "ring"', 'KEY = "dolly_test"')
        open(ext, "w", encoding="utf-8").write(text)
        src = q.add_provider(ext, {"count": 8})
        assert src.get("provider_copy", "").startswith("providers/"), src
        os.remove(ext)  # the worker must not need the original
        mod = providers.load_for_source(src, q.root)
        assert mod.KEY == "dolly_test"
        copy = os.path.join(q.root, src["provider_copy"])
        open(copy, "a", encoding="utf-8").write("\n# edited after submit\n")
        try:
            providers.load_for_source(src, q.root)
            raise AssertionError("expected a version mismatch")
        except RuntimeError as e:
            print("5 ok: external provider runs from the queue copy; an edit is refused:", str(e)[:70], "...")


if __name__ == "__main__":
    main()
