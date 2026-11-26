"""What a Death Stranding Director's Cut install needs (1.004, Steam app 1850570), for
`capture install deathstranding`.

- Our plug-in capture_ds.asi (adapters/deathstranding/plugin): the script layer the game lacks,
  hooking its clocks and its render camera (adapter.py, Method). Built here from source with the
  C++ build tools, or taken prebuilt from a mods bundle built from exactly these sources.
  capture_ds.ini beside it says where its control and status files are.
- Ultimate ASI Loader as winhttp.dll, which loads it (ds.exe imports winhttp.dll at start).
- ReShade for Direct3D 12 as dxgi.dll beside the exe, no effects, and our capture add-on.
- game_settings.cfg (per Steam account, in %LOCALAPPDATA%\\KojimaProductions\\DeathStrandingDC):
  AutoLogin 0, so the game starts offline without asking (with 1 and Steam offline it shows two
  notices first), and PhotoModeKeepParams 1, so photo mode keeps Show Sam and the other switches
  between sessions and leaves without a confirmation (photo.py).

The game's graphics options are in profile.dat (binary) and are not written here: the capture
setup is the game's own maximum, set once in its menu (README, Death Stranding).
"""
import os
import re
import subprocess

from capture import config, host
from capture.install.components import addon, reshade, wine
from capture.install.components.addon import digest_of, find_cmake, no_build_note, prebuilt
from capture.install.plan import Call, CopyFile, IniSet, InstallError, KvSet, MakeDir

from . import paths

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = paths.GAME
TITLE = "Death Stranding Director's Cut (Steam)"
EXE = paths.EXE_NAME
EXE_PATH = paths.EXE
STEAM_APP = paths.STEAM_APP
FOLDER = paths.FOLDER
LOCK = os.path.join(HERE, "mods.lock.json")
OPTIONS = {"api": "d3d12"}

PLUGIN_SRC = os.path.join(HERE, "plugin")
PLUGIN_BUILD = os.path.join(PLUGIN_SRC, "build")
PLUGIN_NAME = "capture_ds.asi"
PLUGIN_STAMP = "capture_ds.src.sha256"
PLUGIN_BUILT = os.path.join(PLUGIN_BUILD, "Release", PLUGIN_NAME)
PLUGIN_BUILT_STAMP = os.path.join(PLUGIN_BUILD, PLUGIN_STAMP)
EXTRA_NAMES = (PLUGIN_NAME, PLUGIN_STAMP)      # found by name in a mods bundle (capture mods bundle)

SETTINGS = [
    ("AutoLogin", "0", "start offline without asking: no sign-in, so no notices and no other players' structures"),
    ("PhotoModeKeepParams", "1", "photo mode keeps Show Sam off and its other switches; leaving it asks nothing"),
]


def plugin_digest():
    # CMakeLists.txt is part of the tag with its line ends taken as LF, like the sources (digest_of)
    cmake = open(os.path.join(PLUGIN_SRC, "CMakeLists.txt"), "rb").read().replace(b"\r\n", b"\n")
    return digest_of(os.path.join(PLUGIN_SRC, "src"), cmake)


def bundle_extra(log=print):
    """Our built plug-in and its stamp, for `capture mods bundle`: a machine without the C++ build
    tools (any Linux machine) installs capture_ds.asi from the bundle."""
    if not plugin_built():
        log("capture_ds.asi is not built here from the current sources, so the bundle will not include it")
        return []
    return [("capture_ds/" + PLUGIN_NAME, PLUGIN_BUILT), ("capture_ds/" + PLUGIN_STAMP, PLUGIN_BUILT_STAMP)]


def plugin_built():
    return (os.path.exists(PLUGIN_BUILT) and os.path.exists(PLUGIN_BUILT_STAMP)
            and open(PLUGIN_BUILT_STAMP).read().strip() == plugin_digest())


