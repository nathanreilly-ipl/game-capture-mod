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
import re
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


def driver_version():
    """The NVIDIA driver's version ("580.105.08"), or None."""
    try:
        with open("/proc/driver/nvidia/version") as f:
            # "... Kernel Module for x86_64  580.178.04  Release Build ...": the first x.y[.z] standing alone
            m = re.search(r"Kernel Module.*?\s(\d+\.\d+(?:\.\d+)?)\s", f.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        return out[0] if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ngx_dir():
    """NVIDIA's NGX DLLs for this machine's driver (nodes of one cluster can run different ones);
    failing that the newest set there is."""
    v = driver_version()
    d = os.path.join(host_dir(), "nvidia", v or "?")
    return d if os.path.exists(os.path.join(d, "nvngx.dll")) else _newest("nvidia/*/nvngx.dll")


def tools():
    """Where the pieces are (None for a missing one): proton, runtime, sysroot, ngx; and the
    display (":99") and its screen size ("2560x1440")."""
    cfg = _cfg()
    sysroot = os.path.join(host_dir(), "sysroot")
    return {"proton": cfg.get("proton") or _newest("proton/*/proton"),
            "runtime": cfg.get("runtime") or _newest("runtime/*/_v2-entry-point"),
            "sysroot": sysroot if os.path.isdir(sysroot) else None,
            "ngx": cfg.get("ngx") or _ngx_dir(),
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


def gpu_name():
    """The name of the first GPU this process can see, as the driver gives it, or None."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    names = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    return names[0] if r.returncode == 0 and names else None


def gpus():
    """How many GPUs this process can see (0 when nvidia-smi does not say)."""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    return sum(1 for line in r.stdout.splitlines() if line.startswith("GPU ")) if r.returncode == 0 else 0


def _one_gpu():
    n = gpus()
    if n > 1 and os.environ.get("CAPTURE_ANY_GPUS") != "1":
        # Cyberpunk 2077 on a job with four GPUs, 2026-11-23: the game's list of display modes was
        # empty ("Resolution is nil") and its window sat at 320,180; with one GPU visible all is well
        raise HostError("this process sees %d GPUs, and a game under Proton then finds no display modes. Start it where "
                        "one GPU is visible: under Slurm, in a job step (srun --exact --gres=gpu:1 -c <cores> %s ...). "
                        "CAPTURE_ANY_GPUS=1 starts it anyway." % (n, CLI))


def check_start(game):
    """Raises HostError if a game cannot be started from this process (more than one GPU visible),
    before anything is closed: a worker that ended a running game to restart it, and then could not
    start it, lost the game (Cyberpunk 2077, 2026-11-23)."""
    _require()
    _one_gpu()


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


_PREFIX_OF = {}


def use_prefix(game, name):
    """Says that `game` runs in the prefix `name` instead of one of its own: games that share a
    launcher and its sign-in (Rockstar's) share one prefix. Called by the game's package when it
    is imported. Stopping one such game ends everything in the shared prefix."""
    _PREFIX_OF[game] = name


def prefix(game):
    """The game's Proton prefix folder (STEAM_COMPAT_DATA_PATH); its C: drive is pfx/drive_c."""
    return config.game(game).get("prefix") or os.path.join(paths.OUT, "proton", _PREFIX_OF.get(game, game))


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


def host_path(path, game=None):
    """The other way round: a path as code inside the game gave it (C:\\... in the game's prefix,
    Z:\\... elsewhere) on this machine."""
    p = path.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        drive, rest = p[0].upper(), p[2:].lstrip("/")
        if drive == "Z":
            return "/" + rest
        if drive == "C" and game:
            return os.path.join(drive_c(game), *rest.split("/"))
    return path


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
    when asked to end, so it is asked first and only killed if it stays. A Steam client in the
    prefix ends with it: after a game it had started was closed (by signal or by taskkill) its main
    loop stalled and it took no further requests or ended itself minutes later (RDR2 and GTA V,
    2026-11-23). `capture host steam <game> --keep` starts it again; steam_launch waits for that."""
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
    if not os.path.isdir("/proc/asound") or not glob.glob("/proc/asound/card*"):
        # no sound hardware: a default device that plays nothing (alsa_null.conf says why)
        env["ALSA_CONFIG_PATH"] = "/usr/share/alsa/alsa.conf:" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "alsa_null.conf")
    if app_id:
        env.update(SteamAppId=str(app_id), SteamGameId=str(app_id), STEAM_COMPAT_APP_ID=str(app_id))
    if dll_overrides:
        env["WINEDLLOVERRIDES"] = dll_overrides + (";" + env["WINEDLLOVERRIDES"] if env.get("WINEDLLOVERRIDES") else "")
    if os.environ.get("CAPTURE_PROTON_LOG"):      # Proton's own log (large): out/host/logs/steam-<app>.log
        env.update(PROTON_LOG="1", PROTON_LOG_DIR=_logs())
    return env


# --- Wine without Proton's script: a real Steam client in the prefix, 32-bit programs ------------------
# Proton's script wraps every program in its own stand-in for the Steam client (lsteamclient, a
# built-in steam.exe), which needs the Linux Steam client. Games that must be started by a real Steam
# client (Rockstar's launcher refuses without one) get the Windows client in their prefix, and that
# client and what it starts run through wine_direct(): Wine's preloader, the environment Proton would
# give (below), Proton's stand-in switched off.
#
# What Proton's script sets for a game, read from a game it started (GE-Proton11-12, 2026-11-23):
# DXVK, vkd3d-proton and NVAPI in place of Wine's own Direct3D, the fast synchronisation primitives.
PROTON_OVERRIDES = ("dotnetfx35.exe=b;dotnetfx35setup.exe=b;beclient.dll=b,n;beclient_x64.dll=b,n;winebth.sys=d;opencl=n,d;"
                    "d3d11=n;d3d10core=n;d3d9=n;dxgi=n;d3d12=n;d3d12core=n;nvapi64=n;nvofapi64=n;nvapi=n;nvcuda=b")
PROTON_ENV = {"WINEDEBUG": "-all", "DXVK_LOG_LEVEL": "none", "VKD3D_DEBUG": "none", "VKD3D_SHADER_DEBUG": "none",
              "WINENTSYNC": "1", "WINEESYNC": "1", "WINEFSYNC": "1", "WINE_LARGE_ADDRESS_AWARE": "1",
              "DXVK_ENABLE_NVAPI": "1", "DXVK_NVAPI_SET_NGX_DEBUG_OPTIONS": "DLSSIndicator=0,DLSSGIndicator=0,",
              "__GLVND_DISALLOW_PATCHING": "1"}
WOW64_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wow64")
STEAM_PARTS = ("Program Files (x86)", "Steam")


def tls32():
    """The preload library that lets Wine start 32-bit Windows programs where the 32-bit system call
    entry is forbidden (wow64/tls32.c; built by `capture host setup` into out/host/lib), or None."""
    p = os.path.join(host_dir(), "lib", "tls32.so")
    return p if os.path.exists(p) else None


def _wine_env(game, dll_overrides=None, cwd=None):
    t = tools()
    files = os.path.join(t["proton"], "files")
    env = _env(game)
    for k in ("SteamAppId", "SteamGameId", "STEAM_COMPAT_APP_ID", "UMU_ID"):
        env.pop(k, None)
    env.update(PROTON_ENV)
    if os.environ.get("CAPTURE_WINEDEBUG"):
        env["WINEDEBUG"] = os.environ["CAPTURE_WINEDEBUG"]
    env.update(WINEPREFIX=os.path.join(prefix(game), "pfx"),
               WINEDLLPATH=":".join(os.path.join(files, "lib", d) for d in ("wine/nvidia-libs/nvml/wine", "vkd3d", "wine")),
               WINEDLLOVERRIDES=(dll_overrides + ";" if dll_overrides else "") + PROTON_OVERRIDES,
               PROTON_DISABLE_LSTEAMCLIENT="1",     # Wine's loader: no stand-in when steamclient64.dll is loaded
               WINEARCH="wow64")                    # 32-bit Windows programs in 64-bit processes
    if tls32():
        env["CAPTURE_PRELOAD"] = tls32()
    if cwd:
        env["CAPTURE_CWD"] = cwd
    return env


def _wine_cmd(t, *args):
    return [os.path.join(t["runtime"], "_v2-entry-point"), "--verb=run", "--", os.path.join(WOW64_DIR, "wine.sh"),
            os.path.join(t["proton"], "files")] + list(args)


def wine_direct(game, *args, dll_overrides=None, cwd=None, wait=True, timeout=600):
    """Runs a Windows program in the game's prefix through Wine itself (see above). wait: returns the
    finished process (its output captured); otherwise starts it detached, its output in the game's log."""
    t = _require()
    ensure_display()
    ensure_prefix(game)
    env = _wine_env(game, dll_overrides, cwd)
    if not wait:
        _one_gpu()      # what it starts may be a game, or a Steam client that starts one
    if wait:
        return subprocess.run(_wine_cmd(t, *args), env=env, cwd=_scratch(), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    with open(os.path.join(_logs(), "%s.log" % game), "ab") as log:
        log.write(("\n=== %s (wine) %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(args))).encode())
        log.flush()
        return subprocess.Popen(_wine_cmd(t, *args), env=env, cwd=_scratch(), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)


def app_overrides(game, exe_name, overrides):
    """DLL overrides for one exe, kept in the prefix's registry (HKCU\\Software\\Wine\\AppDefaults): they
    hold however the game is started, by us or by a Steam client. overrides: {"dinput8": "native,builtin"}."""
    for dll, order in overrides.items():
        r = wine_direct(game, "reg", "add", "HKCU\\Software\\Wine\\AppDefaults\\%s\\DllOverrides" % exe_name,
                        "/v", dll, "/t", "REG_SZ", "/d", order, "/f")
        if r.returncode != 0:
            raise HostError("could not set the DLL override %s for %s:\n%s" % (dll, exe_name, (r.stdout + r.stderr)[-800:]))


def steam_exe(game):
    """The Windows Steam client in the game's prefix (a real one, not Proton's stand-in), or None."""
    p = os.path.join(drive_c(game), *STEAM_PARTS, "steam.exe")
    return p if os.path.exists(p) and os.path.getsize(p) > 1000000 else None


def steam_running(game):
    for pid in _prefix_pids(game):
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                arg0 = f.read().split(b"\0")[0].decode(errors="replace").replace("\\", "/").lower()
        except OSError:
            continue
        if arg0.endswith("/steam/steam.exe"):
            return True
    return False


def start_steam(game, wait_s=600):
    """Starts the prefix's Steam client if it is not running; returns once its window is up (signed in
    with the remembered login, or waiting at its sign-in window: the owner signs in there once)."""
    if not steam_exe(game):
        raise HostError("no Steam client in %s (the Windows client's folder goes in %s)" % (
            prefix(game), os.path.join(drive_c(game), *STEAM_PARTS)))
    if not tls32():
        raise HostError("out/host/lib/tls32.so is not built (run: %s host setup): Steam's service is a 32-bit program" % CLI)
    if steam_running(game):
        return
    t = time.time()
    while _prefix_pids(game) and time.time() - t < 60:
        time.sleep(2)       # what a stop is still ending: a client started into a dying Wine server ends at once
    p = wine_direct(game, "C:\\Program Files (x86)\\Steam\\steam.exe", "-no-cef-sandbox", "-silent",
                    cwd=os.path.join(drive_c(game), *STEAM_PARTS), wait=False)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(5)
        if steam_running(game) and os.path.exists(os.path.join(drive_c(game), *STEAM_PARTS, "logs", "connection_log.txt")):
            return
        if p.poll() is not None and not steam_running(game):
            raise HostError("the Steam client ended at once (see %s)" % os.path.join(_logs(), "%s.log" % game))
    raise HostError("the Steam client did not come up in %d s (see %s)" % (wait_s, os.path.join(_logs(), "%s.log" % game)))


def steam_logged_on(game):
    """True once the prefix's running Steam client has logged on (its connection log says so after
    the client's start)."""
    log = os.path.join(drive_c(game), *STEAM_PARTS, "logs", "connection_log.txt")
    started = None
    for pid in _prefix_pids(game):
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                arg0 = f.read().split(b"\0")[0].decode(errors="replace").replace("\\", "/").lower()
            if arg0.endswith("/steam/steam.exe"):
                started = os.stat("/proc/%d" % pid).st_mtime
        except OSError:
            pass
    if started is None or not os.path.exists(log) or os.path.getmtime(log) < started:
        return False
    with open(log, encoding="utf-8", errors="replace") as f:
        tail = f.read()[-4000:]
    i = tail.rfind("[Logged On")
    return i >= 0 and "Logged Off" not in tail[i:] and "Disconnected" not in tail[i:]


def steam_launch(game, app_id, wait_s=900):
    """Asks the prefix's Steam client to start a game, as steam://rungameid does on Windows. Waits
    for a client that is being started elsewhere (the keeper's job step) and for its logon."""
    deadline = time.time() + wait_s
    while not (steam_running(game) and steam_logged_on(game)):
        if time.time() > deadline:
            raise HostError("the Steam client in %s is not up and logged on (run: %s host steam %s --keep, in a job step "
                            "with one GPU; its sign-in window is on display %s)" % (prefix(game), CLI, game, tools()["display"]))
        if not steam_running(game) and gpus() <= 1:
            start_steam(game)
        time.sleep(5)
    time.sleep(10)      # logged on is a little before it takes requests
    # the client that is running takes the request; this second steam.exe only passes it on and ends
    return wine_direct(game, "C:\\Program Files (x86)\\Steam\\steam.exe", "-applaunch", str(app_id), timeout=300)


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
    if have and os.path.isdir(system32):
        # the prefix is there with its registry value; only the driver changed (another node of a
        # cluster): the files of this driver's version, no Proton run (it would wait for whatever
        # runs in the prefix to end)
        for n in NGX_FILES:
            shutil.copyfile(os.path.join(t["ngx"], n), os.path.join(system32, n))
        with open(marker, "w", encoding="utf-8") as f:
            json.dump(want, f)
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
    _one_gpu()
    ensure_display()
    ensure_prefix(game, app_id)
    with open(os.path.join(_logs(), "%s.log" % game), "ab") as log:
        log.write(("\n=== %s %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), exe, " ".join(args))).encode())
        log.flush()
        return subprocess.Popen(_proton(t, exe, *args), cwd=cwd, env=_env(game, app_id, dll_overrides),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
