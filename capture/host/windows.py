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
