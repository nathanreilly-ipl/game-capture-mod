"""Where Kingdom Come: Deliverance (1.9.7, Steam) keeps what the capture needs. Game-specific."""
import os

from capture import config, host
from capture import paths as capture_paths

GAME = "kcd"
EXE_NAME = "KingdomCome.exe"
EXE = os.path.join("Bin", "Win64", EXE_NAME)            # relative to the game folder
STEAM_APP = "379430"
FOLDER = "KingdomComeDeliverance"                       # under steamapps\common
WINDOW_CLASS = "CryENGINE"                              # CryEngine's window class (to be checked in the game)
MOD_NAME = "capture_mod"                                # Mods\<name>\mod.manifest + Data\*.pak
DEFAULT_GAME_DIR = (os.path.join(capture_paths.OUT, "games", "kcd") if host.LINUX
                    else r"C:\Program Files (x86)\Steam\steamapps\common\KingdomComeDeliverance")


def game_dir():
    """The game folder: KCD_DIR, then this machine's config (written by `capture install`), then Steam's default."""
    return os.environ.get("KCD_DIR") or config.game(GAME).get("game_dir") or DEFAULT_GAME_DIR


def bin_dir(game=None):
    return os.path.join(game or game_dir(), "Bin", "Win64")


def mod_dir(game=None):
    return os.path.join(game or game_dir(), "Mods", MOD_NAME)


def game_log(game=None):
    """CryEngine's log, named after the game, in the game folder; System.LogAlways writes to it."""
    return os.path.join(game or game_dir(), "kcd.log")


def user_cfg(game=None):
    """Console variables the game reads at start, after system.cfg."""
    return os.path.join(game or game_dir(), "user.cfg")


def inbox(game=None):
    """Long inputs for our script, as Lua files it runs (Script.ReloadScript reads loose files in
    Data once sys_PakPriority is 0): <game>\\Data\\capture_mod_in."""
    return os.path.join(game or game_dir(), "Data", "capture_mod_in")


def saves_dir():
    return os.path.join(host.user_dir(GAME, "saved_games"), "kingdomcome", "saves")


def exchange():
    """Frames pass through here: the capture add-on's folder (request, ack, pictures)."""
    return os.path.join(capture_paths.OUT, "exchange", GAME)
