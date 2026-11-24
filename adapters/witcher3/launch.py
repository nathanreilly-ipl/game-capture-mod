"""Starts The Witcher 3 with nobody at the keyboard, until a save is loaded and our script answers
from inside the world (61 s on 2026-11-23, the window after 11 s).

    close the game
    -> bin\\x64_dx12\\witcher3.exe -debugscripts
       (the exe alone: no launcher, and no Steam client needed; checked with Steam shut down,
       2026-11-23. -debugscripts makes the game write the scripts log our script answers through)
    -> intro films, then a screen offering a CD Projekt account, on a first start also one
       asking for telemetry: Space skips a film, Esc the account screen, Esc held rejects telemetry.
       They are pressed until our script answers (it does once the main menu is up)
    -> main menu: our script loads the last save (cm_continue, what the menu's Continue does).
       A machine with no save gets a new "Blood and Wine only" game (cm_newgame): a ready
       character in the open world of Velen with no prologue to play, and a quick save of it
    -> the world has loaded when the script reports ingame=1 with no streaming and no black screen

On Linux the same exe is started under Proton on the headless display (capture/host) with
ReShade's dxgi.dll taken from the game folder (paths.DLL_OVERRIDES); not run there yet.

    uv run --project . python -m adapters.witcher3.launch [--close]
"""
import glob
import os
import sys
import time

from capture import host

from ..common import window
from . import paths
from .session import Session

ARGS = ("-debugscripts",)
OTHER_PROCS = ("REDprelauncher.exe", "REDlauncher.exe", "CrashReporter.exe")
CRASH_TITLE = "The Witcher 3 Crash Reporter"
# shown at start when a script does not compile; it lists the errors and waits for a click
COMPILE_TITLE = "The Witcher 3: Wild Hunt - Script Compilation Errors"


def has_save():
    return bool(glob.glob(os.path.join(paths.saves_dir(), "*.sav")))


def quit_game(wait_s=30, log=print):
    """Closes the game as its window's close button does and waits for it to end. True if it ended."""
    if not host.process_running(paths.EXE_NAME):
        return True
    h = Session(log).hwnd()
    if not h or not window.close(h):
        return False
    t = time.time()
    while time.time() - t < wait_s:
        if not host.process_running(paths.EXE_NAME):
            log("the game closed after %.0f s" % (time.time() - t))
            return True
        time.sleep(0.5)
    return False


def close_game(log=print):
    quit_game(log=log)
    if host.LINUX or host.process_running(paths.EXE_NAME) or any(host.process_running(p) for p in OTHER_PROCS):
        host.stop(paths.GAME, (paths.EXE_NAME,) + OTHER_PROCS)


def crashed():
    """The game's crash reporter is up (it stays until someone answers it)."""
    return bool(window.windows_titled(CRASH_TITLE))


def start(client=(2560, 1440), timeout=420, log=print):
    """Restarts the game and loads the last save; returns the game window once the world is up."""
    window.keep_awake()
    close_game(log)
    b = paths.bin_dir()
    host.start(paths.GAME, os.path.join(b, paths.EXE_NAME), ARGS, cwd=b, dll_overrides=paths.DLL_OVERRIDES,
               app_id=paths.STEAM_APP)
    log("starting The Witcher 3 (its exe, -debugscripts)")
    return drive(client, timeout, log)


def drive(client=(2560, 1440), timeout=420, log=print):
    """Takes a starting game to a loaded save; also for attaching to a game already on its way."""
    window.keep_awake()
    sess = Session(log)
    t0 = time.time()
    asked, sized, menu_at, new_game, h = 0.0, False, None, False, None
    while time.time() - t0 < timeout:
        if crashed():
            raise RuntimeError("The Witcher 3 crashed while starting (its crash reporter is open)")
        if window.windows_titled(COMPILE_TITLE):
            raise RuntimeError("The Witcher 3 could not compile its scripts with ours (its window \"Script Compilation "
                               "Errors\" lists the lines; fix adapters/witcher3/ws, run `%s install witcher3 --only "
                               "scripts`, then press Retry in that window or start again)" % host.CLI)
        h = sess.hwnd()
        if not h:
            time.sleep(1)
            continue
        if not sized and window.focus(h):
            sized = window.set_client_size(h, *client) or True     # a full-screen window cannot be resized
        st = sess.hello(timeout=2.0)
        if st is None:
            # a film, or a screen before the main menu: skip it and ask again
            window.focus(h)
            window.press(h, "Space")
            time.sleep(0.6)
            window.press(h, "Esc", hold_s=2.6 if time.time() - t0 > 40 else 0.08)   # held: rejects telemetry
            time.sleep(0.8)
            continue
        if st.get("ingame") == "1":
            if st.get("streaming") == "0" and st.get("black") == "0":
                log("a save is loaded and our script answers after %.0f s" % (time.time() - t0))
                break
            time.sleep(1.5)
            continue
        if menu_at is None:
            menu_at = time.time()
            log("our script answers from the main menu after %.0f s" % (menu_at - t0))
        if time.time() - asked > 25:
            window.press(h, "Esc")                      # the account screen, if it is still up
            time.sleep(0.5)
            new_game = not has_save()
            r = sess.cmd("newgame" if new_game else "continue", check=False)
            asked = time.time()
            log("asked the game to %s (%s)" % ("start a new Blood and Wine only game" if new_game else "load the last save", r.text))
        time.sleep(1.5)
    else:
        raise RuntimeError("The Witcher 3 did not reach a loaded world with our script answering in %d s" % timeout)
    settle(sess, h, log)
    if new_game:
        sess.cmd("save")
        log("made a quick save of the new game, so the next start continues from it")
        time.sleep(3)
    if not window.set_client_size(h, *client):
        log("the game window is %s, not %s" % (window.client_size(h), client))
    return h


def settle(sess, h, log=print, tries=6):
    """After a load: closes whatever panel the game opened over the world (a welcome panel pauses
    it) until the world runs."""
    for _ in range(tries):
        st = sess.state()
        if st.get("paused") == "0" and st.get("menu") == "0" and st.get("dialog") == "0":
            return True
        window.focus(h)
        window.press(h, "Enter")
        time.sleep(1.5)
    log("the world is still paused or a menu is open after %d tries: %s" % (tries, sess.last_state))
    return False


if __name__ == "__main__":
    if "--close" in sys.argv:
        close_game()
    else:
        start()
