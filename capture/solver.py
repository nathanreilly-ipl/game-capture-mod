"""Rigs solved per location: the camera-rig repository's own rules, run against the scene
around the location (capture/scene.py), so a ring is lifted or shrunk, a blocked group dropped,
or the location declined exactly as the rig's documentation says (docs/SCENE_FIT.md there).

A solver spec (a job's rig source of kind "solver"):
    {"kind": "solver", "solver": "yiming_stdm", "fold": ["zehao_traj"],
     "repo": <path to gamecapture-camera-rigs-huixin>, "commit": <its git commit at submit>,
     "seed": 1234, "key": "demo", "rule": "unreal",
     "subject": {"height_m": 1.99644, "radius_m": 0.53387, "frames": 120},
     "scene": {...capture/scene.py DEFAULTS overrides...}}

No-performer captures need no SMPL-X model: the ST-DM and Diverse rules read only the
performer's bounding box over the clip and its pelvis track, so the subject is a static stand-in
box. With the demo performer's box (the default) and an open floor, the solve reproduces the
demo rig file exactly (286 + 1 cameras, poses within 1e-5; checked 2026-11-20).
Folded rigs (zehao_traj's Diverse trajectory) join the main rig as one more group, as the rig
repository's tools/build_web_data.py does.
"""
import os
import subprocess
import sys

import numpy as np

from .util import digest_json

DEFAULT_REPO = os.environ.get("CAMRIGS_REPO") or os.path.join(os.path.expanduser("~"), "repos",
                                                              "gamecapture-camera-rigs-huixin")
DEFAULT_SUBJECT = {"height_m": 1.99644, "radius_m": 0.53387, "frames": 120}  # the demo performer
FOLDS = {"yiming_stdm": ["zehao_traj"]}


class Declined(RuntimeError):
    """The rig's rules decline this location (e.g. no near ring fits): the take is not rendered."""


def repo_commit(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("not a git checkout: %s" % repo)
    return r.stdout.strip()


def make_spec(solver="yiming_stdm", seed=1234, key="demo", rule="unreal", subject=None, scene=None, repo=None):
    repo = os.path.abspath(repo or DEFAULT_REPO)
    return {"kind": "solver", "solver": solver, "fold": FOLDS.get(solver, []), "repo": repo,
            "commit": repo_commit(repo), "seed": seed, "key": key, "rule": rule,
            "subject": dict(DEFAULT_SUBJECT, **(subject or {})), "scene": dict(scene or {})}


def spec_id(spec):
    keep = {k: v for k, v in spec.items() if k not in ("repo", "rig_id", "digest")}
    return "%s-solved-%s" % (spec["solver"], digest_json(keep)[:8])


def _import(spec):
    repo = spec["repo"]
    have = repo_commit(repo)
    if spec.get("commit") and have != spec["commit"]:
        raise RuntimeError("rig repository is at %s, the job was submitted at %s" % (have[:10], spec["commit"][:10]))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from camrigs import rigs, scene, scenefit  # noqa: E402
    from camrigs.context import Context  # noqa: E402
    from camrigs.people import Person  # noqa: E402
    return rigs, scene, scenefit, Context, Person


def standin(Person, height, radius, frames=120, fps=30.0):
    """A static box the size of a performer, standing at the origin facing +Z."""
    corners = np.array([[x, y, z] for x in (-radius, radius) for y in (0.0, height) for z in (-radius, radius)])
    verts = np.repeat(corners[None], frames, axis=0)
    pelvis = np.array([0.0, height * 0.5, 0.0])
    joints = np.repeat(np.repeat(pelvis[None, None], 55, axis=1), frames, axis=0)
    fwd = np.repeat(np.array([[0.0, 0.0, 1.0]]), frames, axis=0)
    return Person(name="standin", verts=verts, joints=joints, root=joints[:, 0].copy(), root_fwd=fwd, fps=fps,
                  source={"standin": {"height_m": height, "radius_m": radius}})


def solve(spec, triangles_rig, scene_name, log=print):
    """The camrig/v1 rig for this scene (triangles in the rig frame: metres, +Y up, the location's
    ground at y = 0). Raises Declined if the rules decline it."""
    rigs, scene_mod, scenefit, Context, Person = _import(spec)
    subj = dict(DEFAULT_SUBJECT, **spec.get("subject", {}))
    person = standin(Person, subj["height_m"], subj["radius_m"], int(subj.get("frames", 120)))
    tris = np.asarray(triangles_rig, float).reshape(-1, 3, 3)
    sc = scene_mod.Scene(tris, spec.get("rule", "unreal"), scene_name, {"kind": "game rays", "triangles": len(tris)})
    ctx = Context([person], sc, seed=int(spec.get("seed", 1234)), key=spec.get("key", "demo"), fps=30.0)
    docs = {}
    for k in [spec["solver"]] + list(spec.get("fold", [])):
        docs[k] = rigs.get(k).solve(ctx)
        docs[k]["record"]["scene_fit"] = scenefit.summarize(k, docs[k], sc)
    doc = docs.pop(spec["solver"])
    for k, src in docs.items():  # fold, as tools/build_web_data.py does
        f = getattr(rigs.get(k), "WEB_FOLD", {}) or {}
        for c in src["cameras"]:
            c["group"] = f.get("group", k)
        doc["cameras"] += src["cameras"]
        doc["title"] = f.get("title", doc["title"])
        doc["owner"] = "%s + %s" % (doc["owner"], src["owner"])
        sub, fit = src["record"].pop("scene_fit", None), doc["record"].get("scene_fit")
        if sub and fit and sub.get("effects"):
            fit["effects"] += ["%s: %s" % (f.get("group", k), e) for e in sub["effects"]]
        doc["record"][k] = src["record"]
    effects = doc["record"].get("scene_fit", {}).get("effects", [])
    for e in effects:
        log("solver: %s" % e)
    if doc["record"].get("declined") or not doc["cameras"]:
        raise Declined("; ".join(effects) or "declined")
    doc["record"]["solved_for"] = {"scene": scene_name, "spec": {k: v for k, v in spec.items() if k != "repo"}}
    return doc
