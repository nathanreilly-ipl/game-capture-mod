"""Starts GTA V story mode (Legacy or Enhanced) through Steam with nobody at the keyboard, until
the capture loader's heartbeat is up (about 75 s for Legacy).

    close the game and its launcher (a leftover launcher makes Steam refuse a new start)
    -> steam://rungameid/<app>
    -> Steam asks which launch option: pick the story-mode one (the first) and Play
    -> Rockstar's landing page: click STORY MODE (the rightmost item of its bottom bar)
    -> story mode loads; RedLua's Autorun starts capture_loader.lua; heartbeat

Clicks go only to Steam's dialog and to the game while the loader is not running (landing page,
loading screens), so a click never lands in the game world. BattlEye stays off (-nobattleye in
commandline.txt), so the game cannot go online whatever is clicked.

    uv run --project . python -m adapters.gtav.launch [--enhanced] [--snapshots DIR]
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import numpy as np

from ..common import mem, redlua, window


@dataclass(frozen=True)
class Edition:
    name: str
    steam_app: str
    exe: str
    dialog_title: str            # Steam's launch-option dialog
    close: tuple                 # processes to end before a start
    window_class: str = "grcWindow"
    landing: str = "bar"         # Rockstar's landing page: "bar" (Legacy) or "tabs" (Enhanced)


LAUNCHER_PROCS = ("PlayGTAV.exe", "Launcher.exe", "RockstarErrorHandler.exe", "RockstarSteamHelper.exe",
                  "SocialClubHelper.exe", "GTAVLauncher.exe")
LEGACY = Edition("GTA V Legacy", "271590", "GTA5.exe", "Grand Theft Auto V Legacy",
                 ("GTA5.exe", "GTA5_BE.exe") + LAUNCHER_PROCS)
# Enhanced's window is class sgaWindow, titled "Grand Theft Auto V" (2026-11-21)
ENHANCED = Edition("GTA V Enhanced", "3240220", "GTA5_Enhanced.exe", "Grand Theft Auto V Enhanced",
                   ("GTA5_Enhanced.exe", "GTA5_Enhanced_BE.exe") + LAUNCHER_PROCS, window_class="sgaWindow",
                   landing="tabs")
# Enhanced's landing page: tabs ONLINE, GTA+, STORY across the top (ONLINE selected, a white box);
# E moves one tab right, Enter on STORY resumes the story. Tab centres as fractions of the width.
TABS = (0.085, 0.148, 0.208)
# Legacy's names, as the adapter and older callers use them
STEAM_APP, EXE, WINDOW_CLASS = LEGACY.steam_app, LEGACY.exe, LEGACY.window_class
# Steam's dialog, as fractions of its window: the story-mode option (first) and the Play button
DIALOG_STORY = (0.34, 0.287)
DIALOG_PLAY = (0.60, 0.925)

user32 = window.user32
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


OTHER_GAMES = ("GTA5.exe", "GTA5_Enhanced.exe", "RDR2.exe", "Cyberpunk2077.exe")   # games this machine captures


def _process_running(exe):
    try:
        mem.find_pid(exe)
        return True
    except RuntimeError:
        return False


def running_app():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return str(winreg.QueryValueEx(k, "RunningAppID")[0])
    except OSError:
        return "0"


def _post_close(h):
    user32.PostMessageW(h, 0x0010, 0, 0)   # WM_CLOSE


def steam_error():
    """Closes Steam's error box ("Unable to launch game, ...") if one is up; True if there was one."""
    try:
        steam = mem.find_pid("steam.exe")
    except RuntimeError:
        return False
    hit = False
    for h in window.windows_titled("Error", "#32770"):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == steam:
            _post_close(h)
            hit = True
    return hit


def close_game(log=print, ed=LEGACY):
    for name in ed.close:
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    # a launch Steam gave up on leaves its "Launching..." window open, and Steam ignores new starts
    steam_error()
    for h in window.windows_titled("Launching...", "SDL_app"):
        _post_close(h)
    t = time.time()
    while running_app() == ed.steam_app and time.time() - t < 60:
        time.sleep(1)
    if running_app() == ed.steam_app:
        log("Steam still lists %s as running; the start may fail" % ed.name)


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


def answer_steam_dialog(log=print, ed=LEGACY):
    """Steam's launch-option dialog, if it is up: story mode, then Play. True if it was answered."""
    for h in window.windows_titled(ed.dialog_title, "SDL_app"):
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


