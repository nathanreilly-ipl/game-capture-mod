"""A game window on an X display (a Windows game under Proton, capture/host/proton.py): the same
functions as window_win32.py. Reached through window.py. Game-agnostic.

The window is found and driven with xdotool; a grab reads the window's pixels from the X server
(XGetImage through ctypes). On the headless display the game is alone: nothing takes its focus,
and with no window manager a window has no frame, so its size is its client size.

A handle is the X window id (an int).
"""
import ctypes
import ctypes.util
import subprocess
import time

from capture.host import proton

# key names as window_win32.SCAN has them -> X key names
KEYS = {"Enter": "Return", "Esc": "Escape", "Space": "space", "Back": "BackSpace", "Q": "q", "E": "e",
        "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right", "F3": "F3", "F4": "F4", "F5": "F5", "F6": "F6",
        "Grave": "grave"}
# a caller may pass a keyboard scan code where window_win32.SCAN has no name for the key
SCAN_KEYS = {0x1C: "Return", 0x01: "Escape", 0x39: "space", 0x0E: "BackSpace", 0x10: "q", 0x12: "e", 0x48: "Up", 0x50: "Down",
             0x4B: "Left", 0x4D: "Right", 0x3D: "F3", 0x3E: "F4", 0x3F: "F5", 0x40: "F6", 0x29: "grave"}
SCAN_KEYS.update({0x3B + i: "F%d" % (i + 1) for i in range(10)})     # F1..F10 (Death Stranding's photo mode: F8)
SCAN_KEYS.update({0x57: "F11", 0x58: "F12"})
# Windows virtual-key codes -> X key names, for press_vk (the function keys F1..F24 and letters, digits)
VK = {0x0D: "Return", 0x1B: "Escape", 0x20: "space", 0x08: "BackSpace",
      0x10: "Shift_L", 0x11: "Control_L", 0x12: "Alt_L"}           # Alt: Death Stranding's photo mode controls
VK.update({0x70 + i: "F%d" % (i + 1) for i in range(24)})
VK.update({c: chr(c).lower() for c in range(0x41, 0x5B)})
VK.update({c: chr(c) for c in range(0x30, 0x3A)})


def _xdo(*args, timeout=15):
    """xdotool's output lines, [] when it fails (no such window, no display)."""
    exe = proton.tool("xdotool")
    if not exe:
        raise RuntimeError("xdotool is not on this machine (run: %s host setup)" % proton.CLI)
    try:
        r = subprocess.run([exe] + [str(a) for a in args], env=proton.x_env(), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    return r.stdout.split() if r.returncode == 0 else []


def _geometry(win):
    out = dict(line.split("=", 1) for line in _xdo("getwindowgeometry", "--shell", win) if "=" in line)
    try:
        return int(out["X"]), int(out["Y"]), int(out["WIDTH"]), int(out["HEIGHT"])
    except (KeyError, ValueError):
        return None


def find_game_window(pid, window_class=None):
    """The game's own window: the largest visible window of the process. window_class (a Win32
    class) cannot be asked of an X window and is not used."""
    best, area = None, 0
    for w in _xdo("search", "--onlyvisible", "--pid", pid):
        g = _geometry(int(w))
        if g and g[2] * g[3] > area:
            best, area = int(w), g[2] * g[3]
    return best


def windows_titled(title, window_class=None):
    """Visible windows with exactly this title."""
    out = []
    for w in _xdo("search", "--onlyvisible", "--name", "^%s$" % title.replace("\\", "\\\\")):
        out.append(int(w))
    return out


def keep_awake():
    """Nothing to do: a headless display does not sleep."""


def desktop_size():
    """The display's size; while it is not up, the size it will be started with."""
    out = _xdo("getdisplaygeometry")
    if len(out) == 2:
        return int(out[0]), int(out[1])
    w, h = proton.tools()["screen"].lower().split("x")
    return int(w), int(h)


def is_foreground(win):
    out = _xdo("getwindowfocus")
    return bool(win) and bool(out) and int(out[0]) == int(win)


def client_size(win):
    g = _geometry(win) if win else None
    return (g[2], g[3]) if g else None


def set_client_size(win, width, height):
    if not win:
        return False
    if client_size(win) == (width, height):
        return True
    _xdo("windowsize", win, width, height)
    time.sleep(1.0)
    return client_size(win) == (width, height)


def focus(win):
    """Gives the window the keyboard. True if it has it afterwards."""
    if not win:
        return False
    if is_foreground(win):
        return True
    _xdo("windowfocus", win)
    time.sleep(0.2)
    return is_foreground(win)


def _press(win, name, hold_s):
    if not is_foreground(win):
        return False
    _xdo("keydown", name)
    time.sleep(hold_s)
    _xdo("keyup", name)
    return True


def press(win, key, hold_s=0.08):
    """Presses one key (a name as in window_win32.SCAN, or an X key name), only while the game
    window has the keyboard."""
    if isinstance(key, int):
        if key not in SCAN_KEYS:
            raise ValueError("no X key for scan code 0x%02X" % key)
        return _press(win, SCAN_KEYS[key], hold_s)
    return _press(win, KEYS.get(key, key), hold_s)


def press_vk(win, vk, scan=0, hold_s=0.08):
    """Presses one key by its Windows virtual-key code (Wine turns the X key back into it)."""
    if vk not in VK:
        raise ValueError("no X key for virtual key 0x%02X" % vk)
    return _press(win, VK[vk], hold_s)


def paste(win, text, hold_s=0.03):
    """Puts text on the X clipboard (Wine hands it to the game as the Windows clipboard) and
    sends Ctrl+V, only while the game window has the keyboard: Ctrl down, V down, V up, Ctrl up,
    hold_s apart as window_win32.paste does. Sent at once (xdotool's ctrl+v), the game often saw
    a plain "v" (The Witcher 3's console filled with lines of "v": about every second long
    command missed its first try, 2026-11-24)."""
    if not is_foreground(win):
        return False
    exe = proton.tool("xclip") or proton.tool("xsel")
    if not exe:
        raise RuntimeError("no xclip or xsel on this machine: pasting into the game needs one (%s host setup)" % proton.CLI)
    args = [exe, "-selection", "clipboard", "-i"] if exe.rstrip("/").endswith("xclip") else [exe, "--clipboard", "--input"]
    subprocess.run(args, input=text.encode("utf-8"), env=proton.x_env(), timeout=15, check=True)
    h = "%.3f" % max(0.0, hold_s)
    _xdo("keydown", "Control_L", "sleep", h, "keydown", "v", "sleep", h, "keyup", "v", "sleep", h, "keyup", "Control_L")
    time.sleep(hold_s)
    return True


class _XImage(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
                ("data", ctypes.POINTER(ctypes.c_ubyte)), ("byte_order", ctypes.c_int), ("bitmap_unit", ctypes.c_int),
                ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int),
                ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int)]


