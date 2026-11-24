"""Starts Kingdom Come: Deliverance with nobody at the keyboard and brings it to a loaded save.

    uv run --project . python -m adapters.kcd.launch

The exe with -devmode (the console our commands use; Steam picks the game up on its own), intro
films off by user.cfg (wh_sys_HideIntroVideo, install.py). Our script answers from the main menu;
Enter there is the menu's first item, Continue (the latest save). The game is in a world once the
player stands away from the main menu's spot and no save is loading. On the first start on a
machine the game shows its EULA, which E accepts (done on this PC on 2026-11-23, on Nathan's word).
"""
import os
import time

from capture import host

from ..common import window
from . import paths
from .session import Session

ARGS = ("-devmode",)


def quit_game(wait_s=30, log=print):
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
    if host.process_running(paths.EXE_NAME):
        host.stop(paths.GAME, (paths.EXE_NAME,))


def to_menu(timeout=300, log=print):
    """Starts the exe and returns the session once our script answers at the main menu."""
    window.keep_awake()
    close_game(log)
    b = paths.bin_dir()
    host.start(paths.GAME, os.path.join(b, paths.EXE_NAME), ARGS, cwd=b, dll_overrides="dxgi=n,b", app_id=paths.STEAM_APP)
    log("starting Kingdom Come: Deliverance (its exe, -devmode)")
    s = Session(log)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        if not s.hwnd():
            continue
        st = s.hello(timeout=3.0)
        if st:
            log("our script answers after %.0f s" % (time.time() - t0))
            return s
    raise RuntimeError("Kingdom Come: Deliverance did not answer within %d s" % timeout)


def enter_world(s, timeout=240, log=print):
    """From the main menu: Continue (Enter on the first item), then waits for a loaded save."""
    t0 = time.time()
    pressed = 0
    while time.time() - t0 < timeout:
        st = s.hello(timeout=3.0) or {}
        if st.get("ingame") == "1" and st.get("loading") == "0":
            time.sleep(3.0)              # the first frames of a loaded save
            log("a save is loaded after %.0f s" % (time.time() - t0))
            return st
        if not st.get("ingame") == "1" and pressed < 3 and time.time() - t0 > 2 + 25 * pressed:
            h = s.hwnd()
            window.focus(h)
            window.press(h, "Enter", hold_s=0.08)
            pressed += 1
            log("Continue (Enter at the main menu)")
        time.sleep(3.0)
    raise RuntimeError("no save loaded within %d s" % timeout)


def start(timeout=420, log=print):
    """Restarts the game and returns once a save is loaded and our script answers."""
    t0 = time.time()
    s = to_menu(timeout=min(300, timeout), log=log)
    st = enter_world(s, timeout=max(60, timeout - (time.time() - t0)), log=log)
    log("in the world after %.0f s" % (time.time() - t0))
    return s.hwnd()


if __name__ == "__main__":
    start()
