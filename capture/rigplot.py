"""Top-down and side plans of a solved rig in its scene: scene hits as grey dots (darker = higher),
camera positions by kind, the subject at the circle. For checking a solved rig before a take."""
import numpy as np
from PIL import Image, ImageDraw

COLOURS = {"temporal": (90, 160, 255), "freecam": (120, 220, 140), "moving": (255, 200, 60),
           "spacetime": (255, 120, 60), "sweep": (200, 120, 255), "trajectory": (255, 90, 160)}


def camera_points(rig):
    out = []
    for c in rig["cameras"]:
        m = np.asarray(c["c2w"], float)
        m = m[None] if m.ndim == 2 else m
        out += [(c["kind"], p) for p in m[:, :3, 3]]
    return out


def plan(scene_rig_points, rig, title, half=13.0, size=760):
    """scene_rig_points: scene hits in the rig frame (x, y up, z)."""
    pts = np.asarray(scene_rig_points, float).reshape(-1, 3)
    cams = camera_points(rig)
    img = Image.new("RGB", (2 * size, size + 40), (24, 24, 24))
    d = ImageDraw.Draw(img)
    s = (size - 40) / (2 * half)

    def panel(ox, u, v, vmin):
        def px(a, b):
            return ox + 20 + (a + half) * s, size - 20 - (b - vmin) * s
        for g in np.arange(-int(half), int(half) + 1, 1.0):
            x0, _ = px(g, vmin)
            d.line([(x0, 20), (x0, size - 20)], fill=(38, 38, 38))
            _, y0 = px(-half, g + vmin + half) if False else px(-half, g)
            d.line([(ox + 20, y0), (ox + size - 20, y0)], fill=(38, 38, 38))
        return px

    top = panel(0, 0, 2, -half)
    side = panel(size, 0, 1, -1.0)
    keep = (np.abs(pts[:, 0]) < half) & (np.abs(pts[:, 2]) < half) & (pts[:, 1] > 0.15)
    for p in pts[keep]:
        g = int(np.clip(200 - p[1] * 15, 70, 200))
        x, y = top(p[0], -p[2])
        d.point((x, y), fill=(g, g, g))
    for p in pts[(np.abs(pts[:, 0]) < half) & (np.abs(pts[:, 1]) < 2 * half)]:
        x, y = side(p[0], p[1])
        d.point((x, y), fill=(110, 110, 110))
    for kind in ("sweep", "trajectory", "moving", "spacetime", "freecam", "temporal"):
        r = 3 if kind in ("temporal", "freecam") else 1
        for k, p in cams:
            if k != kind:
                continue
            for f, (a, b) in ((top, (p[0], -p[2])), (side, (p[0], p[1]))):
                x, y = f(a, b)
                d.ellipse([x - r, y - r, x + r, y + r], fill=COLOURS.get(kind, (235, 235, 235)))
    for f in (top, side):
        x, y = f(0, 0)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 255), width=2)
    d.text((8, 4), "top view, 1 m grid: " + title, fill=(235, 235, 235))
    d.text((size + 8, 4), "side view (x, height)", fill=(235, 235, 235))
    x = 10
    for kind, c in COLOURS.items():
        d.rectangle([x, size + 14, x + 12, size + 26], fill=c)
        d.text((x + 18, size + 14), kind, fill=(235, 235, 235))
        x += 140
    d.text((x, size + 14), "grey: scene (darker = higher)", fill=(200, 200, 200))
    return img
