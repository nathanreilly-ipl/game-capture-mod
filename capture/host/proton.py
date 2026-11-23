"""A Windows game on Linux: under Proton, inside the Steam Linux Runtime container, on a headless
X display. Needs no root and no Steam client (found on a CoreWeave Slurm node, 2026-11-23:
Ubuntu 22.04 image, NVIDIA 580.105.08, one RTX PRO 6000; docs/LINUX_PORT.md).

What it uses lives under out/host (config "host.dir" or CAPTURE_HOST moves it), put there by
`capture host setup` (setup.py):

    proton/<build>/proton              Proton (GE-Proton11 needs Steam Linux Runtime 4)
    runtime/<name>/_v2-entry-point     the Steam Linux Runtime: Proton runs inside its container
                                       (pressure-vessel; unprivileged user namespaces are enough)
    sysroot/                           Ubuntu packages unpacked, not installed: Xvfb, xkbcomp, xdotool
    nvidia/<driver version>/           nvngx.dll and _nvngx.dll from NVIDIA's driver package of the
                                       machine's driver version; DLSS needs them in the prefix

Each game has its own Proton prefix, out/proton/<game> (config games.<game>.prefix): its C: drive,
registry and the game user's folders. The rest of this machine is drive Z: to the game, so a path
here is Z:\\path\\with\\backslashes there (game_path).

The display is Xvfb: the game's Direct3D 12 goes through VKD3D-Proton to NVIDIA's Vulkan driver,
which presents to Xvfb, and a screen grab of it shows the game (measured 2026-11-23). Xvfb runs
/usr/bin/xkbcomp at start; where that is missing and cannot be installed, it is started in a
private mount namespace whose /usr/bin is links to the real one plus the unpacked xkbcomp.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time

from .. import config, paths

CLI = "./capture.sh"
WINE_USER = "steamuser"     # the Windows user of a Proton prefix
NGX_KEY = r"HKLM\Software\NVIDIA Corporation\Global\NGXCore"
NGX_FILES = ("nvngx.dll", "_nvngx.dll")
_USER_DIRS = {"local_appdata": ("AppData", "Local"), "appdata": ("AppData", "Roaming"),
              "documents": ("Documents",), "saved_games": ("Saved Games",)}


class HostError(RuntimeError):
    pass


# --- where things are ----------------------------------------------------------------------------
def _cfg():
    return config.load().get("host", {})


def host_dir():
    return os.environ.get("CAPTURE_HOST") or _cfg().get("dir") or os.path.join(paths.OUT, "host")


def _newest(pattern):
    found = sorted(glob.glob(os.path.join(host_dir(), pattern)))
    return os.path.dirname(found[-1]) if found else None


def tools():
    """Where the pieces are (None for a missing one): proton, runtime, sysroot, ngx; and the
    display (":99") and its screen size ("2560x1440")."""
    cfg = _cfg()
    sysroot = os.path.join(host_dir(), "sysroot")
    return {"proton": cfg.get("proton") or _newest("proton/*/proton"),
            "runtime": cfg.get("runtime") or _newest("runtime/*/_v2-entry-point"),
            "sysroot": sysroot if os.path.isdir(sysroot) else None,
            "ngx": cfg.get("ngx") or _newest("nvidia/*/nvngx.dll"),
            "display": os.environ.get("CAPTURE_DISPLAY") or cfg.get("display") or ":99",
            "screen": cfg.get("screen") or "2560x1440"}


def missing():
    """What a game cannot start without, as text lines; [] when all is there."""
    t = tools()
    out = []
    if not t["proton"]:
        out.append("Proton (out/host/proton/<build>/proton)")
    if not t["runtime"]:
        out.append("the Steam Linux Runtime (out/host/runtime/<name>/_v2-entry-point)")
    if not tool("Xvfb"):
        out.append("Xvfb (out/host/sysroot, or installed)")
    if not tool("xdotool"):
        out.append("xdotool (out/host/sysroot, or installed)")
    if not t["ngx"]:
        out.append("NVIDIA's nvngx.dll and _nvngx.dll for this driver (out/host/nvidia/<version>/)")
    return out


def _require():
    gone = missing()
    if gone:
        raise HostError("this machine is not set up to run games (run: %s host setup). Missing: %s" % (CLI, "; ".join(gone)))
    return tools()


def env_dir():
    """The conda environment that holds this machine's ordinary programs (ffmpeg): CAPTURE_ENV,
    config host.env, else ~/.conda/envs/game-capture. Its programs are run by path, without
    activating it; Python stays with uv."""
    return (os.environ.get("CAPTURE_ENV") or _cfg().get("env")
            or os.path.join(os.path.expanduser("~"), ".conda", "envs", "game-capture"))


def tool(name):
    """A host program: the unpacked one in out/host/sysroot, else the one in the conda environment
    (env_dir), else the installed one, else None."""
    for p in (os.path.join(host_dir(), "sysroot", "usr", "bin", name), os.path.join(env_dir(), "bin", name)):
        if os.path.exists(p):
            return p
    return shutil.which(name)


def x_env():
    """The environment for a program that talks to the game's display (ours run from the sysroot)."""
    env = dict(os.environ, DISPLAY=tools()["display"])
    lib = os.path.join(host_dir(), "sysroot", "usr", "lib", "x86_64-linux-gnu")
    if os.path.isdir(lib):
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def _scratch(*parts):
    """A folder of ours on this node's own disk (sockets and mount points do not belong on a
    shared file system)."""
    d = os.path.join(tempfile.gettempdir(), "capture_host_%d" % os.getuid(), *parts)
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def prefix(game):
    """The game's Proton prefix folder (STEAM_COMPAT_DATA_PATH); its C: drive is pfx/drive_c."""
    return config.game(game).get("prefix") or os.path.join(paths.OUT, "proton", game)


