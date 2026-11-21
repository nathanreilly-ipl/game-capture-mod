"""RDR2's window, through the shared window helpers (adapters/common/window.py)."""
from ..common.window import *  # noqa: F401,F403
from ..common import window as _window

GAME_CLASS = "sgaWindow"


def find_game_window(pid):
    """RDR2's own window (class sgaWindow), not RedLua's console. None if absent."""
    return _window.find_game_window(pid, GAME_CLASS)
