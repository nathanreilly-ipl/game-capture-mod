"""Game name -> adapter class. Adapters live in adapters/<game>/ at the repo root and are
imported only when asked for, so the generic code never loads a game's dependencies."""
import importlib
import sys

from .paths import REPO

GAMES = {"rdr2": ("adapters.rdr2.adapter", "RDR2Adapter"), "gtav": ("adapters.gtav.adapter", "GTAVAdapter"),
         "gtave": ("adapters.gtav.adapter", "GTAVEnhancedAdapter"),
         "cyberpunk": ("adapters.cyberpunk.adapter", "CyberpunkAdapter"),
         "witcher3": ("adapters.witcher3.adapter", "Witcher3Adapter"),
         "kcd": ("adapters.kcd.adapter", "KcdAdapter")}


def get(game):
    if game not in GAMES:
        raise KeyError("no adapter for %r (known: %s)" % (game, ", ".join(sorted(GAMES))))
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    module, cls = GAMES[game]
    return getattr(importlib.import_module(module), cls)


def names():
    return sorted(GAMES)