_x11 = None


def _xlib():
    global _x11
    if _x11 is None:
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x.XGetImage.restype = ctypes.POINTER(_XImage)
        x.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_ulong, ctypes.c_int]
        x.XFree.argtypes = [ctypes.c_void_p]
        _x11 = x
    return _x11


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong), ("format", ctypes.c_int),
                ("data", ctypes.c_long * 5), ("pad", ctypes.c_long * 12)]    # padded to the size of an XEvent


def rect(win):
    """The window on the screen: (left, top, right, bottom), or None."""
    g = _geometry(win) if win else None
    return (g[0], g[1], g[0] + g[2], g[1] + g[3]) if g else None


def click_screen(x, y):
    """A left click at a point of the screen."""
    _xdo("mousemove", int(x), int(y))
    time.sleep(0.3)
    _xdo("mousedown", 1)
    time.sleep(0.08)
    _xdo("mouseup", 1)


def click(win, x, y):
    """A left click at a point of the window's client area."""
    r = rect(win)
    if r:
        click_screen(r[0] + x, r[1] + y)


def middle_click(win, hold_s=0.1):
    """A middle click where the pointer is, with the window brought to the front first."""
    focus(win)
    _xdo("mousedown", 2)
    time.sleep(hold_s)
    _xdo("mouseup", 2)


def window_pid(win):
    """The process a window belongs to (0 if unknown)."""
    out = _xdo("getwindowpid", win)
    return int(out[0]) if out else 0


def move(win, x, y):
    """Puts the window's top left corner at a point of the screen."""
    if win:
        _xdo("windowmove", win, int(x), int(y))


def hide(win):
    """Takes a window off the screen without closing it (a console, a launcher that stays up)."""
    if win:
        _xdo("windowunmap", win)


def close(win):
    """Asks the window to close, as a window manager's close button does (WM_DELETE_WINDOW, which
    Wine hands the game as WM_CLOSE): the game shuts down in its own way and writes what it
    writes on exit. True if the request was sent."""
    if not win:
        return False
    x = _xlib()
    d = x.XOpenDisplay(proton.tools()["display"].encode())
    if not d:
        return False
    try:
        x.XInternAtom.restype = ctypes.c_ulong
        x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
        x.XFlush.argtypes = [ctypes.c_void_p]
        ev = _ClientMessage(type=33, send_event=1, window=int(win), message_type=x.XInternAtom(d, b"WM_PROTOCOLS", 0), format=32)
        ev.data[0] = x.XInternAtom(d, b"WM_DELETE_WINDOW", 0)
        sent = x.XSendEvent(d, int(win), 0, 0, ctypes.byref(ev))
        x.XFlush(d)
        return bool(sent)
    finally:
        x.XCloseDisplay(d)


def grab(win):
    """A picture of the window as it is on the display (PIL image), or None."""
    from PIL import Image
    g = _geometry(win) if win else None
    if not g:
        return None
    # only what is on the screen can be read: a window reaching past an edge gives BadMatch, and
    # Xlib's answer to that ends the program (RDR2's window stood at 0,13 on a 1440-line screen)
    sw, sh = desktop_size()
    size = (min(g[2], sw - max(g[0], 0)), min(g[3], sh - max(g[1], 0)))
    if size[0] <= 0 or size[1] <= 0:
        return None
    x = _xlib()
    d = x.XOpenDisplay(proton.tools()["display"].encode())
    if not d:
        return None
    try:
        img = x.XGetImage(d, int(win), max(-g[0], 0), max(-g[1], 0), size[0], size[1], 0xFFFFFFFF, 2)   # all planes, ZPixmap
        if not img:
            return None
        im = img.contents
        if im.bits_per_pixel != 32:
            return None
        raw = ctypes.string_at(im.data, im.bytes_per_line * im.height)
        out = Image.frombuffer("RGB", (im.width, im.height), raw, "raw", "BGRX", im.bytes_per_line, 1).copy()
        x.XFree(im.data)   # XDestroyImage is a macro: free the pixels, then the image
        x.XFree(img)
        return out
    finally:
        x.XCloseDisplay(d)
