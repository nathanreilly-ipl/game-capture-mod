"""Rig sources, and turning one into poses.

A job names a *rig source*:
    {"kind": "camrig", "path": ..., "digest": <sha256 of the file>, "rig_id": ...}
        a camrig/v1 pose file from the camera-rig repository (or an edited copy)
    {"kind": "solver", ...}
        a solver and its settings, solved per location (not supported yet: BACKLOG.md)

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


def resolve(source, base_dir=None, location=None):
    """The camrig/v1 rig for a source at a location. base_dir resolves relative paths."""
    kind = source.get("kind", "camrig")
    if kind == "camrig":
        path = source["path"]
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        if source.get("digest") and sha256_file(path) != source["digest"]:
            raise ValueError("rig file %s changed since the job was submitted" % path)
        return load_pose_file(path), path
    if kind == "solver":
        raise NotImplementedError("rig solver specs are not supported yet (BACKLOG.md: rig solver format)")
    raise ValueError("unknown rig source kind %r" % kind)
