"""GTA V Enhanced's graphics settings through its pause menu, by key presses (game-specific).

For what has no native and must change at one frozen instant: ray tracing on or off, so
tools/preset_ab.py can compare both (and DLSS 5 over each) on the same frozen world. Enhanced
applies the change live, without a restart (measured 2026-11-21, build 1.0.1158.13).

The path, the same every time (the menu opens on MAP and every list on its first entry):
    Esc            pause menu, tabs MAP BRIEF STATS SETTINGS GAME ONLINE
    E x3           SETTINGS (Q/E browse; Enter is never pressed on ONLINE)
    Enter, Down x6 the settings list on Graphics (Gamepad, Keyboard / Mouse, Key Bindings, Audio,
                   Camera, Display, Graphics, ...)
    Enter, Down x10  Enable Ray Tracing (after Ignore Suggested Limits, the video settings and the
                   graphics preset)
    Left / Right   Off / On; "Apply Changes" appears
    Space          applies; settings.xml is rewritten
    Esc x3         back to the game
Each step is checked on a grab of the window (which tab and which row are highlighted, the
"Apply Changes" prompt appearing), and the outcome in settings.xml. Positions are fractions of
the client area, measured at 2560x1440 (the capture size). Scripts (our loader and session) do
not run while the pause menu is open: its heartbeat stops and resumes when the menu closes.
"""
import os
import re
import time

import numpy as np

from ..common import window

TABS = (0.218, 0.331, 0.444, 0.557, 0.670, 0.784)   # MAP .. ONLINE, centres across
TAB_Y = 0.186
SETTINGS_TAB, ONLINE_TAB = 3, 5
LIST_X, LIST_ROW0, LIST_STEP = (0.17, 0.38), 0.239, 0.0375   # the settings list: Gamepad's row, row spacing
GRAPHICS_ROW = 6
BOTTOM_ROW_Y, PANEL_X = 0.801, (0.41, 0.70)    # where the selection sits after scrolling down
APPLY_PROMPT = (0.652, 0.718, 0.957, 0.978)     # "Apply Changes" in the bottom bar (x0, x1, y0, y1)
PANEL = (0.39, 0.84, 0.29, 0.83)                 # the settings panel's rows (x0, x1, y0, y1)


class MenuError(RuntimeError):
    pass


def settings_xml():
    return os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "Rockstar Games", "GTAV Enhanced", "settings.xml")


def read_settings(path=None):
    with open(path or settings_xml(), encoding="utf-8", errors="replace") as f:
        return dict(re.findall(r'<(\w+) value="([^"]*)"', f.read()))


def _gray(hwnd):
    img = window.grab(hwnd)
    if img is None:
        raise MenuError("no picture of the game window")
    return np.asarray(img.convert("L").resize((1280, 720)), dtype=np.float32)


def _box(a, x0, x1, y0, y1):
    h, w = a.shape
    return a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def selected_tab(a):
    """The highlighted tab (a white box among dark ones), or None when the pause menu is not open.
    Measured: the lit tab 200-225, the others 25-80 (also over a sunny street); a bright scene
    without the menu lights several places at once."""
    m = [float(_box(a, x - 0.035, x + 0.035, TAB_Y - 0.01, TAB_Y + 0.01).mean()) for x in TABS]
    lit = [i for i, v in enumerate(m) if v > 170]
    if len(lit) == 1 and all(v < 110 for i, v in enumerate(m) if i != lit[0]):
        return lit[0]
    return None


def selected_row(a):
    """The highlighted entry of the settings list (0 Gamepad ... 10 Saving), or None."""
    lit = [i for i in range(11)
           if _box(a, LIST_X[0], LIST_X[1], LIST_ROW0 + i * LIST_STEP - 0.008, LIST_ROW0 + i * LIST_STEP + 0.008).mean() > 170]
    return lit[0] if len(lit) == 1 else None


def bottom_row_selected(a):
    return _box(a, PANEL_X[0], PANEL_X[1], BOTTOM_ROW_Y - 0.008, BOTTOM_ROW_Y + 0.008).mean() > 170


def prompt_appeared(before, after):
    """Whether "Apply Changes" appeared in the bottom bar between two grabs (a bright scene behind
    the menu can look like text there, so the test is the change, not the brightness)."""
    return float(np.abs(_box(after, *APPLY_PROMPT) - _box(before, *APPLY_PROMPT)).mean()) > 12.0


def _until(hwnd, test, seconds):
    """Grabs until test(grab) holds; the grab, or None after `seconds`."""
    deadline = time.time() + seconds
    while True:
        a = _gray(hwnd)
        if test(a):
            return a
        if time.time() > deadline:
            return None
        time.sleep(0.15)


