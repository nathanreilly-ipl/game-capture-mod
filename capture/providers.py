"""Rig providers: every rig format behind one contract, so anyone can add one.

A provider is one Python file (rigs/README.md has the full contract):

    KEY = "ring"                      unique name; the CLI and jobs refer to it
    TITLE = "..."
    DEFAULTS = {...}                  its settings and their defaults (optional)
    NEEDS_SCENE = True                False: solve() gets scene=None and no scene is captured
    def solve(scene, subject, settings) -> dict
        the camrig/v1 rig for this location; raise Declined(reason) to refuse the location
    def version(settings) -> str      optional; default: a hash of the provider file
    def available(settings) -> (bool, str)   optional: can it run here? (e.g. an external repo)
    def freeze(settings, store) -> dict      optional, at submit: make settings self-contained
                                             (e.g. copy a file into the queue's store folder)
    def qc(package_dir, rig, take) -> dict   optional, after packaging:
                                             {"ok": True | False | None, "message": ..., ...}

Where providers are found, first match wins:
    a path given explicitly (--provider path/to/my_rig.py)
    the folders in CAPTURE_RIG_PATH (separated by os.pathsep)
    rigs/ in this repository (formats added by pull request)

A job's rig source:
    {"kind": "provider", "provider": KEY, "version": ..., "settings": {...},
     "subject": {...}, "scene": {...}, "rig_id": ..., "digest": ...,
     "provider_copy": "providers/<key>_<hash>.py"}   (a single-file provider from outside the
                                                       repo, copied into the queue at submit)
Workers find the provider by key (or use the copy) and refuse to run if its version differs.

The scene every provider gets (capture/scene.py): triangles and ray hits around the location in
the rig frame: metres, +Y up, the location's ground at y = 0, the subject at the origin facing +Z.
"""
import hashlib
import importlib.util
import os
import shutil

from .paths import REPO
from .util import digest_json, sha256_file

REPO_RIGS = os.path.join(REPO, "rigs")
# The stand-in subject for no-performer captures: the demo performer's bounding box (camera-rig
# repository, web/data/demo/rig_yiming_stdm.json record).
DEFAULT_SUBJECT = {"height_m": 1.99644, "radius_m": 0.53387, "frames": 120, "fps": 30.0}


class Declined(RuntimeError):
    """A provider's rules refuse this location (e.g. no near ring fits): the take is not rendered."""


class Scene:
    """The scene around a location in the rig frame (see the module docstring)."""

    def __init__(self, triangles, points, normals, name, info=None):
        self.triangles, self.points, self.normals = triangles, points, normals
        self.name, self.info = name, dict(info or {})


def search_path(extra=None):
    paths = list(extra or [])
    paths += [p for p in os.environ.get("CAPTURE_RIG_PATH", "").split(os.pathsep) if p]
    paths.append(REPO_RIGS)
    return paths


_LOADED = {}


def load_file(path):
    """Imports a provider file (cached per path and content)."""
    path = os.path.abspath(path)
    key = (path, sha256_file(path))
    if key not in _LOADED:
        name = "capture_rig_provider_%s" % hashlib.sha1(path.encode()).hexdigest()[:10]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for attr in ("KEY", "solve"):
            if not hasattr(mod, attr):
                raise ValueError("%s is not a rig provider (no %s)" % (path, attr))
        mod.__provider_file__ = path
        _LOADED[key] = mod
    return _LOADED[key]


def candidates(extra=None):
    """Every provider file on the search path: [(path)]; files starting with _ are skipped."""
    out = []
    for d in search_path(extra):
        if os.path.isfile(d) and d.endswith(".py"):
            out.append(d)
        elif os.path.isdir(d):
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".py") and not f.startswith("_")]
    return out


def find(key_or_path, extra=None):
    """The provider module for a key on the search path, or for a file path."""
    if key_or_path.endswith(".py") and os.path.isfile(key_or_path):
        return load_file(key_or_path)
    for p in candidates(extra):
        try:
            mod = load_file(p)
        except Exception:
            continue
        if mod.KEY == key_or_path:
            return mod
    raise KeyError("no rig provider %r (looked in: %s)" % (key_or_path, ", ".join(search_path(extra))))


def listing(extra=None):
    out = []
    for p in candidates(extra):
        try:
            mod = load_file(p)
        except Exception as e:
            out.append({"key": None, "file": p, "error": "%s: %s" % (type(e).__name__, e)})
            continue
        ok, why = available(mod, settings_for(mod, {}))
        out.append({"key": mod.KEY, "title": getattr(mod, "TITLE", ""), "file": p, "available": ok, "why": why})
    return out


def settings_for(mod, settings):
    return dict(getattr(mod, "DEFAULTS", {}), **(settings or {}))


def available(mod, settings):
    fn = getattr(mod, "available", None)
    return fn(settings) if fn else (True, "")


def version(mod, settings):
    fn = getattr(mod, "version", None)
    return fn(settings) if fn else "file-" + sha256_file(mod.__provider_file__)[:16]


def is_in_repo(mod):
    return os.path.dirname(os.path.abspath(mod.__provider_file__)) == os.path.abspath(REPO_RIGS)


def make_source(key_or_path, settings=None, subject=None, scene=None, store=None, extra=None):
    """A job's rig source for a provider. store: the queue folder that keeps submitted files
    (a provider file from outside the repo, files the provider freezes)."""
    mod = find(key_or_path, extra)
    st = settings_for(mod, settings)
    ok, why = available(mod, st)
    if not ok:
        raise RuntimeError("rig provider %s cannot run here: %s" % (mod.KEY, why))
    if hasattr(mod, "freeze") and store:
        st = mod.freeze(st, store)
    src = {"kind": "provider", "provider": mod.KEY, "version": version(mod, st), "settings": st,
           "subject": dict(DEFAULT_SUBJECT, **(subject or {})), "scene": dict(scene or {})}
    if store and not is_in_repo(mod):
        rel = os.path.join("providers", "%s_%s.py" % (mod.KEY, sha256_file(mod.__provider_file__)[:10]))
        os.makedirs(os.path.join(store, "providers"), exist_ok=True)
        shutil.copyfile(mod.__provider_file__, os.path.join(store, rel))
        src["provider_copy"] = rel.replace(os.sep, "/")
    src["digest"] = digest_json({k: v for k, v in src.items() if k != "provider_copy"})
    label = "-".join(str(p) for p in (mod.KEY, st.get("rig")) if p)
    src["rig_id"] = "%s-%s" % (label, src["digest"][:8])
    return src


def load_for_source(source, base_dir=None, extra=None):
    """The provider a job's rig source names, checked against the version it was submitted with."""
    if source.get("provider_copy") and base_dir:
        mod = load_file(os.path.join(base_dir, source["provider_copy"]))
    else:
        mod = find(source["provider"], extra)
    have = version(mod, source["settings"])
    if have != source["version"]:
        raise RuntimeError("rig provider %s is at version %s here, the job was submitted with %s"
                           % (mod.KEY, have, source["version"]))
    return mod
