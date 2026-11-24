"""Scouts locations at the game's named places (places.py: the developers' town portals: squares,
pubs, castles, mills, camps), by name, without anyone riding there.

    uv run --project . python -m adapters.kcd.probes.scout_places --list
    uv run --project . python -m adapters.kcd.probes.scout_places "Rataje - middle pub=rattay-middle-pub" [...] [--ahead 4] [--clock 12:00]

--list prints the places (their name in the game's file, a title, the position). Each
<place>=<name> moves the player to that place, --ahead metres north of it if asked (so a door or
sign is not the subject), and records a location there with the usual four previews, as
`capture scout` does.
"""
import sys

from capture import paths as capture_paths
from capture.scout import TooClose, scout

from .. import places
from ..adapter import KcdAdapter


def arg(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv):
    ahead = float(arg(argv, "--ahead", 0.0))
    clock = arg(argv, "--clock", "12:00")
    known = {p["name"]: p for p in places.load()}
    if "--list" in argv:
        for p in known.values():
            print("%-36s %-36s %s" % (p["name"], p["title"], ", ".join("%.1f" % v for v in p["position"])))
        print("%d places" % len(known))
        return 0
    ad = KcdAdapter()
    ad.ensure_ready(restart=True)
    ad.open()
    try:
        for spec in [a for a in argv if "=" in a and not a.startswith("--")]:
            place, name = spec.split("=", 1)
            p = known.get(place)
            if p is None:
                print("%s: not a named place (--list shows them)" % place)
                continue
            at = [p["position"][0], p["position"][1] + ahead, p["position"][2] + 0.5]
            try:
                e = scout(ad, capture_paths.LOCATIONS, name=name, at=at, facing=None, clock=clock, tags=["place", place])
                print("%s -> %s %s at %s" % (place, e["id"], e.get("title"), ", ".join("%.2f" % v for v in e["position"])))
            except TooClose as err:
                print("%s: %s" % (place, err))
    finally:
        ad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
