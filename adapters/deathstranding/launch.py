"""Starts Death Stranding Director's Cut with nobody at the keyboard and brings it into the last save.

    uv run --project . python -m adapters.deathstranding.launch [--close]

Steam starts it (steam://rungameid/1850570; Steam is in offline mode on the capture PC). Then, all
answered by Enter until our plug-in counts frames of a loaded world (its frame hook only runs in
one): the publisher logos (Enter skips them), the main menu (Enter is its first item, Continue: the
latest save), and, when the game cannot sign in (Steam offline), two notices about offline mode,
each with an OK button. 2026-11-25 on the PC: the window after 2 s, the logos and the first shader
compile about 2 min on a first start, the menu then about 25 s, a save loaded 20 s after Continue.

The plug-in's frame counter rises only in a loaded world, so `in_world()` is the test the adapter
and the worker use; the status file going stale means the game went away.
"""
import argparse
import os
import time

import numpy as np

from capture import host

from ..common import window
from . import paths
from .plugin import Plugin


def hwnd():
    hs = window.windows_titled(paths.WINDOW_TITLE)
    return hs[0] if hs else None


def quit_game(wait_s=40, log=print):
    """Closes the window as its close button does (the game exits without a dialog) and waits."""
    if not host.process_running(paths.EXE_NAME):
        return True
    h = hwnd()
    if h:
        window.close(h)
    t = time.time()
    while time.time() - t < wait_s:
        if not host.process_running(paths.EXE_NAME):
            log("the game closed after %.0f s" % (time.time() - t))
            return True
        time.sleep(0.5)
    return False


def close_game(log=print):
    if not quit_game(log=log) and host.process_running(paths.EXE_NAME):
        host.stop(paths.GAME, (paths.EXE_NAME,))


def _counts(p):
    st = p.status()
    t = st.get("timer0", "0,0").split(",")[0]
    return int(st.get("cam_calls", "0") or 0), int(t or 0), st.get("state")


def in_world(p=None, frames=20, timeout=5.0, need_time=None):
    """True if a loaded world renders: the render camera is set up `frames` more times within
    `timeout` (the plug-in's frame counter alone also runs while a save loads behind the offline
    notices), and, unless the plug-in holds time, the game clock advances (it stands still while
    a notice or a menu is up). need_time: force the clock test on or off."""
    p = p or Plugin()
    if not p.alive():
        return False
    c0, t0_, state = _counts(p)
    if need_time is None:
        need_time = state == "run"
    t0 = time.time()
    while time.time() - t0 < timeout:
        c, t, _ = _counts(p)
        if c >= c0 + frames and (not need_time or t > t0_):
            return True
        time.sleep(0.05)
    return False


def notice_up(h):
    """An offline notice: its OK button, a cyan box low in the middle of the frame."""
    img = window.grab(h)
    if img is None:
        return False
    a = np.asarray(img.convert("RGB").resize((480, 270)), dtype=np.float32)
    box = a[180:192, 220:260]
    return box[..., 2].mean() > 120 and box[..., 0].mean() < 80


def start(timeout=420, log=print):
    """Restarts the game and returns the window once a save is loaded and the plug-in counts frames."""
    window.keep_awake()
    close_game(log)
    for f in (paths.plugin_status(),):
        try:
            os.remove(f)
        except OSError:
            pass
    host.steam_launch(paths.GAME, paths.STEAM_APP)
    log("starting Death Stranding Director's Cut through Steam")
    p = Plugin()
    t0 = time.time()
    last_enter = 0.0
    while time.time() - t0 < timeout:
        time.sleep(1.0)
        h = hwnd()
        if not h:
            continue
        if p.alive() and p.frame() > 0 and in_world(p, frames=30, timeout=3.0, need_time=True):
            time.sleep(2.0)      # the first frames of a loaded save
            log("a save is loaded after %.0f s (frame %d)" % (time.time() - t0, p.frame()))
            return h
        # Enter answers everything before the world: logos, notices, the main menu's Continue
        if time.time() - last_enter > (2.0 if notice_up(h) else 4.0):
            if window.focus(h):
                window.press(h, "Enter", hold_s=0.08)
                last_enter = time.time()
    raise RuntimeError("Death Stranding did not reach a loaded save within %d s" % timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--close", action="store_true")
    a = ap.parse_args()
    if a.close:
        close_game()
        return
    start()


if __name__ == "__main__":
    main()