def _press(hwnd, *keys, pause=0.35):
    for k in keys:
        if not window.press(hwnd, k):
            raise MenuError("the game window lost focus")
        time.sleep(pause)


def _close(hwnd):
    """Esc until the pause menu is gone. Esc in the game opens it again, and the menu fades out
    over about a second (slower while the world is frozen), so after each Esc this waits up to 3 s
    for it to go before pressing again."""
    for _ in range(5):
        if selected_tab(_gray(hwnd)) is None:
            return
        _press(hwnd, "Esc", pause=0.4)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if selected_tab(_gray(hwnd)) is None:
                time.sleep(0.5)
                if selected_tab(_gray(hwnd)) is None:
                    return
            time.sleep(0.3)
    raise MenuError("the pause menu did not close")


def set_ray_tracing(hwnd, on, log=print, xml=None):
    """Switches the game's ray tracing; True if it changed, False if it already was so."""
    xml = xml or settings_xml()
    want = "true" if on else "false"
    before = read_settings(xml)
    if before.get("Raytracing_Enabled") == want:
        return False
    if not window.focus(hwnd):
        raise MenuError("the game window is not in front")
    for attempt in range(2):   # right after the menu closed, the game can ignore Esc for a moment
        _press(hwnd, "Esc", pause=0.5)
        if _until(hwnd, lambda a: selected_tab(a) is not None, 3.0) is not None:
            break
    try:
        if selected_tab(_gray(hwnd)) is None:
            raise MenuError("the pause menu did not open")
        # Keys are sometimes dropped (more so while the world is frozen), so every move is
        # pressed, then confirmed on screen, before the next
        for _ in range(8):
            tab = selected_tab(_gray(hwnd))
            if tab == SETTINGS_TAB:
                break
            if tab is None or tab > SETTINGS_TAB:
                raise MenuError("unexpected tab %s" % tab)
            _press(hwnd, "E", pause=0.1)
            _until(hwnd, lambda a: selected_tab(a) != tab, 1.5)
        if selected_tab(_gray(hwnd)) != SETTINGS_TAB:
            raise MenuError("could not reach the SETTINGS tab")
        _press(hwnd, "Enter", pause=0.1)
        if _until(hwnd, lambda a: selected_row(a) == 0, 2.0) is None:
            raise MenuError("the settings list did not take the focus")
        for _ in range(GRAPHICS_ROW + 4):
            row = selected_row(_gray(hwnd))
            if row == GRAPHICS_ROW:
                break
            _press(hwnd, "Down" if row is None or row < GRAPHICS_ROW else "Up", pause=0.1)
            _until(hwnd, lambda a: selected_row(a) != row, 1.5)
        if selected_row(_gray(hwnd)) != GRAPHICS_ROW:
            raise MenuError("could not reach Graphics in the settings list")
        _press(hwnd, "Enter", pause=0.8)
        for i in range(10):   # Enable Ray Tracing is ten entries down; each step must move the panel
            before_step = _box(_gray(hwnd), *PANEL)
            for attempt in range(3):
                _press(hwnd, "Down", pause=0.1)
                if _until(hwnd, lambda a: float(np.abs(_box(a, *PANEL) - before_step).mean()) > 2.0, 1.5) is not None:
                    break
            else:
                raise MenuError("the graphics list did not move at entry %d" % (i + 1))
        time.sleep(0.4)
        a0 = _gray(hwnd)
        if not bottom_row_selected(a0):
            raise MenuError("Enable Ray Tracing is not where expected")
        _press(hwnd, "Right" if on else "Left", pause=0.6)
        if not prompt_appeared(a0, _gray(hwnd)):
            raise MenuError("no Apply Changes prompt after switching Enable Ray Tracing")
        # Space applies; once in a frozen run it did not take (2026-11-21), so wait for settings.xml
        # and press it once more if nothing was written
        for attempt in range(2):
            _press(hwnd, "Space", pause=0.2)
            deadline = time.time() + 6.0
            while time.time() < deadline and read_settings(xml).get("Raytracing_Enabled") != want:
                time.sleep(0.5)
            if read_settings(xml).get("Raytracing_Enabled") == want:
                break
            log("  settings.xml unchanged after Apply; pressing Space again")
        time.sleep(1.5)
    finally:
        _close(hwnd)
    after = read_settings(xml)
    if after.get("Raytracing_Enabled") != want:
        raise MenuError("settings.xml has Raytracing_Enabled=%s, not %s" % (after.get("Raytracing_Enabled"), want))
    other = sorted(k for k in set(before) | set(after) if k != "Raytracing_Enabled" and before.get(k) != after.get(k))
    if other:
        log("  settings.xml also changed: %s" % ", ".join("%s %s -> %s" % (k, before.get(k), after.get(k)) for k in other))
    log("  ray tracing %s (the game's settings menu)" % ("on" if on else "off"))
    return True