def drive_c(game):
    return os.path.join(prefix(game), "pfx", "drive_c")


def game_path(path, game=None):
    """A path of this machine as the game sees it: C:\\... inside the game's prefix, Z:\\... elsewhere."""
    path = os.path.abspath(path)
    if game:
        real, c = os.path.realpath(path), os.path.realpath(drive_c(game))   # out/ may be a link
        if real == c or real.startswith(c + os.sep):
            return "C:\\" + real[len(c) + 1:].replace("/", "\\")
    return "Z:" + path.replace("/", "\\")


def user_dir(game, kind):
    """kind: local_appdata, appdata, documents or saved_games, of the prefix's Windows user."""
    return os.path.join(drive_c(game), "users", WINE_USER, *_USER_DIRS[kind])


def program_data(game=None):
    return os.path.join(drive_c(game), "ProgramData") if game else os.path.join(host_dir(), "ProgramData")


# --- processes -------------------------------------------------------------------------------------
def _own_pids():
    uid = os.getuid()
    for name in os.listdir("/proc"):
        if name.isdigit():
            try:
                if os.stat("/proc/" + name).st_uid == uid:
                    yield int(name)
            except OSError:
                pass


def pids(exe_name):
    """Processes of ours whose program is this Windows exe (Wine keeps the exe's Windows path as
    the process's first argument)."""
    found = []
    for pid in _own_pids():
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                arg0 = f.read().split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            continue
        if arg0.replace("\\", "/").rsplit("/", 1)[-1].lower() == exe_name.lower() and (":" in arg0 or "\\" in arg0):
            found.append(pid)
    return found