def build_plugin(log=print):
    cmake = find_cmake()
    if not cmake:
        raise InstallError("no C++ build tools: install Visual Studio Build Tools with 'Desktop development with C++'")
    for args in (["-S", PLUGIN_SRC, "-B", PLUGIN_BUILD, "-A", "x64"], ["--build", PLUGIN_BUILD, "--config", "Release"]):
        r = subprocess.run([cmake] + args, capture_output=True, text=True)
        if r.returncode != 0:
            raise InstallError("building capture_ds.asi failed:\n" + (r.stdout + r.stderr)[-2000:])
    with open(PLUGIN_BUILT_STAMP, "w") as f:
        f.write(plugin_digest())
    log("  built %s" % PLUGIN_BUILT)


def find_game_dir():
    """The game folder: this machine's config, the environment variable, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("DS_DIR")
    if known and os.path.exists(os.path.join(known, EXE_PATH)):
        return known
    if host.LINUX:
        return paths.DEFAULT_GAME_DIR if os.path.exists(os.path.join(paths.DEFAULT_GAME_DIR, EXE_PATH)) else None
    libs = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam") as key:
            steam = winreg.QueryValueEx(key, "InstallPath")[0]
        libs.append(steam)
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="replace").read())]
    except OSError:
        pass
    for lib in libs:
        d = os.path.join(lib, "steamapps", "common", FOLDER)
        if os.path.exists(os.path.join(d, EXE_PATH)):
            return d
    return None


def installed_dirs(game_dir, system):
    return [game_dir, os.path.join(system.program_data(), "ReShade")]


def plugin_steps(ctx, g, exchange):
    state = {}

    def usable(c=None):
        if plugin_built():
            return PLUGIN_BUILT
        if c is not None and "prebuilt" not in state:
            state["prebuilt"] = prebuilt(c, PLUGIN_NAME, PLUGIN_STAMP, plugin_digest())
        return state.get("prebuilt", (None, None))[0]

    def build_status(c):
        if plugin_built():
            return "ok", "built"
        if usable(c):
            return "ok", "prebuilt from %s" % state["prebuilt"][1]
        if find_cmake():
            return "todo", "build with CMake"
        return "missing", no_build_note("capture_ds.asi")

    ini = os.path.join(g, "capture_ds.ini")
    why = "where capture_ds.asi takes commands and writes its status"
    return [Call("capture_ds.asi built from adapters/deathstranding/plugin", build_status, lambda c: build_plugin(c.log), tag="scripts"),
            CopyFile(lambda: usable(ctx), os.path.join(g, PLUGIN_NAME), tag="scripts", what="our plug-in capture_ds.asi"),
            IniSet(ini, "capture", "Control", os.path.join(exchange, "capture.txt"), tag="scripts", why=why, game_path=True),
            IniSet(ini, "capture", "Status", os.path.join(exchange, "capture_status.txt"), tag="scripts", why=why, game_path=True),
            MakeDir(exchange, tag="scripts")]


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    exe = os.path.join(g, EXE_PATH)
    api = opt.get("api") or "d3d12"
    if api != "d3d12":
        raise ValueError("Death Stranding Director's Cut runs on Direct3D 12, not %s" % api)
    exchange = opt.get("exchange_dir") or paths.exchange()
    out = []
    # the ASI loader as winhttp.dll, and our plug-in it loads
    out.append(CopyFile(ctx.file("ultimate_asi_loader", "dinput8.dll"), os.path.join(g, "winhttp.dll"),
                        what="Ultimate ASI Loader as winhttp.dll"))
    out += plugin_steps(ctx, g, exchange)
    # ReShade (dxgi.dll beside the exe, no effects) and our add-on
    out += reshade.steps(ctx, exe, api)
    out += addon.steps(ctx, g, exchange)
    out += wine.dll_overrides(ctx, EXE, ["dxgi", "winhttp"])     # under Proton: the game folder's copies
    # the game's own settings, per Steam account (settings_files: other files, for tests)
    for cfg in opt.get("settings_files") or paths.game_settings_files():
        for key, value, why in SETTINGS:
            out.append(KvSet(cfg, key, value, why=why))
    return out


def after_install(ctx):
    notes = ["Start it with: %s verify deathstranding --launch (adapters/deathstranding/launch.py starts it through Steam)." % host.CLI]
    if not paths.game_settings_files():
        notes.append("No game_settings.cfg yet: start the game once, then run install again for its settings.")
    return notes
