"""Rig sources, and turning one into poses.

A job names a rig source: a rig provider (capture/providers.py, rigs/README.md), its version
and settings. resolve() asks the provider for the camrig/v1 rig at the job's location, giving
it the scene there (captured with rays, capture/scene.py) when the provider wants one, so
everything after it (placement, shot list, capture, packaging) only ever sees poses.
"""
import os

from .util import read_json, write_json

POSE_SCHEMA = "camrig/v1"


def load_pose_file(path):
    rig = read_json(path)
    if rig.get("schema") != POSE_SCHEMA:
        raise ValueError("%s is not a %s rig (schema %r)" % (path, POSE_SCHEMA, rig.get("schema")))
    if rig.get("camera_convention") not in (None, "opencv_c2w"):
        raise ValueError("unsupported camera convention %r" % rig.get("camera_convention"))
    return rig


def _upgrade(source):
    """Rig sources of the two kinds jobs used before providers existed (2026-11-20)."""
    kind = source.get("kind", "camrig")
    if kind == "camrig":
        return dict(source, kind="legacy_file")
    if kind == "solver":
        raise ValueError("this job uses the old solver rig source; submit it again (--solver / --provider camrigs)")
    return source


def scene_for(adapter, location, params, scene_dir, log=print):
    """The location's scene in the rig frame (capture/providers.Scene)."""
    from . import scene
    from .providers import Scene
    sc = scene.load_or_capture(adapter, location, scene_dir, params, log=log)
    origin = adapter.ground_point(location["position"])
    R = adapter.rig_rotation(location.get("facing_deg", 0.0))
    patch = dict(scene.DEFAULTS, **(params or {}))["patch_m"]
    tris = scene.to_rig_frame(scene.patches(sc["points"], sc["normals"], patch), origin, R)
    pts = scene.to_rig_frame(sc["points"], origin, R)
    nrm = (sc["normals"] @ R) if len(sc["normals"]) else sc["normals"]
    return Scene(tris, pts, nrm, "%s (%s)" % (location["id"], adapter.name),
                 {"file": sc.get("path"), "hits": int(len(sc["points"]))})


def resolve(source, base_dir=None, location=None, adapter=None, out_dir=None, scene_dir=None, log=print):
    """The camrig/v1 rig for a job's rig source at its location, and the path of its file
    (out_dir/<rig id>/<location>.json, reused when it exists)."""
    from . import providers
    source = _upgrade(source)
    if source["kind"] == "legacy_file":
        path = source["path"]
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        return load_pose_file(path), path
    if out_dir is None or location is None:
        raise ValueError("resolving a rig needs the location and an output folder")
    path = os.path.join(out_dir, source["rig_id"], "%s.json" % location["id"])
    if os.path.exists(path):
        log("rig %s: reusing %s" % (source["rig_id"], path))
        return load_pose_file(path), path
    mod = providers.load_for_source(source, base_dir)
    settings = dict(source["settings"], _base_dir=base_dir)
    scene = None
    if getattr(mod, "NEEDS_SCENE", True):
        if adapter is None or "raycast" not in adapter.capabilities:
            raise ValueError("rig provider %s needs the scene, and the game adapter cannot cast rays" % mod.KEY)
        scene = scene_for(adapter, location, source.get("scene"), scene_dir or os.path.join(out_dir, "scenes"), log=log)
    doc = mod.solve(scene, source["subject"], settings)
    if doc.get("schema") != POSE_SCHEMA:
        raise ValueError("rig provider %s returned %r, not a %s rig" % (mod.KEY, doc.get("schema"), POSE_SCHEMA))
    for e in doc.get("record", {}).get("scene_fit", {}).get("effects", []):
        log("rig %s: %s" % (mod.KEY, e))
    doc.setdefault("record", {})["provided_by"] = {
        "provider": mod.KEY, "version": source["version"],
        "settings": {k: v for k, v in source["settings"].items() if not k.startswith("_")},
        "subject": source["subject"], "location": {k: location.get(k) for k in ("id", "position", "facing_deg")},
        "scene": scene.info if scene else None}
    write_json(path, doc, indent=None)
    log("rig %s: %d cameras, written to %s" % (source["rig_id"], len(doc["cameras"]), path))
    return doc, path
