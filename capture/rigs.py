"""Rig sources, and turning one into poses.

A job names a *rig source*:
    {"kind": "camrig", "path": ..., "digest": <sha256 of the file>, "rig_id": ...}
        a camrig/v1 pose file from the camera-rig repository (or an edited copy)
    {"kind": "solver", "solver": "yiming_stdm", ..., "rig_id": ...}
        the camera-rig repository's rules for a rig, solved per location against the scene
        captured there (capture/solver.py, capture/scene.py)

resolve() turns any source into a camrig/v1 rig for the location, so everything after it
(placement, shot list, capture, packaging) only ever sees poses.
"""
import os

from .util import read_json, sha256_file

POSE_SCHEMA = "camrig/v1"


def rig_id(rig, digest):
    """Names an exact rig file: its key plus a short content hash, so an edited copy of a
    rig is a different rig."""
    return "%s-%s" % (rig.get("rig", "rig"), digest[:8])


def load_pose_file(path):
    rig = read_json(path)
    if rig.get("schema") != POSE_SCHEMA:
        raise ValueError("%s is not a %s rig (schema %r)" % (path, POSE_SCHEMA, rig.get("schema")))
    if rig.get("camera_convention") not in (None, "opencv_c2w"):
        raise ValueError("unsupported camera convention %r" % rig.get("camera_convention"))
    return rig


def source_for_file(path):
    rig = load_pose_file(path)
    digest = sha256_file(path)
    return {"kind": "camrig", "path": os.path.abspath(path), "digest": digest, "rig_id": rig_id(rig, digest),
            "rig": rig.get("rig"), "title": rig.get("title")}


def resolve(source, base_dir=None, location=None, adapter=None, out_dir=None, scene_dir=None, log=print):
    """The camrig/v1 rig for a source at a location, and the path of its file. base_dir resolves
    relative paths. A solver source needs the adapter (to capture the scene around the location)
    and writes the solved rig to out_dir/<rig id>/<location>.json (reused when it exists)."""
    kind = source.get("kind", "camrig")
    if kind == "camrig":
        path = source["path"]
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        if source.get("digest") and sha256_file(path) != source["digest"]:
            raise ValueError("rig file %s changed since the job was submitted" % path)
        return load_pose_file(path), path
    if kind == "solver":
        from . import scene, solver
        from .util import write_json
        if adapter is None or location is None or out_dir is None:
            raise ValueError("a solver rig source needs the game adapter, the location and an output folder")
        path = os.path.join(out_dir, source["rig_id"], "%s.json" % location["id"])
        if os.path.exists(path):
            log("solver: reusing %s" % path)
            return load_pose_file(path), path
        sc = scene.load_or_capture(adapter, location, scene_dir or os.path.join(out_dir, "scenes"),
                                   source.get("scene"), log=log)
        origin = adapter.ground_point(location["position"])
        R = adapter.rig_rotation(location.get("facing_deg", 0.0))
        tris = scene.patches(sc["points"], sc["normals"], dict(scene.DEFAULTS, **source.get("scene", {}))["patch_m"])
        doc = solver.solve(source, scene.to_rig_frame(tris, origin, R), "%s (%s)" % (location["id"], adapter.name),
                           log=log)
        doc["record"]["solved_for"]["location"] = {k: location.get(k) for k in ("id", "position", "facing_deg")}
        doc["record"]["solved_for"]["scene_file"] = sc.get("path")
        write_json(path, doc, indent=None)
        log("solver: %d cameras, written to %s" % (len(doc["cameras"]), path))
        return doc, path
    raise ValueError("unknown rig source kind %r" % kind)
