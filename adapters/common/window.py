"""A game window: find it, tell whether it has focus, give it focus, send keys, grab it.
Game-agnostic: adapters pass their game's process and window class.

The same functions on either system: window_win32.py on Windows, window_x11.py where the game
runs under Proton on an X display (capture/host). A window handle is whatever find_game_window
returned (an HWND, or an X window id); adapters only pass it back.

    find_game_window(pid, window_class) -> handle or None
    windows_titled(title, window_class=None) -> [handle]
    focus(handle) -> bool, is_foreground(handle) -> bool
    client_size(handle) -> (w, h), set_client_size(handle, w, h) -> bool, desktop_size() -> (w, h)
    press(handle, key, hold_s), press_vk(handle, vk, scan, hold_s)      only while the window is in front
    grab(handle) -> PIL image of the window as it is on screen
    close(handle) -> bool                           ask it to close, as its close button does
    keep_awake()
"""
import os

if os.name == "nt":
    from .window_win32 import *   # noqa: F401,F403
else:
    from .window_x11 import *     # noqa: F401,F403
