"""What a Witcher 3 install needs (the "Remastered" build 5.01c, Steam), for `capture install witcher3`.

Game-agnostic components do ReShade and the capture add-on; this file says how the game wants
them (Direct3D 12, ReShade as dxgi.dll beside the exe) and adds what only this game needs:

- Our session script (ws/capture_mod.ws) as a loose script mod. The game compiles the .ws files
  under <game>\\mods\\<mod>\\content\\scripts\\local with its own scripts at every start, so there
  is no script extender, no ASI loader and nothing tied to one build beyond the game's own script
  interface. A changed script takes effect at the next start of the game.
- The debug console (DBGConsoleOn in bin\\config\\base\\general.ini): our commands go in through
  it, since scripts cannot read files (adapters/witcher3/session.py).
- Game settings for captures (settings.py), written into the game's user settings file while the
  game is closed: a 2560x1440 window, path tracing, DLAA with Ray Reconstruction, no frame
  generation, no lens effects, no tutorial hints or welcome panels. A machine where the game has
  never run has no settings file yet; the values are written all the same and the game fills in
  the rest at its first start.
- OptiScaler's DLSS 5 fork as winmm.dll beside the exe (the exe imports WINMM.dll; dxgi.dll is
  ReShade's), on the output of the game's own DLSS, with skin structure 2 as in the other games.

The game is started from its exe with -debugscripts (launch.py): that switch makes it write the
scripts log our script answers through. It needs no launcher and no Steam client.
"""
import os
import re

from capture import config, host
from capture.install.components import addon, optiscaler, reshade, wine
from capture.install.plan import IniSet, MakeDir, WriteText

from . import paths, settings as game_settings

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = paths.GAME
TITLE = "The Witcher 3 (Steam)"
EXE = paths.EXE_NAME          # the process name
EXE_PATH = paths.EXE          # where it is in the game folder
STEAM_APP = paths.STEAM_APP
FOLDER = paths.FOLDER
LOCK = os.path.join(HERE, "mods.lock.json")
# DLSS 5 (OptiScaler over the game's DLAA with Ray Reconstruction) by default, as for RDR2 and GTA V
# Enhanced: measured at Electors' Square 2026-11-23 (README: off/on at one instant, and a near
# sweep with it flickering about as much as without); --no-optiscaler leaves it out (Linux
# nodes whose driver cannot run it), and it needs your nvngx_dlssnr.dll (--dlss-nr).
OPTIONS = {"api": "d3d12", "resolution": "2560x1440", "path_tracing": True, "optiscaler": True}
WS_SRC = os.path.join(HERE, "ws")
# DLSS 5's skin structure 2, as for the other games (Nathan's pick, 2026-11-21/22)
OPTISCALER_SETTINGS = [("DlssNr", "SkinStructure", "2", "skin structure 2: more skin detail (as in the other games)")]


def find_game_dir():
    """The game folder: this machine's config, the environment variable, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("WITCHER3_DIR")
    if known and os.path.exists(os.path.join(known, EXE_PATH)):
        return known
    if host.LINUX:   # no Steam client: the game's Windows depot, downloaded to the default place
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
    """Folders of an existing install, searched (not recursively) as a source of the pinned files."""
    return [paths.bin_dir(game_dir), os.path.join(system.program_data(), "ReShade")]


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    b = paths.bin_dir(g)
    exe = os.path.join(g, EXE_PATH)
    api = opt.get("api") or "d3d12"
    if api != "d3d12":
        raise ValueError("The Witcher 3 (this build) runs on Direct3D 12 only, not %s" % api)
    if opt.get("ray_tracing"):
        raise ValueError("--ray-tracing is not set up for The Witcher 3 (its own ray and path tracing are settings)")
    exchange = opt.get("exchange_dir") or paths.exchange()            # tests point these elsewhere
    user_settings = opt.get("user_settings") or paths.user_settings()
    out = []

    # our session script, compiled by the game at its next start (so it can be written any time)
    scripts = paths.scripts_dir(g)
    for n in sorted(os.listdir(WS_SRC)):
        if n.endswith(".ws"):
            out.append(WriteText(os.path.join(scripts, n), open(os.path.join(WS_SRC, n), encoding="utf-8").read(),
                                 tag="scripts", what="adapters/witcher3/ws/%s" % n))
    out.append(IniSet(os.path.join(g, "bin", "config", "base", "general.ini"), "General", "DBGConsoleOn", "true",
                      tag="scripts", why="the debug console: our commands go in through it"))
    out.append(MakeDir(exchange, tag="scripts"))

    # game-agnostic components, as this game wants them: ReShade as dxgi.dll beside the exe, no effects
    out += reshade.steps(ctx, exe, api)
    out += addon.steps(ctx, b, exchange)

    # OptiScaler (DLSS 5) over the game's own DLSS (DLAA with Ray Reconstruction, settings.py), as
    # winmm.dll: the exe imports WINMM.dll, and dxgi.dll is ReShade's
    if opt.get("optiscaler"):
        out += optiscaler.steps(ctx, b, api, loader="winmm", settings=OPTISCALER_SETTINGS)
    else:
        out += optiscaler.not_loaded(ctx, b, loader="winmm")
    # under Proton: Wine loads the game folder's dxgi.dll (ReShade) and winmm.dll (OptiScaler) for
    # this exe however the game is started (launch.py passes the same overrides); nothing on Windows
    out += wine.dll_overrides(ctx, EXE, ["dxgi"] + (["winmm"] if opt.get("optiscaler") else []))

    # game settings, in the game's own user settings file
    size = tuple(int(v) for v in (opt.get("resolution") or "2560x1440").lower().split("x"))
    if abs(size[0] / size[1] - 16 / 9) > 0.01:
        raise ValueError("the render size must be 16:9, not %dx%d" % size)
    for section, key, value, why in game_settings.profile(size, bool(opt.get("path_tracing"))):
        out.append(IniSet(user_settings, section, key, value, tag="settings", why=why))
    return out


def after_install(ctx):
    """What to tell the user once the files are in place."""
    return ["Start it with: %s verify witcher3 --launch (adapters/witcher3/launch.py starts the exe with -debugscripts)." % host.CLI,
            "The first start compiles our script with the game's own; keys in game: ` debug console, Home ReShade."]
