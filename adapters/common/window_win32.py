"""A game window on Windows (Win32): find it, tell whether it has focus, give it focus, send keys,
grab it. Reached through window.py, which picks this or window_x11.py. Game-agnostic: adapters pass
their game's window class."""
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Report window sizes in real pixels, not scaled by the display's DPI setting.
try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # per-monitor aware
except (OSError, AttributeError):
    user32.SetProcessDPIAware()

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]

def find_game_window(pid, window_class):
    """The game's own window (a visible window of the process with this class, e.g. RDR2's
    sgaWindow, GTA V's grcWindow), not RedLua's console. None if absent."""
    found = []

    def cb(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == window_class:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def windows_titled(title, window_class=None):
    """Visible top-level windows with exactly this title (and class, if given)."""
    out = []

    def cb(h, _):
        if user32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, t, 256)
            c = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, c, 64)
            if t.value == title and (window_class is None or c.value == window_class):
                out.append(h)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def keep_awake():
    """Keeps the display (and the machine) awake while this process runs. With the display
    asleep, grabs of the screen return the last picture shown (seen 2026-11-21), so anything
    read off the screen (a launcher's menus, the colour check) goes stale."""
    kernel32.SetThreadExecutionState(0x80000000 | 0x00000002 | 0x00000001)  # CONTINUOUS | DISPLAY | SYSTEM


def desktop_size():
    """The primary display's size in pixels."""
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def is_foreground(hwnd):
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def client_size(hwnd):
    r = wt.RECT()
    if not hwnd or not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    return r.right - r.left, r.bottom - r.top


def set_client_size(hwnd, width, height):
    """Resizes a window so its client area (what the game renders) is width x height, keeping
    its top-left corner. Some games size the outer window from their settings, which leaves a
    smaller client area (GTA V: 2554x1400 for 2560x1440). True if the size is right afterwards."""
    if not hwnd:
        return False
    if client_size(hwnd) == (width, height):
        return True
    outer, inner = wt.RECT(), wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    user32.GetClientRect(hwnd, ctypes.byref(inner))
    bw = (outer.right - outer.left) - (inner.right - inner.left)
    bh = (outer.bottom - outer.top) - (inner.bottom - inner.top)
    user32.SetWindowPos(hwnd, None, outer.left, outer.top, width + bw, height + bh, 0x0004 | 0x0010)  # NOZORDER, NOACTIVATE
    time.sleep(1.0)
    return client_size(hwnd) == (width, height)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


SCAN = {"F3": 0x3D, "F4": 0x3E, "F5": 0x3F, "F6": 0x40, "Enter": 0x1C, "Esc": 0x01, "Space": 0x39, "Back": 0x0E,
        "Q": 0x10, "E": 0x12, "Up": 0x48, "Down": 0x50, "Left": 0x4B, "Right": 0x4D,
        "Grave": 0x29, "Ctrl": 0x1D, "V": 0x2F}   # Grave: the key left of 1 (` and ~)
EXTENDED = {"Up", "Down", "Left", "Right"}   # the arrow keys, not the number pad's


def press(hwnd, key, hold_s=0.08):
    """Presses one key (a SCAN name or scan code), only while the game window is in front."""
    if not is_foreground(hwnd):
        return False
    scan = SCAN.get(key, key)
    ext = 0x0001 if key in EXTENDED else 0    # KEYEVENTF_EXTENDEDKEY
    for flags in (0x0008 | ext, 0x0008 | ext | 0x0002):  # KEYEVENTF_SCANCODE, then | KEYEVENTF_KEYUP
        i = _INPUT(type=1)
        i.ki = _KEYBDINPUT(0, scan, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))
        time.sleep(hold_s)
    return True


def press_vk(hwnd, vk, scan=0, hold_s=0.08):
    """Presses one key by virtual-key code (with its scan code), for hooks that read either;
    only while the game window is in front."""
    if not is_foreground(hwnd):
        return False
    for flags in (0, 0x0002):  # key down, then KEYEVENTF_KEYUP
        i = _INPUT(type=1)
        i.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))
        time.sleep(hold_s)
    return True


def set_clipboard(text):
    """Puts text on the Windows clipboard (it replaces what the user had there)."""
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    data = (text + "\0").encode("utf-16-le")
    for _ in range(40):                 # another program may hold the clipboard for a moment
        if user32.OpenClipboard(None):
            break
        time.sleep(0.025)
    else:
        raise OSError("the clipboard is held by another program")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))      # GMEM_MOVEABLE; the clipboard owns it after SetClipboardData
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(13, h):           # CF_UNICODETEXT
            raise OSError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def paste(hwnd, text, hold_s=0.03):
    """Puts text on the clipboard and sends Ctrl+V, only while the game window is in front. For a
    game that takes long commands through a console of its own (The Witcher 3's debug console took
    30,000 characters at once, 2026-11-23)."""
    if not is_foreground(hwnd):
        return False
    set_clipboard(text)
    for scan, flags in ((SCAN["Ctrl"], 0x0008), (SCAN["V"], 0x0008), (SCAN["V"], 0x000A), (SCAN["Ctrl"], 0x000A)):
        i = _INPUT(type=1)
        i.ki = _KEYBDINPUT(0, scan, flags, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))
        time.sleep(hold_s)
    return True


def grab(hwnd):
    """A picture of the window's client area as it is on screen (PIL image), or None."""
    from PIL import ImageGrab
    size = client_size(hwnd)
    if not size:
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return ImageGrab.grab(bbox=(pt.x, pt.y, pt.x + size[0], pt.y + size[1]), all_screens=True)


user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


def rect(hwnd):
    """The window on the screen: (left, top, right, bottom), or None."""
    r = wt.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def click_screen(x, y):
    """A left click at a point of the screen."""
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.3)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def click(hwnd, x, y):
    """A left click at a point of the window's client area."""
    pt = wt.POINT(int(x), int(y))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    click_screen(pt.x, pt.y)


def window_pid(hwnd):
    """The process a window belongs to (0 if unknown)."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def move(hwnd, x, y):
    """Puts the window's top left corner at a point of the screen."""
    if hwnd:
        user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)   # NOSIZE | NOZORDER | NOACTIVATE


def hide(hwnd):
    """Takes a window off the screen without closing it (minimized, not activated)."""
    if hwnd:
        user32.ShowWindow(hwnd, 7)   # SW_SHOWMINNOACTIVE


def close(hwnd):
    """Asks the window to close, as its close button does (WM_CLOSE): the game shuts down in its
    own way and writes what it writes on exit. True if the request was sent."""
    return bool(hwnd) and bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))


def focus(hwnd):
    """Brings the window to the front. True if it is the foreground window afterwards."""
    if not hwnd:
        return False
    if is_foreground(hwnd):
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    me = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(me, fg_thread, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(me, fg_thread, False)
    time.sleep(0.4)
    return is_foreground(hwnd)
