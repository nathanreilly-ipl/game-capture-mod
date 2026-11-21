"""Starts GTA V Legacy story mode through Steam with nobody at the keyboard, until the capture
loader's heartbeat is up (about three minutes).

    close the game and its launcher (a leftover launcher makes Steam refuse a new start)
    -> steam://rungameid/271590
    -> Steam asks which launch option: pick "Play Grand Theft Auto V Legacy" and Play
    -> Rockstar's landing page: click STORY MODE (the rightmost item of its bottom bar)
    -> story mode loads; RedLua's Autorun starts capture_loader.lua; heartbeat

Clicks go only to Steam's dialog and to the game while the loader is not running (landing page,
loading screens), so a click never lands in the game world. BattlEye stays off (-nobattleye in
commandline.txt), so the game cannot go online whatever is clicked.

    uv run --project . python -m adapters.gtav.launch [--snapshots DIR]
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

import numpy as np

from ..common import mem, redlua, window

STEAM_APP = "271590"
EXE = "GTA5.exe"
WINDOW_CLASS = "grcWindow"
DIALOG_TITLE = "Grand Theft Auto V Legacy"      # Steam's launch-option dialog
# Steam's dialog, as fractions of its window: the story-mode option (first) and the Play button
DIALOG_STORY = (0.34, 0.287)
DIALOG_PLAY = (0.60, 0.925)
CLOSE = ("GTA5.exe", "GTA5_BE.exe", "PlayGTAV.exe", "Launcher.exe", "RockstarErrorHandler.exe",
         "RockstarSteamHelper.exe", "SocialClubHelper.exe", "GTAVLauncher.exe")

user32 = window.user32
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def running_app():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return str(winreg.QueryValueEx(k, "RunningAppID")[0])
    except OSError:
        return "0"


def close_game(log=print):
    for name in CLOSE:
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    t = time.time()
    while running_app() == STEAM_APP and time.time() - t < 60:
        time.sleep(1)
    if running_app() == STEAM_APP:
        log("Steam still lists GTA V as running; the start may fail")


def click_screen(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.3)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def _rect(h):
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r


def answer_steam_dialog(log=print):
    """Steam's launch-option dialog, if it is up: story mode, then Play. True if it was answered."""
    for h in window.windows_titled(DIALOG_TITLE, "SDL_app"):
        window.focus(h)
        r = _rect(h)
        w, hgt = r.right - r.left, r.bottom - r.top
        click_screen(r.left + DIALOG_STORY[0] * w, r.top + DIALOG_STORY[1] * hgt)
        time.sleep(0.5)
        click_screen(r.left + DIALOG_PLAY[0] * w, r.top + DIALOG_PLAY[1] * hgt)
        time.sleep(2)
        log("answered Steam's launch dialog: story mode, Play")
        return True
    return False


def landing_target(img):
    """Where to click STORY MODE on Rockstar's landing page: the rightmost word group of the
    bottom bar (QUIT, SETTINGS, ..., ONLINE, STORY MODE), as client coordinates; None if the bar
    has no text (another screen)."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = a.shape
    band = a[int(h * 0.935):int(h * 0.965), int(w * 0.40):int(w * 0.99)]
    cols = (band > 150).sum(axis=0) > 0
    xs = np.flatnonzero(cols)
    if len(xs) < 20:
        return None
    groups, start, prev = [], xs[0], xs[0]
    gap = w * 0.012                       # a gap wider than between two words of one item
    for x in xs[1:]:
        if x - prev > gap:
            groups.append((start, prev))
            start = x
        prev = x
    groups.append((start, prev))
    if len(groups) < 3:                   # the bar has several items; a lone text is not it
        return None
    x0, x1 = groups[-1]
    return int(w * 0.40 + (x0 + x1) / 2), int(h * 0.95)


def start(exchange, client=(2560, 1440), timeout=480, log=print, snapshots=None):
    """Restarts the game into story mode; returns once the loader's heartbeat is up."""
    close_game(log)
    try:
        os.remove(os.path.join(exchange, "heartbeat.txt"))
    except OSError:
        pass
    t0 = time.time()
    os.startfile("steam://rungameid/%s" % STEAM_APP)
    log("starting GTA V Legacy through Steam")
    last_click, shots, sized = 0.0, 0, False
    while time.time() - t0 < timeout:
        time.sleep(2)
        if redlua.heartbeat_age(exchange) < 3:
            log("loader heartbeat is up after %.0f s" % (time.time() - t0))
            break
        answer_steam_dialog(log)
        try:
            h = window.find_game_window(mem.find_pid(EXE), WINDOW_CLASS)
        except RuntimeError:
            continue
        if not h:
            continue
        if not sized and window.focus(h):
            sized = window.set_client_size(h, *client)
        if time.time() - last_click < 10 or not window.focus(h):
            continue
        img = window.grab(h)
        if img is None:
            continue
        if snapshots:
            os.makedirs(snapshots, exist_ok=True)
            shots += 1
            img.convert("RGB").resize((960, 540)).save(os.path.join(snapshots, "%02d_%03ds.jpg" % (shots, time.time() - t0)))
        target = landing_target(img)
        if target and redlua.heartbeat_age(exchange) > 3:
            pt = wt.POINT(*target)
            user32.ClientToScreen(h, ctypes.byref(pt))
            click_screen(pt.x, pt.y)
            log("clicked STORY MODE at %s" % (target,))
            last_click = time.time()
    else:
        raise RuntimeError("GTA V did not reach story mode with the loader running in %d s" % timeout)
    redlua.minimize_console()
    h = window.find_game_window(mem.find_pid(EXE), WINDOW_CLASS)
    window.focus(h)
    if not window.set_client_size(h, *client):
        log("the game window is %s, not %s" % (window.client_size(h), client))
    return h


if __name__ == "__main__":
    from .adapter import EXCHANGE
    snaps = sys.argv[sys.argv.index("--snapshots") + 1] if "--snapshots" in sys.argv else None
    start(EXCHANGE, snapshots=snaps)
