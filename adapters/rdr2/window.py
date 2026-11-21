"""The game window: find it, tell whether it has focus, give it focus (Windows only)."""
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

GAME_CLASS = "sgaWindow"


def find_game_window(pid):
    """The game's own window (class sgaWindow), not RedLua's console. None if absent."""
    found = []

    def cb(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == GAME_CLASS:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def is_foreground(hwnd):
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def client_size(hwnd):
    r = wt.RECT()
    if not hwnd or not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    return r.right - r.left, r.bottom - r.top


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


SCAN = {"F3": 0x3D, "F4": 0x3E, "F5": 0x3F, "F6": 0x40, "Enter": 0x1C, "Esc": 0x01}


def press(hwnd, key, hold_s=0.08):
    """Presses one key (a SCAN name or scan code), only while the game window is in front."""
    if not is_foreground(hwnd):
        return False
    scan = SCAN.get(key, key)
    for flags in (0x0008, 0x0008 | 0x0002):  # KEYEVENTF_SCANCODE, then | KEYEVENTF_KEYUP
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


def grab(hwnd):
    """A picture of the window's client area as it is on screen (PIL image), or None."""
    from PIL import ImageGrab
    size = client_size(hwnd)
    if not size:
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return ImageGrab.grab(bbox=(pt.x, pt.y, pt.x + size[0], pt.y + size[1]), all_screens=True)


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
