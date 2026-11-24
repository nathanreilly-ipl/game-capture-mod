"""Where The Witcher 3 and our files in it are.

The game keeps its user files in Documents\\The Witcher 3 (settings, saves, and the scripts log
our session script answers through); our exchange folder for frames sits in there too.
"""
import os

from capture import config, host
from capture import paths as capture_paths

GAME = "witcher3"
EXE_NAME = "witcher3.exe"
EXE = os.path.join("bin", "x64_dx12", EXE_NAME)       # relative to the game folder
STEAM_APP = "292030"
FOLDER = "The Witcher 3"                               # under steamapps\common
WINDOW_CLASS = "W2ViewportClass"                       # REDengine's window class
WINDOW_TITLE = "The Witcher 3"
USER_FOLDER = "The Witcher 3"                          # under Documents
MOD_NAME = "modCaptureMod"                             # a mod folder's name must start with "mod"
SCRIPT_NAME = "capture_mod.ws"
# Windows: Steam's default library. Linux (the game under Proton, capture/host): where a download
# of the game's Windows depot is kept, since there is no Steam client there.
DEFAULT_GAME_DIR = (os.path.join(capture_paths.OUT, "games", "witcher3") if host.LINUX
                    else r"C:\Program Files (x86)\Steam\steamapps\common\The Witcher 3")
# Under Proton, Wine must load the game folder's own dxgi.dll (ReShade) and winmm.dll (OptiScaler,
# when installed) instead of its built-in ones
DLL_OVERRIDES = "dxgi,winmm=n,b"


def game_dir():
    """The game folder: WITCHER3_DIR, then this machine's config (written by `capture install`),
    then Steam's default."""
    return os.environ.get("WITCHER3_DIR") or config.game(GAME).get("game_dir") or DEFAULT_GAME_DIR


def bin_dir(game=None):
    return os.path.join(game or game_dir(), "bin", "x64_dx12")


def scripts_dir(game=None):
    """Where our loose script mod lives; the game compiles it with its own scripts at start."""
    return os.path.join(game or game_dir(), "mods", MOD_NAME, "content", "scripts", "local")


def user_dir():
    return os.path.join(host.user_dir(GAME, "documents"), USER_FOLDER)


def user_settings():
    return os.path.join(user_dir(), "dx12user.settings")


def scripts_log():
    """Written by the game when it is started with -debugscripts; our script's answers are in it."""
    return os.path.join(user_dir(), "scriptslog.txt")


def saves_dir():
    return os.path.join(user_dir(), "gamesaves")


def exchange():
    """Frames pass through here: the capture add-on's folder (request, ack, pictures)."""
    return os.path.join(user_dir(), "capture_mod")
