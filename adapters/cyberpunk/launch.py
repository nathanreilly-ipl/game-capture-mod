"""Starts Cyberpunk 2077 with nobody at the keyboard, until a save is loaded, the world runs and
our loader mod's heartbeat says ingame=1 (about 95 s, 2026-11-21).

    close the game and CD Projekt's launcher
    -> bin\\x64\\Cyberpunk2077.exe --launcher-skip -skipStartScreen, Steam running
       (-skipStartScreen: no "press a key" screen before the main menu)
    -> main menu: Cyber Engine Tweaks starts our mod, the heartbeat appears with world=0
    -> the continue job (lua/jobs/continue_game.lua) loads the last save from inside the game,
       asked again every 15 s until a world is there (a request during the intro is ignored)
    -> heartbeat with ingame=1: the ground under the player has loaded and the clock runs

The exe is started directly, not through Steam: every start through Steam (steam.exe -applaunch)
raised a Windows administrator prompt, Steam's first-time setup for the game, which nobody
answers; it times out after two minutes and blanks every screen grab meanwhile. Started
directly, Steam does not list the game as running (RunningAppID stays 0), so anything that must
not run beside it has to look for the Cyberpunk2077.exe process. through_steam=True starts it
through Steam all the same.

    uv run --project . python -m adapters.cyberpunk.launch [--snapshots DIR]
"""
import os
import subprocess
import sys
import time

from ..common import mem, redlua, window
from . import paths

LAUNCHER_PROCS = ("REDprelauncher.exe", "REDlauncher.exe", "REDEngineErrorReporter.exe", "CrashReporter.exe")
CONTINUE_JOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lua", "jobs", "continue_game.lua")
ARGS = ("--launcher-skip", "-skipStartScreen")


def running_app():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return str(winreg.QueryValueEx(k, "RunningAppID")[0])
    except OSError:
        return "0"


def steam_exe():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return os.path.normpath(winreg.QueryValueEx(k, "SteamExe")[0])
    except OSError:
        return r"C:\Program Files (x86)\Steam\steam.exe"


def close_game(log=print):
    for name in (paths.EXE_NAME,) + LAUNCHER_PROCS:
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    t = time.time()
    while time.time() - t < 60:   # an install right after must not find the game still exiting
        try:
            mem.find_pid(paths.EXE_NAME)
        except RuntimeError:
            if running_app() != paths.STEAM_APP:
                break
        time.sleep(1)
    if running_app() == paths.STEAM_APP:
        log("Steam still lists Cyberpunk 2077 as running; the start may fail")


def heartbeat(exchange):
    if redlua.heartbeat_age(exchange) > 5:
        return None
    return redlua.read_kv(os.path.join(exchange, "heartbeat.txt"))


def start(exchange, client=(2560, 1440), timeout=600, log=print, snapshots=None, through_steam=False):
    """Restarts the game and loads the last save; returns the game window once ingame=1."""
    window.keep_awake()
    close_game(log)
    other = running_app()
    if other not in ("0", paths.STEAM_APP):
        # Steam runs one game at a time; it answers a second start with "Unable to launch game"
        raise RuntimeError("Steam is running another game (app %s); close it before starting Cyberpunk 2077" % other)
    try:
        os.remove(os.path.join(exchange, "heartbeat.txt"))
    except OSError:
        pass
    if through_steam:
        subprocess.Popen([steam_exe(), "-applaunch", paths.STEAM_APP] + list(ARGS))
        log("starting Cyberpunk 2077 through Steam")
    else:
        b = paths.bin_dir()
        subprocess.Popen([os.path.join(b, paths.EXE_NAME)] + list(ARGS), cwd=b)
        log("starting Cyberpunk 2077 (its exe, Steam running)")
    return drive(exchange, client, timeout, log, snapshots)


def drive(exchange, client=(2560, 1440), timeout=600, log=print, snapshots=None):
    """Takes a starting game to a loaded save; also for attaching to a game already on its way."""
    window.keep_awake()
    t0 = time.time()
    asked, shots, sized, h = 0.0, 0, False, None
    while time.time() - t0 < timeout:
        time.sleep(2)
        try:
            pid = mem.find_pid(paths.EXE_NAME)
        except RuntimeError:
            continue
        h = window.find_game_window(pid, paths.WINDOW_CLASS)
        if h and not sized and window.focus(h):
            sized = window.set_client_size(h, *client)
        if h and snapshots:
            img = window.grab(h)
            if img is not None:
                os.makedirs(snapshots, exist_ok=True)
                shots += 1
                img.convert("RGB").resize((960, 540)).save(os.path.join(snapshots, "%02d_%03ds.jpg" % (shots, time.time() - t0)))
        hb = heartbeat(exchange)
        if not hb:
            continue
        if hb.get("ingame") == "1":
            log("a save is loaded and the loader is up after %.0f s" % (time.time() - t0))
            break
        if hb.get("world") != "1" and time.time() - asked > 15 and not hb.get("job"):
            # in the main menu (world=0): load the last save from inside the game. A request made
            # while the intro still plays is ignored, so it is repeated until a world is there.
            redlua.run_job(exchange, CONTINUE_JOB, timeout_s=50, wait=False, staged=True)
            asked = time.time()
            log("main menu reached after %.0f s; asked the game to load the last save" % (time.time() - t0))
    else:
        raise RuntimeError("Cyberpunk 2077 did not reach a loaded save with the loader running in %d s" % timeout)
    if h:
        window.focus(h)
        if not window.set_client_size(h, *client):
            log("the game window is %s, not %s" % (window.client_size(h), client))
    return h


if __name__ == "__main__":
    snaps = sys.argv[sys.argv.index("--snapshots") + 1] if "--snapshots" in sys.argv else None
    start(paths.exchange(), snapshots=snaps)
