"""A game on Windows: it runs as it is, in the user's own account."""
import os
import subprocess
import time

CLI = ".\\capture.ps1"


def pids(exe_name):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe_name, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == exe_name.lower() and parts[1].isdigit():
            found.append(int(parts[1]))
    return found


def stop(game, exe_names, wait_s=60):
    """Ends the processes with these names and waits until the first of them (the game) is gone."""
    for name in exe_names:
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    t = time.time()
    while exe_names and pids(exe_names[0]) and time.time() - t < wait_s:
        time.sleep(1)


def start(game, exe, args=(), cwd=None, dll_overrides=None, app_id=None):
    """Starts the game's exe. dll_overrides and app_id only matter under Proton."""
    return subprocess.Popen([exe] + list(args), cwd=cwd)


def game_path(path, game=None):
    return path


def use_prefix(game, name):
    pass


def host_path(path, game=None):
    return path


def user_dir(game, kind):
    """kind: local_appdata, appdata, documents or saved_games."""
    home = os.environ.get("USERPROFILE", "")
    return {"local_appdata": os.environ.get("LOCALAPPDATA", ""), "appdata": os.environ.get("APPDATA", ""),
            "documents": os.path.join(home, "Documents"), "saved_games": os.path.join(home, "Saved Games")}[kind]


def program_data(game=None):
    return os.environ.get("ProgramData", r"C:\ProgramData")


def start_beside_steam(game, exe, args=(), cwd=None, dll_overrides=None, app_id=None, limit_cpus=False, wait_s=900):
    """On Windows a game started from its exe finds the Steam client that runs: an ordinary start."""
    return start(game, exe, args, cwd=cwd, dll_overrides=dll_overrides, app_id=app_id)


def check_start(game):
    """Nothing stops a start here (the Linux side checks the GPUs a process sees)."""


def steam_launch(game, app_id):
    """Asks the Steam client to start a game."""
    os.startfile("steam://rungameid/%s" % app_id)


def gpu_name():
    return None     # not asked on Windows: nothing there depends on it


def gpu_adapters():
    """[{index, name, vendor, dedicated_mb, software}] in DXGI's order, the order a Direct3D game
    lists them in unless it asks by preference (RDR2 counts the 5090 first either way). The GPU that
    drives the main display comes first: on the development PC (an RTX 5090 beside the processor's AMD
    Radeon) the AMD came first while the monitor showed the motherboard's input (2026-11-24)."""
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                    ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
                    ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", ctypes.c_uint)]

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    def call(obj, slot, *types):
        """A COM method by its place in the object's table: IUnknown 0-2, IDXGIObject 3-6,
        IDXGIFactory 7-11, IDXGIFactory1.EnumAdapters1 12; IDXGIAdapter 7-9, IDXGIAdapter1.GetDesc1 10."""
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[slot])

    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    try:
        if ctypes.WinDLL("dxgi").CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return []
    except OSError:
        return []
    out = []
    try:
        while len(out) < 16:
            adapter = ctypes.c_void_p()
            if call(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(factory, len(out), ctypes.byref(adapter)) != 0:
                break   # DXGI_ERROR_NOT_FOUND: no more
            d = DESC1()
            call(adapter, 10, ctypes.POINTER(DESC1))(adapter, ctypes.byref(d))
            call(adapter, 2)(adapter)
            out.append({"index": len(out), "name": d.Description, "vendor": d.VendorId,
                        "dedicated_mb": d.DedicatedVideoMemory >> 20, "software": bool(d.Flags & 2)})
    finally:
        call(factory, 2)(factory)
    return out
