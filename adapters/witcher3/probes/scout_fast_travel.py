"""Scouts locations beside the game's fast-travel points (road signs and harbours): known spots on
the ground all over each world, by name, without anyone riding there.

    uv run --project . python -m adapters.witcher3.probes.scout_fast_travel --list [--world skellige]
    uv run --project . python -m adapters.witcher3.probes.scout_fast_travel <point>=<name> [...] [--ahead 6] [--clock 12:00] [--world bob]

--list prints the points of the loaded world (point, title, where the player lands). Each
<point>=<name> (e.g. mulbrydale=mulbrydale-road) moves the player to where that point lands a
traveller, steps --ahead metres the way the traveller then faces (so the sign post is not the
subject) and records a location there with the usual four previews, as `capture scout` does.
--world loads another of the game's worlds first (novigrad: Velen and Novigrad, skellige,
kaer_morhen, prolog_village: White Orchard, wyzima_castle, bob: Toussaint).
"""
import math
import sys

from capture import paths as capture_paths
from capture.scout import TooClose, scout

from ..adapter import Witcher3Adapter
from ..session import parse_kv, vec


def pins(ad):
    out = {}
    for line in ad.sess.cmd("pins", 0, timeout=20).data:
        head, _, title = line.partition(" title=")
        p = parse_kv(head)
        out[p["name"]] = {"type": p["type"], "pos": vec(p["pos"]), "land": vec(p["land"]), "yaw": float(p["yaw"]),
                          "title": title.strip()}
    return out


def arg(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    ahead = float(arg(argv, "--ahead", 6.0))
    clock = arg(argv, "--clock", "12:00")
    world = arg(argv, "--world", None)
    ad = Witcher3Adapter()
    ad.ensure_ready(restart=True)
    ad.open()
    try:
        if world:
            ad.enter_place({"world": world})
        known = pins(ad)
        if "--list" in argv:
            for name, p in sorted(known.items()):
                print("%-34s %-9s %-34s lands at %s" % (name, p["type"], p["title"], ", ".join("%.1f" % v for v in p["land"])))
            print("%d points in %s" % (len(known), ad.subject_state().get("place")))
            return 0
        for spec in [a for a in argv if "=" in a and not a.startswith("--")]:
            point, name = spec.split("=", 1)
            p = known.get(point)
            if p is None:
                print("%s: not a fast-travel point of the loaded world (--list shows them)" % point)
                continue
            land = p["land"] if any(abs(v) > 1e-6 for v in p["land"]) else p["pos"]
            h = math.radians(p["yaw"])
            at = [land[0] - math.sin(h) * ahead, land[1] + math.cos(h) * ahead, land[2] + 0.5]
            try:
                e = scout(ad, capture_paths.LOCATIONS, name=name, at=at, facing=p["yaw"], clock=clock, tags=["fast-travel", point])
                print("%s -> %s at %s" % (point, e["id"], ", ".join("%.2f" % v for v in e["position"])))
            except TooClose as err:
                print("%s: %s" % (point, err))
    finally:
        ad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
