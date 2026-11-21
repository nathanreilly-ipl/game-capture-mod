"""A camrig/v1 pose file, used as it is at every location (no scene fit).

    capture submit --rig path/to/rig.json           (shortcut)
    capture submit --provider file --set path=path/to/rig.json

At submit the file is copied into the queue (settings path becomes relative to it), so the
job keeps exactly the rig it was submitted with.
"""
import os
import shutil

from capture.rigs import load_pose_file
from capture.util import sha256_file

KEY = "file"
TITLE = "A camrig/v1 pose file, used as it is"
NEEDS_SCENE = False
DEFAULTS = {"path": None}


def available(settings):
    p = settings.get("path")
    return (True, "") if not p or os.path.exists(p) or settings.get("_frozen") else (False, "no file %s" % p)


def freeze(settings, store):
    path = settings["path"]
    if not path:
        raise ValueError("the file provider needs --set path=<camrig/v1 file>")
    rig = load_pose_file(path)
    digest = sha256_file(path)
    rel = os.path.join("rigs", "%s-%s.json" % (rig.get("rig", "rig"), digest[:8]))
    os.makedirs(os.path.join(store, "rigs"), exist_ok=True)
    if not os.path.exists(os.path.join(store, rel)):
        shutil.copyfile(path, os.path.join(store, rel))
    return dict(settings, path=rel.replace(os.sep, "/"), sha256=digest, rig=rig.get("rig"), _frozen=True)


def solve(scene, subject, settings):
    path = settings["path"]
    if not os.path.isabs(path):
        path = os.path.join(settings.get("_base_dir") or "", path)
    if settings.get("sha256") and sha256_file(path) != settings["sha256"]:
        raise ValueError("rig file %s changed since the job was submitted" % path)
    return load_pose_file(path)
