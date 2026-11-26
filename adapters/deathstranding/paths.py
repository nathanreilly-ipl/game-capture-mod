"""Where Death Stranding Director's Cut (1.004, Steam) keeps what the capture needs. Game-specific."""
import glob
import os

from capture import config, host
from capture import paths as capture_paths

GAME = "deathstranding"
EXE_NAME = "ds.exe"
EXE = EXE_NAME                                          # relative to the game folder
STEAM_APP = "1850570"
FOLDER = "DEATH STRANDING DIRECTORS CUT"                # under steamapps\common
WINDOW_TITLE = "DEATH STRANDING DIRECTOR'S CUT"
WINDOW_CLASS = "PIGS_MainWnd"
DEFAULT_GAME_DIR = (os.path.join(capture_paths.OUT, "games", GAME) if host.LINUX
                    else os.path.join(r"C:\Program Files (x86)\Steam\steamapps\common", FOLDER))


def game_dir():
    """The game folder: DS_DIR, then this machine's config (written by `capture install`), then Steam's default."""
    return os.environ.get("DS_DIR") or config.game(GAME).get("game_dir") or DEFAULT_GAME_DIR


def profile_dirs():
    """The game's per-account folders (%LOCALAPPDATA%\\KojimaProductions\\DeathStrandingDC\\<steam id>),
    holding the saves and profile\\game_settings.cfg."""
    base = os.path.join(host.user_dir(GAME, "local_appdata"), "KojimaProductions", "DeathStrandingDC")
    return [d for d in glob.glob(os.path.join(base, "*")) if os.path.isdir(os.path.join(d, "profile"))]


def game_settings_files():
    return [os.path.join(d, "profile", "game_settings.cfg") for d in profile_dirs()]


def exchange():
    """Our plug-in's control and status files, and the frames of the capture add-on."""
    return os.path.join(capture_paths.OUT, "exchange", GAME)


def plugin_control():
    return os.path.join(exchange(), "capture.txt")


def plugin_status():
    return os.path.join(exchange(), "capture_status.txt")
