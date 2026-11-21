"""The camera-rig repository's rigs (gamecapture-camera-rigs-huixin), solved per location with
that repository's own rules against the scene there: a ring lifted or shrunk, a blocked group
dropped, the location declined, as its docs/SCENE_FIT.md describes.

    capture submit --provider camrigs --set rig=yiming_stdm      (or the shortcut --solver yiming_stdm)

Optional: needs a checkout of that repository, found in this order:
    CAMRIGS_REPO (environment), third_party/gamecapture-camera-rigs-huixin (a git submodule of
    this repository), ~/repos/gamecapture-camera-rigs-huixin
The job records the checkout's commit (the provider version); a worker whose checkout is at
another commit refuses the job.

No-performer captures need no SMPL-X model: the ST-DM (yiming_stdm) and Diverse (zehao_traj)
rules read only the performer's bounding box and pelvis track, so the subject is a static
stand-in box. With the demo performer's box and an open floor this reproduces the demo rig file
exactly (286 + 1 cameras, poses within 1e-5; checked 2026-11-20). Other rigs of that repository
(hemisphere, chaowei_v2) test the performer's silhouette and are not checked with a stand-in.

Folded rigs (zehao_traj's Diverse trajectory into yiming_stdm) join the main rig as one more
group, as that repository's tools/build_web_data.py does.

qc(): the repository's qc/stdm_view.py on the packaged take (needs the temporal ring).
"""
import os
import subprocess
import sys

import numpy as np

from capture.paths import REPO
from capture.providers import Declined

KEY = "camrigs"
TITLE = "Rigs of the camera-rig repository, solved per location (ST-DM + Diverse by default)"
NEEDS_SCENE = True
DEFAULTS = {"rig": "yiming_stdm", "fold": None, "seed": 1234, "key": "demo", "rule": "unreal"}
FOLDS = {"yiming_stdm": ["zehao_traj"]}
REPO_NAME = "gamecapture-camera-rigs-huixin"


def repo_path():
    for p in (os.environ.get("CAMRIGS_REPO"), os.path.join(REPO, "third_party", REPO_NAME),
              os.path.join(os.path.expanduser("~"), "repos", REPO_NAME)):
        if p and os.path.isdir(os.path.join(p, "camrigs")):
            return os.path.abspath(p)
    return None


def demo_rig_file():
    p = repo_path()
    return os.path.join(p, "web", "data", "demo", "rig_yiming_stdm.json") if p else None


def _commit(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def available(settings):
    p = repo_path()
    if not p:
        return False, "no checkout of %s (CAMRIGS_REPO, third_party/%s or ~/repos/%s)" % (REPO_NAME, REPO_NAME, REPO_NAME)
    if not _commit(p):
        return False, "%s is not a git checkout (git needed for the version)" % p
    return True, p


def version(settings):
    p = repo_path()
    return "camrigs@%s" % (_commit(p) if p else "missing")


def _import():
    p = repo_path()
    if p not in sys.path:
        sys.path.insert(0, p)
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


def solve(scene, subject, settings):
    rigs, scene_mod, scenefit, Context, Person = _import()
    person = standin(Person, subject["height_m"], subject["radius_m"], int(subject.get("frames", 120)),
                     float(subject.get("fps", 30.0)))
    if scene is None:
        sc = scene_mod.floor_plane()
    else:
        tris = np.asarray(scene.triangles, float).reshape(-1, 3, 3)
        sc = scene_mod.Scene(tris, settings.get("rule", "unreal"), scene.name, {"kind": "game rays", "triangles": len(tris)})
    ctx = Context([person], sc, seed=int(settings["seed"]), key=settings["key"], fps=float(subject.get("fps", 30.0)))
    main = settings["rig"]
    fold = settings["fold"] if settings.get("fold") is not None else FOLDS.get(main, [])
    docs = {}
    for k in [main] + list(fold):
        docs[k] = rigs.get(k).solve(ctx)
        docs[k]["record"]["scene_fit"] = scenefit.summarize(k, docs[k], sc)
    doc = docs.pop(main)
    for k, src in docs.items():  # as tools/build_web_data.py folds
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
    if doc["record"].get("declined") or not doc["cameras"]:
        raise Declined("; ".join(effects) or "declined")
    return doc


def qc(package_dir, rig, take):
    """The repository's ST-DM reader (qc/stdm_view.py) on the package: it reads every camera and
    builds the 3D view's data (qc_view.json, qc_row.json next to the package)."""
    labels = os.listdir(package_dir)
    if not any("TemporalCam" in name for name in labels):
        return {"ok": None, "message": "skipped: stdm_view.py needs the temporal ring, not in this take"}
    tool = os.path.join(repo_path(), "qc", "stdm_view.py")
    name = os.path.basename(os.path.dirname(os.path.abspath(package_dir)))
    r = subprocess.run([sys.executable, "-I", tool, package_dir, "--game", (take.get("game") or "game").upper(),
                        "--name", name], capture_output=True, text=True, cwd=os.path.dirname(tool))
    out = (r.stdout + r.stderr).strip().splitlines()
    return {"ok": r.returncode == 0, "message": out[-1] if out else "", "tool": "qc/stdm_view.py"}
