"""`capture verify <game>`: does this install do what scouting, capturing and iterating need?

Game-agnostic: everything goes through the game's adapter.
  1. every install step is satisfied
  2. the game is up and scripts answer (with --launch the adapter starts or restarts it)
  3. the frame rate (it sets how long each shot takes)
  4. a test frame through the capture add-on, and its colours against the screen
  5. a small frozen take (8 ring cameras, 3 clip frames): camera writes, exact time steps,
     obstacle check, packaging into videos                                   (skipped with --quick)
Writes out/install/<game>/verify/report.json and frame.jpg.
"""
import json
import os
import shutil
import time

import numpy as np
from PIL import Image

from .. import adapters_registry, providers
from ..package import package
from ..runner import run_take
from ..util import now_iso, stamp, write_json
from . import context, prereqs, work_dir


def _colour_check(frame_path, grab):
    """(ok, note): the add-on's frame against a screen grab of the same view; other windows may
    cover part of the game, so the test is only which channel order fits better."""
    a = np.asarray(Image.open(frame_path).convert("RGB").resize((320, 180)), dtype=np.float32)
    s = np.asarray(grab.convert("RGB").resize((320, 180)), dtype=np.float32)
    as_is, swapped = float(np.abs(a - s).mean()), float(np.abs(a[..., ::-1] - s).mean())
    return as_is <= swapped, "difference to the screen %.1f (%.1f with red and blue swapped)" % (as_is, swapped)


def verify(game, launch=False, quick=False, log=print):
    out = os.path.join(work_dir(game), "verify")
    os.makedirs(out, exist_ok=True)
    checks = []

    def check(name, ok, note=""):
        checks.append({"check": name, "ok": bool(ok), "note": note})
        log("  %-7s %s%s" % ("ok" if ok else "FAILED", name, ": " + note if note else ""))
        return ok

    log("machine:")
    prereqs.report(log=log)
    log("install:")
    ctx, mod = context(game, log=log)
    todo = [(s, note) for s in mod.steps(ctx) for state, note in [s.status(ctx)] if state != "ok"]
    check("all install steps satisfied", not todo, "%d to do; run: capture install %s --dry-run" % (len(todo), game) if todo else "")

    log("game:")
    adapter = adapters_registry.get(game)()
    try:
        adapter.ensure_ready(restart=launch)
        adapter.open()
    except Exception as e:
        check("the game is running and scripts answer", False, "%s%s" % (e, "" if launch else " (start it, or pass --launch)"))
        return _finish(game, out, checks, log)
    try:
        st = adapter.subject_state()
        check("the game is running and scripts answer", True, "player at %s%s" % (
            ", ".join("%.1f" % v for v in st["position"]), ", " + st["title"] if st.get("title") else ""))

        t = time.time()
        adapter.wait_frames(240)
        fps = 240 / (time.time() - t)
        settle = adapter.settings.get("settle", 40)
        # an adapter that trades frame rate for quality (path tracing) says how low is still fine
        check("frame rate", fps >= getattr(adapter, "min_fps", 55),
              "%.0f frames/s, so about %.2f s per shot (settle %s frames)" % (fps, settle / fps + 0.05, settle))

        fwd, right, up = (np.asarray(v, float) for v in adapter.heading_basis(st["facing_deg"]))
        eye = np.asarray(st["position"]) + up * 1.6 - fwd * 3.0
        frame = os.path.join(out, "frame.bmp")
        adapter.view(eye, fwd, up, 60.0, frame)
        grab = adapter.screen_grab()
        img = Image.open(frame)
        img.convert("RGB").save(os.path.join(out, "frame.jpg"), quality=90)
        os.remove(frame)
        check("a frame through the capture add-on", True, "%dx%d, %s" % (img.width, img.height, os.path.join(out, "frame.jpg")))
        if abs(img.width / img.height - 16 / 9) > 0.01:
            check("16:9 game window", False, "%dx%d: the frozen frame is letterboxed unless the window is 16:9" % img.size)
        if grab is not None:
            ok, note = _colour_check(os.path.join(out, "frame.jpg"), grab)
            check("colours match the screen", ok, note)

        if not quick:
            ring = providers.find("ring")
            rig = ring.solve(None, providers.DEFAULT_SUBJECT, providers.settings_for(ring, {"count": 8, "last": 3, "radius_m": 3.0}))
            rig_path = os.path.join(out, "rig.json")
            write_json(rig_path, rig, indent=None)
            take_dir = os.path.join(out, "take_" + stamp())
            job = {"id": "verify", "location": {"id": "verify", "game": game, "position": st["position"],
                                                "facing_deg": st["facing_deg"]},
                   "rig": {"kind": "verify", "rig_id": "verify-ring"}, "settings": {"clock": None}}
            take = run_take(adapter, job, rig, rig_path, take_dir, log=lambda m: log("          " + m))
            check("a frozen take (8 cameras, 3 clip frames)", take["status"] == "captured",
                  "%d shots in %.0f s, %d recaptured" % (take["shots_captured"], take["seconds"], take["shots_recaptured"]))
            steps = [json.loads(line) for line in open(os.path.join(take_dir, "steps.jsonl"))]
            worst = max(abs(s["advanced_s"] - 1 / 30) for s in steps) * 1000
            check("time steps of 1/30 s", worst < 3.0, "%d steps, worst error %.2f ms" % (len(steps), worst))
            adapter.close()
            meta = package(take_dir, log=lambda m: None)
            check("packaging into videos", len(meta["cameras"]) == 8, "%d cameras" % len(meta["cameras"]))
            shutil.rmtree(os.path.join(take_dir, "raw"), ignore_errors=True)
    except Exception as e:
        check("verification ran to the end", False, "%s: %s" % (type(e).__name__, e))
    finally:
        try:
            adapter.close()
        except Exception:
            pass
    return _finish(game, out, checks, log)


def _finish(game, out, checks, log):
    ok = all(c["ok"] for c in checks)
    write_json(os.path.join(out, "report.json"), {"game": game, "when": now_iso(), "ok": ok, "checks": checks})
    log("%s  (%s)" % ("VERIFIED: ready to scout, capture and iterate" if ok else "NOT VERIFIED: see the failed checks above",
                      os.path.join(out, "report.json")))
    return ok
