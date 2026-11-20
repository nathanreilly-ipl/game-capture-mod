"""Records a capture location from the running game: the subject's ground point and
facing, plus four previews looking outward from it (front, right, back, left of the
facing) at eye height, so a person or an agent can judge whether the spot is open enough.

Without --at, the location is wherever the player stands. With --at, the player is moved
there first (the scout then works the same for a person and for an agent).
"""
import os

import numpy as np
from PIL import Image, ImageDraw

from . import locations as locs
from .util import now_iso

DIRECTIONS = (("front", 0.0), ("right", -90.0), ("back", 180.0), ("left", 90.0))


def _sheet(images, labels, width=640):
    tiles = []
    for img, label in zip(images, labels):
        h = round(img.height * width / img.width)
        t = Image.new("RGB", (width, h + 22), (24, 24, 24))
        t.paste(img.resize((width, h), Image.LANCZOS), (0, 22))
        ImageDraw.Draw(t).text((6, 5), label, fill=(235, 235, 235))
        tiles.append(t)
    out = Image.new("RGB", (2 * width, 2 * tiles[0].height), (24, 24, 24))
    for i, t in enumerate(tiles):
        out.paste(t, ((i % 2) * width, (i // 2) * t.height))
    return out


class TooClose(RuntimeError):
    pass


def scout(adapter, locations_path, name=None, at=None, facing=None, clock="12:00", tags=(), note="",
          eye_height=1.6, vfov=60.0, warn_m=25.0, refuse_m=5.0, force=False, log=print):
    adapter.open()
    doc = locs.load(locations_path)
    adapter.publish_locations(doc["locations"])
    if at is not None:
        adapter.go_to(at, facing if facing is not None else adapter.subject_state()["facing_deg"])
    state = adapter.subject_state()
    position = [float(v) for v in adapter.ground_point(state["position"])]
    facing = float(facing if facing is not None else state["facing_deg"])

    near, dist = locs.nearest(doc, adapter.name, position)
    if near is not None:
        msg = "nearest saved location: %s (%s), %.1f m away" % (near["id"], near.get("title") or "untitled", dist)
        if dist < refuse_m and not force:
            raise TooClose(msg + "; not saved (closer than %.0f m; --force to save anyway)" % refuse_m)
        log(("WARNING: " if dist < warn_m else "") + msg)

    if clock:
        clock = adapter.set_clock(clock)
    else:
        clock = state.get("clock")

    loc_id = locs.new_id(doc, adapter.name, name)
    root = os.path.dirname(os.path.abspath(locations_path))
    pdir = os.path.join(root, "previews", loc_id)
    os.makedirs(pdir, exist_ok=True)

    fwd, right, up = (np.asarray(v, dtype=np.float64) for v in adapter.heading_basis(facing))
    eye = np.asarray(position) + up * eye_height
    preview, images = {}, []
    adapter.hide_subject(True)
    try:
        for label, turn in DIRECTIONS:
            d = fwd if turn == 0 else (-fwd if turn == 180 else (-right if turn > 0 else right))
            raw = os.path.join(pdir, label + ".bmp")
            adapter.view(eye, d, up, vfov, raw)
            img = Image.open(raw).convert("RGB")
            jpg = os.path.join(pdir, label + ".jpg")
            img.save(jpg, quality=90)
            os.remove(raw)
            preview[label] = os.path.relpath(jpg, root)
            images.append(img)
    finally:
        adapter.hide_subject(False)
    sheet = os.path.join(pdir, "sheet.jpg")
    _sheet(images, ["%s (heading %.0f)" % (lbl, (facing + t) % 360) for lbl, t in DIRECTIONS]).save(sheet, quality=88)
    preview["sheet"] = os.path.relpath(sheet, root)

    entry = {"id": loc_id, "game": adapter.name, "title": state.get("title"), "position": position,
             "facing_deg": facing, "clock": clock, "tags": list(tags), "note": note, "preview": preview,
             "scene": None, "scouted": now_iso()}
    locs.add(locations_path, entry)
    adapter.publish_locations(locs.load(locations_path)["locations"])
    log("location %s (%s) at %s, facing %.1f; previews in %s" % (
        loc_id, entry["title"] or "untitled", ", ".join("%.2f" % v for v in position), facing, pdir))
    return entry
