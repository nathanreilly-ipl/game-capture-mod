"""Where Cyberpunk 2077 and our files in it are.

Cyber Engine Tweaks lets a mod read and write only inside its own folder, so unlike RDR2 and
GTA V the exchange folder is not under Documents: it is the "exchange" subfolder of our mod,
inside the game folder. The ReShade add-on and the adapter use the same folder by its full path.
"""
import os

from capture import config, host
from capture import paths as capture_paths

GAME = "cyberpunk"
EXE_NAME = "Cyberpunk2077.exe"
EXE = os.path.join("bin", "x64", EXE_NAME)          # relative to the game folder
STEAM_APP = "1091500"
FOLDER = "Cyberpunk 2077"                           # under steamapps\common
WINDOW_CLASS = "W2ViewportClass"                    # REDengine's window class (checked by launch.py)
CET_DIR = os.path.join("bin", "x64", "plugins", "cyber_engine_tweaks")
MOD_NAME = "capture_mod"
MOD_DIR = os.path.join(CET_DIR, "mods", MOD_NAME)
# Windows: Steam's default library. Linux (the game under Proton, capture/host): where a download
# of the game's Windows depot is kept, since there is no Steam client there.
DEFAULT_GAME_DIR = (os.path.join(capture_paths.OUT, "games", "cyberpunk2077") if host.LINUX
                    else r"C:\Program Files (x86)\Steam\steamapps\common\Cyberpunk 2077")
# Under Proton, Wine must load the game folder's own winmm.dll (RED4ext's loader) and version.dll
# (Cyber Engine Tweaks' ASI loader) instead of its built-in ones (RED modding wiki; checked 2026-11-23)
DLL_OVERRIDES = "winmm,version=n,b"


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