def selected_tab(img):
    """Which of Enhanced's landing-page tabs is selected (0 ONLINE, 1 GTA+, 2 STORY), from the white
    box behind it; None when no such box is there (another screen)."""
    a = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = a.shape
    band = a[int(h * 0.062):int(h * 0.080), :int(w * 0.30)]
    filled = band.mean(axis=0) > 200
    xs = np.flatnonzero(filled)
    if len(xs) < w * 0.03 or len(xs) > w * 0.12:      # a tab-sized box, not a bright screen
        return None
    centre = xs.mean() / w
    best = min(range(len(TABS)), key=lambda i: abs(TABS[i] - centre))
    return best if abs(TABS[best] - centre) < 0.03 else None


def start(exchange, client=(2560, 1440), timeout=480, log=print, snapshots=None, ed=LEGACY):
    """Restarts the game into story mode; returns once the loader's heartbeat is up."""
    window.keep_awake()   # the landing page is found in grabs of the screen
    close_game(log, ed)
    other = running_app()
    if other not in ("0", ed.steam_app):
        # Steam runs one game at a time; it answers a second start with "Unable to launch game"
        raise RuntimeError("Steam is running another game (app %s); close it before starting %s" % (other, ed.name))
    # another game started from its exe (the Cyberpunk session does, 2026-11-21) is not in Steam's
    # RunningAppID, and two games fighting over focus and keys break both captures
    for exe in OTHER_GAMES:
        if exe != ed.exe and _process_running(exe):
            raise RuntimeError("%s is running; close it (or wait for its session to yield) before starting %s" % (exe, ed.name))
    try:
        os.remove(os.path.join(exchange, "heartbeat.txt"))
    except OSError:
        pass
    os.startfile("steam://rungameid/%s" % ed.steam_app)
    log("starting %s through Steam" % ed.name)
    return drive(exchange, client, timeout, log, snapshots, ed)


def drive(exchange, client=(2560, 1440), timeout=480, log=print, snapshots=None, ed=LEGACY):
    """Takes a starting game to story mode (Steam's dialog, the landing page) until the loader's
    heartbeat is up; also for attaching to a game already on its way."""
    window.keep_awake()
    t0 = time.time()
    last_click, last_answer, shots, sized = 0.0, 0.0, 0, False
    while time.time() - t0 < timeout:
        time.sleep(2)
        if redlua.heartbeat_age(exchange) < 3:
            log("loader heartbeat is up after %.0f s" % (time.time() - t0))
            break
        if steam_error():
            close_game(log, ed)
            raise RuntimeError("Steam could not launch %s (its error box is closed); is another game running?" % ed.name)
        try:
            pid = mem.find_pid(ed.exe)
        except RuntimeError:
            # Steam's launch-option dialog comes before the game starts; other Steam windows can
            # carry the same title later (Enhanced's), so only answer it while there is no game.
            # After Play, Steam keeps a window of that title up for a minute while Rockstar's
            # launcher starts (Enhanced, 2026-11-21): answer again only if it is still there later.
            if time.time() - last_answer > 30 and answer_steam_dialog(log, ed):
                last_answer = time.time()
            continue
        h = window.find_game_window(pid, ed.window_class)
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
        if ed.landing == "tabs":
            tab = selected_tab(img)
            if tab is not None and redlua.heartbeat_age(exchange) > 3:
                if tab == 2:
                    window.press(h, "Enter")
                    log("resumed the story (Enter on the STORY tab)")
                else:
                    window.press(h, 0x12)   # E: one tab to the right
                    log("landing page on tab %d; E" % tab)
                last_click = time.time() - 8   # look again in about 2 s
            continue
        target = landing_target(img)
        if target and redlua.heartbeat_age(exchange) > 3:
            pt = wt.POINT(*target)
            user32.ClientToScreen(h, ctypes.byref(pt))
            click_screen(pt.x, pt.y)
            log("clicked STORY MODE at %s" % (target,))
            last_click = time.time()
    else:
        raise RuntimeError("%s did not reach story mode with the loader running in %d s" % (ed.name, timeout))
    redlua.minimize_console()
    h = window.find_game_window(mem.find_pid(ed.exe), ed.window_class)
    window.focus(h)
    if not window.set_client_size(h, *client):
        log("the game window is %s, not %s" % (window.client_size(h), client))
    return h


if __name__ == "__main__":
    from . import adapter
    snaps = sys.argv[sys.argv.index("--snapshots") + 1] if "--snapshots" in sys.argv else None
    if "--enhanced" in sys.argv:
        start(adapter.EXCHANGE_ENHANCED, snapshots=snaps, ed=ENHANCED)
    else:
        start(adapter.EXCHANGE, snapshots=snaps)
