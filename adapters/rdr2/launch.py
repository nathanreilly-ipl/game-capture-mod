"""Starts RDR2 story mode with nobody at the keyboard, until capture_loader.lua's heartbeat is up.

    close the game, its start stub and Rockstar's launcher (a leftover one makes Steam refuse a start)
    -> Steam starts the game: PlayRDR2.exe -> Rockstar's launcher (signs in by itself) -> RDR2.exe
    -> main menu: Enter (STORY) every few seconds, only while the game's window has the keyboard
    -> story mode loads; RedLua's Autorun starts capture_loader.lua; heartbeat

Windows: scripts/restart_game.ps1 does this (two to four minutes on the development machine).
Linux (the game under Proton, capture/host): the Steam client is the Windows one in the game's
prefix (host.steam_launch); the rest is the same. On a CoreWeave node, 2026-11-23: Steam's request
to the game's own start in 50 s, main menu about 100 s later, heartbeat 115 s after the first Enter
(game and prefix on a network file system).

    uv run --project . python -m adapters.rdr2.launch [--close]
"""
import os
import subprocess
import sys
import time

from capture import host

from ..common import redlua
from . import install, window
from .mem import find_pid
from .session import CAPTURES, heartbeat_age

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = install.GAME
# what a start must not find running, the game first
CLOSE = ("RDR2.exe", "PlayRDR2.exe", "Launcher.exe", "RockstarErrorHandler.exe", "RockstarSteamHelper.exe",
         "SocialClubHelper.exe")
LAUNCHER_TITLE = "Rockstar Games Launcher"


def close_game(log=print):
    host.stop(GAME, CLOSE)


def _game_window():
    try:
        return window.find_game_window(find_pid())
    except RuntimeError:
        return None


def start(game_dir, timeout=900, key_interval=5.0, log=print):
    """Restarts the game into story mode; returns once the loader's heartbeat is up."""
    if host.WINDOWS:
        script = os.path.join(HERE, "scripts", "restart_game.ps1")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                            "-GameDir", game_dir, "-CaptureDir", CAPTURES], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(r.stdout[-500:] + r.stderr[-500:])
        return
    t0 = time.time()
    close_game(log)
    try:
        os.remove(os.path.join(CAPTURES, "heartbeat.txt"))
    except OSError:
        pass
    host.steam_launch(GAME, install.STEAM_APP)
    log("asked Steam to start Red Dead Redemption 2")
    seen, last_key, asked = None, 0.0, time.time()
    while heartbeat_age() > 3:
        if time.time() - t0 > timeout:
            raise RuntimeError("no loader heartbeat after %d s (is the game in story mode with RedLua's Autorun on?)" % timeout)
        if seen is None and time.time() - asked > 180 and not host.pids(install.EXE):
            # a request can be lost: Steam shows the game's licence once and drops the start, or was not ready
            host.steam_launch(GAME, install.STEAM_APP)
            log("no game after 180 s; asked Steam again")
            asked = time.time()
        h = _game_window()
        if h:
            if seen is None:
                seen = time.time()
                log("game window after %.0f s" % (seen - t0))
            # a few seconds before the first key; then Enter (STORY on the main menu) until the loader runs
            if time.time() - seen > 8 and time.time() - last_key >= key_interval:
                if window.focus(h):
                    window.press(h, "Enter")
                last_key = time.time()
        time.sleep(0.5)
    log("loader heartbeat is up after %.0f s" % (time.time() - t0))
    h = _game_window()
    if h:
        window.move(h, 0, 0)      # all of it on the screen (it came up at 0,13), for screen grabs
    redlua.minimize_console()
    for h in window.windows_titled(LAUNCHER_TITLE):     # Rockstar's launcher keeps a window up beside the game
        window.hide(h)


if __name__ == "__main__":
    from .adapter import game_dir
    if "--close" in sys.argv:
        close_game()
    else:
        start(game_dir())
