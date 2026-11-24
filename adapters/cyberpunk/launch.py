"""Starts Cyberpunk 2077 with nobody at the keyboard, until a save is loaded, the world runs and
our loader mod's heartbeat says ingame=1 (39 s with the loading film skipped, 2026-11-22; 98 s
without).

    close the game and CD Projekt's launcher
    -> bin\\x64\\Cyberpunk2077.exe --launcher-skip -skipStartScreen, Steam running
       (-skipStartScreen: no "press a key" screen before the main menu)
    -> the intro films and the loading film: Space, pressed every 2 s until the player is in the
       world (the loading film otherwise waits on "press to continue")
    -> main menu: Cyber Engine Tweaks starts our mod, the heartbeat appears with world=0
    -> the continue job (lua/jobs/continue_game.lua) loads the last save from inside the game,
       asked again every 6 s until a world is there (a request during the intro is ignored)
    -> heartbeat with ingame=1: the ground under the player has loaded and the clock runs

The exe is started directly, not through Steam: every start through Steam (steam.exe -applaunch)
raised a Windows administrator prompt, Steam's first-time setup for the game, which nobody
answers; it times out after two minutes and blanks every screen grab meanwhile. Started
directly, Steam does not list the game as running (RunningAppID stays 0), so anything that must
not run beside it has to look for the Cyberpunk2077.exe process. through_steam=True starts it
through Steam all the same.

On Linux the same exe is started under Proton on the headless display (capture/host), with the
DLL overrides its script layer needs (paths.DLL_OVERRIDES) and no Steam client at all; everything
after the start is the same (2026-11-23, game and prefix on a network file system, 8 CPU cores:
146 to 155 s from the start to ingame=1, 182 s on the first start of a new prefix). close_game
first asks the window to close (quit_game): a game that exits by itself writes its settings
file, a killed one does not, and there nobody closes it by hand.

    uv run --project . python -m adapters.cyberpunk.launch [--snapshots DIR] | --close
"""
import os
import subprocess
import sys
import time

from capture import host

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


def quit_game(wait_s=60, log=print):
    """Closes the game as its window's close button does and waits for it to end, so it writes
    its settings file (it does so only on a clean exit: a killed game leaves none, 2026-11-23).
    True if it ended."""
    try:
        pid = mem.find_pid(paths.EXE_NAME)
    except RuntimeError:
        return True
    h = window.find_game_window(pid, paths.WINDOW_CLASS)
    if not h or not window.close(h):
        return False
    t = time.time()
    while time.time() - t < wait_s:
        try:
            mem.find_pid(paths.EXE_NAME)
        except RuntimeError:
            log("the game closed after %.0f s" % (time.time() - t))
            return True
        time.sleep(1)
    return False


def close_game(log=print):
    if host.LINUX:   # everything in the game's Proton prefix; there is no Steam client to ask
        quit_game(wait_s=30, log=log)   # a clean exit first: nobody is there to close it by hand
        host.stop(paths.GAME, (paths.EXE_NAME,) + LAUNCHER_PROCS)
        return
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
    host.check_start(paths.GAME)   # before the running game is closed: a start that cannot happen must not end it
    close_game(log)
    other = running_app() if host.WINDOWS else "0"
    if other not in ("0", paths.STEAM_APP):
        # Steam runs one game at a time; it answers a second start with "Unable to launch game"
        raise RuntimeError("Steam is running another game (app %s); close it before starting Cyberpunk 2077" % other)
    try:
        os.remove(os.path.join(exchange, "heartbeat.txt"))
    except OSError:
        pass
    if host.LINUX:
        b = paths.bin_dir()
        host.start(paths.GAME, os.path.join(b, paths.EXE_NAME), ARGS, cwd=b, dll_overrides=paths.DLL_OVERRIDES,
                   app_id=paths.STEAM_APP)
        log("starting Cyberpunk 2077 under Proton (its exe, no Steam client)")
    elif through_steam:
        subprocess.Popen([steam_exe(), "-applaunch", paths.STEAM_APP] + list(ARGS))
        log("starting Cyberpunk 2077 through Steam")
    else:
        b = paths.bin_dir()
        subprocess.Popen([os.path.join(b, paths.EXE_NAME)] + list(ARGS), cwd=b)
        log("starting Cyberpunk 2077 (its exe, Steam running)")
    return drive(exchange, client, timeout, log, snapshots)


def drive(exchange, client=(2560, 1440), timeout=600, log=print, snapshots=None, skip_intro=True):
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
        if h and skip_intro and (not hb or hb.get("ingame") != "1"):
            # Space skips the intro films (Nathan, 2026-11-22) and ends the loading film, which
            # otherwise waits on "press to continue" with the save loaded (40 s to 98 s on
            # 2026-11-22). Pressed until the player is in the world (where it only jumps), and
            # only into the game's window (window.press sends nothing while it is not in front).
            window.focus(h)
            window.press(h, "Space")
        if not hb:
            continue
        if hb.get("ingame") == "1":
            log("a save is loaded and the loader is up after %.0f s" % (time.time() - t0))
            break
        if hb.get("world") != "1" and time.time() - asked > 6 and not hb.get("job"):
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
    # --close: only close the running game (cleanly where possible; then it writes its settings file)
    if "--close" in sys.argv:
        close_game()
    else:
        snaps = sys.argv[sys.argv.index("--snapshots") + 1] if "--snapshots" in sys.argv else None
        start(paths.exchange(), snapshots=snaps)
