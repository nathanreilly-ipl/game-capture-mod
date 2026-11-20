"""The list of capture locations.

    {"schema": "capture_locations/v1", "locations": [
        {"id": "rdr2-lakeshore-001", "game": "rdr2",
         "title": "Lake Don Julio · Rio Bravo · New Austin",   readable place name from the game, if any
         "position": [x, y, z],          ground point under the subject, world frame
         "facing_deg": 0.0,              the subject's facing, the game's heading convention
         "clock": "12:00",               time of day of the previews (jobs may override)
         "tags": ["open"], "note": "",
         "preview": {"front": ..., "right": ..., "back": ..., "left": ..., "sheet": ...},
                                          paths relative to the locations file
         "scene": null,                   reserved: scene data for solved rigs (BACKLOG.md)
         "scouted": "<iso time>"}]}
"""
import os

from .util import read_json, slug, write_json

SCHEMA = "capture_locations/v1"


def load(path):
    if not os.path.exists(path):
        return {"schema": SCHEMA, "locations": []}
    doc = read_json(path)
    if doc.get("schema") != SCHEMA:
        raise ValueError("%s is not a %s file" % (path, SCHEMA))
    return doc


def save(path, doc):
    write_json(path, doc)


def get(path, location_id):
    for loc in load(path)["locations"]:
        if loc["id"] == location_id:
            return loc
    raise KeyError("no location %r in %s" % (location_id, path))


def nearest(doc, game, position, exclude=None):
    """(location, distance in world units) of the nearest saved location of this game, or (None, inf)."""
    best, best_d = None, float("inf")
    for loc in doc["locations"]:
        if loc.get("game") != game or loc["id"] == exclude:
            continue
        d = sum((a - b) ** 2 for a, b in zip(loc["position"], position)) ** 0.5
        if d < best_d:
            best, best_d = loc, d
    return best, best_d


def new_id(doc, game, name=None):
    base = "%s-%s" % (game, slug(name or "loc"))
    taken = {loc["id"] for loc in doc["locations"]}
    n = 1
    while "%s-%03d" % (base, n) in taken:
        n += 1
    return "%s-%03d" % (base, n)


def add(path, entry):
    doc = load(path)
    if any(loc["id"] == entry["id"] for loc in doc["locations"]):
        raise ValueError("location %r exists" % entry["id"])
    doc["locations"].append(entry)
    save(path, doc)
    return entry
