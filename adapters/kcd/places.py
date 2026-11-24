"""Named places of Kingdom Come: Deliverance, from the game's own files.

Warhorse's developer teleports (Libs\\Haste\\haste.xml in Data\\Scripts.pak, the "town portal"
namespace) name about thirty spots with their positions: town squares, pubs, castles, mills,
camps ("Rataje - middle pub", "Talmberk - castle", "Sazava - bridge"). They are read from the
game's pak on the machine (nothing of the game is copied into the repository), with the towns'
English names in front ("Rattay - middle pub"). Scouting uses them as spots (probes/scout_places.py)
and place titles as the nearest one within 400 m.

The pak's local file headers carry backslash paths, which Python's zipfile rejects, so the local
headers are read directly.
"""
import functools
import os
import re
import struct
import zlib

from . import paths

TOWNS = {"Rataje": "Rattay", "RatajeO": "Rattay outskirts", "Talmberk": "Talmberg", "Sazava": "Sasau",
         "Mrchojedy": "Merhojed", "Samopse": "Samopesh", "Skalice": "Skalitz", "Ledecko": "Ledetchko",
         "Uzice": "Uzhitz", "Uzice (Auschitz)": "Uzhitz", "Rovna": "Rovna", "Vranik": "Vranik", "Neuhoff": "Neuhof",
         "Monastery": "Sasau monastery", "SazavaO": "Sasau outskirts", "Pribyslavice": "Pribyslavitz",
         "Mrchojedy warcamp": "Merhojed war camp", "Na Mytince": "Mytinka"}


def _pak_file(pak, wanted):
    data = open(pak, "rb").read()
    i = 0
    while True:
        i = data.find(b"PK\x03\x04", i)
        if i < 0:
            return None
        _v, _f, meth, _t, _d, _c, csz, _u, nl, xl = struct.unpack("<HHHHHIIIHH", data[i + 4:i + 30])
        name = data[i + 30:i + 30 + nl].decode("latin1").replace("\\", "/").lower()
        start = i + 30 + nl + xl
        if name == wanted:
            blob = data[start:start + csz]
            return (zlib.decompress(blob, -15) if meth == 8 else blob).decode("utf-8", "replace")
        i = start + csz


def english(name):
    town, sep, rest = name.partition(" - ")
    town = TOWNS.get(town.strip(), town.strip())
    return town + (" - " + rest.strip() if sep else "")


@functools.lru_cache(maxsize=4)
def load(game_dir=None):
    """[{"name", "title", "position"}] of the game's town portals."""
    text = _pak_file(os.path.join(game_dir or paths.game_dir(), "Data", "Scripts.pak"), "libs/haste/haste.xml") or ""
    m = re.search(r'<namespace name="town portal">(.*?)</namespace>', text, re.S)
    out = []
    for name, x, y, z in re.findall(r'<command name="([^"]+)">\s*<teleportToPosition[^>]*posX="([-\d.]+)"\s+posY="([-\d.]+)"\s+posZ="([-\d.]+)"',
                                    m.group(1) if m else ""):
        out.append({"name": name, "title": english(name), "position": [float(x), float(y), float(z)]})
    return out


def nearest(position, within=400.0, game_dir=None):
    best = None
    for p in load(game_dir):
        d = ((p["position"][0] - position[0]) ** 2 + (p["position"][1] - position[1]) ** 2) ** 0.5
        if d <= within and (best is None or d < best[0]):
            best = (d, p)
    return best
