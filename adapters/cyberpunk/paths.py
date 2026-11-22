"""Where Cyberpunk 2077 and our files in it are.

Cyber Engine Tweaks lets a mod read and write only inside its own folder, so unlike RDR2 and
GTA V the exchange folder is not under Documents: it is the "exchange" subfolder of our mod,
inside the game folder. The ReShade add-on and the adapter use the same folder by its full path.
"""
import os

from capture import config

GAME = "cyberpunk"
EXE_NAME = "Cyberpunk2077.exe"
EXE = os.path.join("bin", "x64", EXE_NAME)          # relative to the game folder
STEAM_APP = "1091500"
FOLDER = "Cyberpunk 2077"                           # under steamapps\common
WINDOW_CLASS = "W2ViewportClass"                    # REDengine's window class (checked by launch.py)
CET_DIR = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks")
MOD_NAME = "capture_mod"
MOD_DIR = os.path.join(CET_DIR, "mods", MOD_NAME)
DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077"


def game_dir():
    """The game folder: CYBERPUNK_DIR, then this machine's config (written by `capture install`),
    then Steam's default."""
    return os.environ.get("CYBERPUNK_DIR") or config.game(GAME).get("game_dir") or DEFAULT_GAME_DIR


def bin_dir(game=None):
    return os.path.join(game or game_dir(), "bin", "x64")


def mod_dir(game=None):
    return os.path.join(game or game_dir(), MOD_DIR)


def exchange(game=None):
    return os.path.join(mod_dir(game), "exchange")
