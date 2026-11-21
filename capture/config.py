"""This machine's settings: out/config.json (gitignored), written by `capture install`.

    {"games": {"rdr2": {"game_dir": "D:\\\\SteamLibrary\\\\steamapps\\\\common\\\\Red Dead Redemption 2"}}}
"""
import os

from . import paths
from .util import read_json, write_json

PATH = os.path.join(paths.OUT, "config.json")


def load():
    return read_json(PATH) if os.path.exists(PATH) else {"games": {}}


def game(name):
    return load().get("games", {}).get(name, {})


def set_game(name, **values):
    cfg = load()
    cfg.setdefault("games", {}).setdefault(name, {}).update(values)
    write_json(PATH, cfg)