def _prefix_pids(game):
    """Everything running in the game's prefix: the game, Wine's server and services, crash reporters."""
    want = os.path.realpath(os.path.join(prefix(game), "pfx")).encode()
    found = []
    for pid in _own_pids():
        try:
            with open("/proc/%d/environ" % pid, "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        if any(e.startswith(b"WINEPREFIX=") and os.path.realpath(e[11:]) == want for e in env):
            found.append(pid)
    return found


def stop(game, exe_names=(), wait_s=60):
    """Ends the game and everything else in its prefix (a Wine server left behind would keep the
    prefix's registry open and make the next start join it). Wine's server writes the registry out
    when asked to end, so it is asked first and only killed if it stays."""
    todo = sorted(set(_prefix_pids(game)) | {p for n in exe_names for p in pids(n)})
    for sig, patience in ((signal.SIGTERM, min(20, wait_s)), (signal.SIGKILL, wait_s)):
        for pid in todo:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        t = time.time()
        while time.time() - t < patience:
            todo = [p for p in todo if os.path.exists("/proc/%d" % p)]
            if not todo:
                return
            time.sleep(0.5)


# --- the display -------------------------------------------------------------------------------------
def display_alive():
    xdo = tool("xdotool")
    if not xdo:
        return False
    try:
        return subprocess.run([xdo, "getdisplaygeometry"], env=x_env(), capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_display():
    """Starts the headless display if it is not up; returns its name (":99")."""
    t = tools()
    if display_alive():
        return t["display"]
    xvfb = tool("Xvfb")
    if not xvfb:
        raise HostError("no Xvfb (run: %s host setup)" % CLI)
    cmd = [xvfb, t["display"], "-screen", "0", t["screen"] + "x24", "-nolisten", "tcp", "-ac"]
    if not os.path.exists("/usr/bin/xkbcomp"):
        xkbcomp = tool("xkbcomp")
        if not xkbcomp:
            raise HostError("Xvfb needs xkbcomp, which is neither installed nor in out/host/sysroot")
        xbin, orig = _scratch("xbin"), _scratch("usr_bin")
        for name in os.listdir("/usr/bin"):
            link = os.path.join(xbin, name)
            if not os.path.lexists(link):
                os.symlink(os.path.join(orig, name), link)
        if not os.path.exists(os.path.join(xbin, "xkbcomp")):
            shutil.copy2(xkbcomp, os.path.join(xbin, "xkbcomp"))
        # the real /usr/bin stays reachable under `orig`; overlay mounts are refused in a user namespace
        cmd = ["unshare", "-Urm", "sh", "-c", 'mount --rbind /usr/bin "$1" && mount --rbind "$2" /usr/bin && shift 2 && exec "$@"',
               "sh", orig, xbin] + cmd
    with open(os.path.join(_scratch(), "xvfb.log"), "ab") as log:
        subprocess.Popen(cmd, env=x_env(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(40):
        time.sleep(0.5)
        if display_alive():
            return t["display"]
    raise HostError("the headless display %s did not come up (see %s)" % (t["display"], os.path.join(_scratch(), "xvfb.log")))


# --- starting a game ---------------------------------------------------------------------------------
def _env(game, app_id=None, dll_overrides=None):
    t = tools()
    env = {k: v for k, v in os.environ.items()
           if k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONUNBUFFERED")}
    env.update(DISPLAY=t["display"], XDG_RUNTIME_DIR=_scratch("xdg"),
               STEAM_COMPAT_CLIENT_INSTALL_PATH=_scratch("steam"), STEAM_COMPAT_DATA_PATH=prefix(game))
    if app_id:
        env.update(SteamAppId=str(app_id), SteamGameId=str(app_id), STEAM_COMPAT_APP_ID=str(app_id))
    if dll_overrides:
        env["WINEDLLOVERRIDES"] = dll_overrides + (";" + env["WINEDLLOVERRIDES"] if env.get("WINEDLLOVERRIDES") else "")
    if os.environ.get("CAPTURE_PROTON_LOG"):      # Proton's own log (large): out/host/logs/steam-<app>.log
        env.update(PROTON_LOG="1", PROTON_LOG_DIR=_logs())
    return env


def _logs():
    d = os.path.join(host_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _proton(t, *args):
    return [os.path.join(t["runtime"], "_v2-entry-point"), "--verb=waitforexitandrun", "--",
            os.path.join(t["proton"], "proton"), "waitforexitandrun"] + list(args)


def run(game, *args, app_id=None, timeout=900):
    """Runs a Windows program in the game's prefix and waits for it (reg, cmd, a setup program)."""
    t = _require()
    ensure_display()
    os.makedirs(prefix(game), exist_ok=True)
    return subprocess.run(_proton(t, *args), env=_env(game, app_id), cwd=_scratch(), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=timeout)


def ensure_prefix(game, app_id=None):
    """Makes the game's prefix if it is not there and gives it what DLSS needs: NVIDIA's NGX
    DLLs in system32 and the registry value that says so (Proton does both itself where the
    driver's Wine files are installed beside the driver; in a container image they are not)."""
    t = _require()
    marker = os.path.join(prefix(game), "capture_host.json")
    want = {"ngx": os.path.basename(t["ngx"])}
    system32 = os.path.join(drive_c(game), "windows", "system32")
    have = None
    if os.path.exists(marker):
        with open(marker, encoding="utf-8") as f:
            have = json.load(f)
    if have == want and all(os.path.exists(os.path.join(system32, n)) for n in NGX_FILES):
        return
    r = run(game, "reg", "add", NGX_KEY, "/v", "FullPath", "/t", "REG_SZ", "/d", "C:\\Windows\\System32", "/f", app_id=app_id)
    if r.returncode != 0 or not os.path.isdir(system32):
        raise HostError("Proton could not make the prefix %s:\n%s" % (prefix(game), (r.stdout + r.stderr)[-1500:]))
    for n in NGX_FILES:
        shutil.copyfile(os.path.join(t["ngx"], n), os.path.join(system32, n))
    with open(marker, "w", encoding="utf-8") as f:
        json.dump(want, f)


def start(game, exe, args=(), cwd=None, dll_overrides=None, app_id=None):
    """Starts the game's exe through Proton on the headless display; returns the process of the
    container (the game itself is found with pids()). dll_overrides: Wine's WINEDLLOVERRIDES for
    the DLLs a script layer replaces ("winmm,version=n,b"); app_id: the game's Steam id."""
    t = _require()
    ensure_display()
    ensure_prefix(game, app_id)
    with open(os.path.join(_logs(), "%s.log" % game), "ab") as log:
        log.write(("\n=== %s %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), exe, " ".join(args))).encode())
        log.flush()
        return subprocess.Popen(_proton(t, exe, *args), cwd=cwd, env=_env(game, app_id, dll_overrides),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
