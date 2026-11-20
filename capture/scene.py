"""The scene around a location, as triangles, for solving rigs per location (capture/solver.py).

Any adapter with the "raycast" capability can provide it: rays are cast from several points
around the location (the ground point, and rings around it at a few heights) in every
direction; each hit becomes a small square patch facing the surface normal. The rig solver
voxelises these triangles with its own clearance (25 cm for ST-DM), so patches spaced closer
than about half a metre read as a closed surface.

What the rays stop at is the adapter's choice; for RDR2: terrain, buildings, objects, glass and
foliage, not people, animals or vehicles (the obstacle check handles those at capture time).

Scenes are cached per location and parameters: out/locations/scenes/<location>_<hash>.npz
(+ .obj to look at).
"""
import math
import os

import numpy as np

from .util import digest_json

DEFAULTS = {
    "radius_m": 14.0,        # how far around the location the scene is sampled (ST-DM far ring <= 11.5 m)
    "rays_per_origin": 6000,
    "patch_m": 0.3,          # side of the square patch per hit
}
# Ray origins: (horizontal distance from the location, height above the ground, count around)
ORIGINS = [(0.0, 0.5, 1), (0.0, 1.6, 1), (0.0, 3.0, 1), (3.0, 1.6, 4), (7.0, 2.0, 4)]


def fibonacci_dirs(n):
    i = np.arange(n) + 0.5
    z = 1 - 2 * i / n
    r = np.sqrt(1 - z * z)
    a = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([r * np.cos(a), r * np.sin(a), z], axis=1)


def ray_pattern(ground, radius, rays_per_origin, up=(0, 0, 1), horizontal=((1, 0, 0), (0, 1, 0))):
    """(origins, ends) for rays around a ground point. up/horizontal: the world's axes."""
    ground, up = np.asarray(ground, float), np.asarray(up, float)
    hx, hy = (np.asarray(v, float) for v in horizontal)
    dirs = fibonacci_dirs(rays_per_origin)
    dirs = dirs[:, :1] * hx + dirs[:, 1:2] * hy + dirs[:, 2:3] * up
    starts, ends = [], []
    for dist, height, count in ORIGINS:
        for k in range(count):
            a = 2 * math.pi * k / count
            o = ground + up * height + dist * (math.cos(a) * hx + math.sin(a) * hy)
            starts.append(np.repeat(o[None], len(dirs), 0))
            ends.append(o + dirs * radius)
    return np.concatenate(starts), np.concatenate(ends)


def patches(points, normals, size):
    """Two triangles per point: a square of side `size` centred on it, facing its normal."""
    p, n = np.asarray(points, float), np.asarray(normals, float)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    ref = np.where(np.abs(n[:, 2:3]) < 0.9, [[0.0, 0.0, 1.0]], [[1.0, 0.0, 0.0]])
    u = np.cross(n, ref)
    u /= np.maximum(np.linalg.norm(u, axis=1, keepdims=True), 1e-9)
    v = np.cross(n, u)
    h = size / 2
    c = [p + h * (su * u + sv * v) for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return np.concatenate([np.stack([c[0], c[1], c[2]], 1), np.stack([c[0], c[2], c[3]], 1)])


def capture(adapter, location, params=None, log=print):
    """Rays around the location; returns {"points", "normals"} (world) and the parameters."""
    prm = dict(DEFAULTS, **(params or {}))
    adapter.go_to(location["position"], location.get("facing_deg", 0.0))
    ground = adapter.ground_point(location["position"])
    fwd, right, up = adapter.heading_basis(0.0)  # the game's axes
    starts, ends = ray_pattern(ground, prm["radius_m"], int(prm["rays_per_origin"]), up=up, horizontal=(right, fwd))
    hit, points, normals = adapter.raycast(starts, ends)
    log("scene: %d rays, %d hits within %.0f m of %s" % (len(starts), int(hit.sum()), prm["radius_m"], location["id"]))
    return {"points": points[hit], "normals": normals[hit], "ground": np.asarray(ground), "params": prm}


def cache_path(cache_dir, location, params):
    prm = dict(DEFAULTS, **(params or {}))
    key = digest_json({"position": location["position"], "params": prm, "origins": ORIGINS})[:10]
    return os.path.join(cache_dir, "%s_%s.npz" % (location["id"], key))


def load_or_capture(adapter, location, cache_dir, params=None, log=print):
    path = cache_path(cache_dir, location, params)
    if os.path.exists(path):
        d = np.load(path)
        log("scene: cached %s (%d hits)" % (os.path.basename(path), len(d["points"])))
        return {"points": d["points"], "normals": d["normals"], "ground": d["ground"], "path": path}
    sc = capture(adapter, location, params, log=log)
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(path, points=sc["points"], normals=sc["normals"], ground=sc["ground"])
    write_obj(path[:-4] + ".obj", patches(sc["points"], sc["normals"], dict(DEFAULTS, **(params or {}))["patch_m"]))
    sc["path"] = path
    return sc


def to_rig_frame(points_or_tris, origin, rotation):
    """World -> rig frame: rig = R^T (world - origin) (capture/placement.py)."""
    a = np.asarray(points_or_tris, float)
    return (a - np.asarray(origin, float)) @ np.asarray(rotation, float)


def write_obj(path, tris):
    with open(path, "w", encoding="utf-8") as f:
        for t in tris:
            for v in t:
                f.write("v %.4f %.4f %.4f\n" % tuple(v))
        for i in range(len(tris)):
            f.write("f %d %d %d\n" % (3 * i + 1, 3 * i + 2, 3 * i + 3))
