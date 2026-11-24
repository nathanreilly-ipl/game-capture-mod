"""What a Kingdom Come: Deliverance install needs (1.9.7, Steam), for `capture install kcd`.

NOT tested in the game yet (2026-11-23): written from the game's own files (its Scripts.pak and
WHGame.dll) and community documentation; README and BACKLOG say what is measured.

- Our session script (lua/capture_mod.lua) as a mod: Mods\\capture_mod\\mod.manifest and
  Mods\\capture_mod\\Data\\capture_mod.pak, a zip holding Scripts\\Startup\\capture_mod.lua, which the
  game runs at start (patch 1.9.3 added startup scripts for mods). The pak is built here, with
  fixed file times so the same script always gives the same file.
- ReShade for Direct3D 11 as dxgi.dll beside the exe, no effects, and our capture add-on.
- Console variables in user.cfg in the game folder (read at every start): no motion blur, depth of
  field, vignette, film grain or chromatic aberration, no intro films, no frame rate cap.

The game is started with -devmode (launch.py), which gives it the console our commands go in through.
"""
import io
import os
import re
import zipfile

from capture import config, host
from capture import paths as capture_paths
from capture.install.components import addon, reshade, wine
from capture.install.plan import CopyFile, IniSet, MakeDir, WriteText

from . import paths

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = paths.GAME
TITLE = "Kingdom Come: Deliverance (Steam)"
EXE = paths.EXE_NAME
EXE_PATH = paths.EXE
STEAM_APP = paths.STEAM_APP
FOLDER = paths.FOLDER
LOCK = os.path.join(HERE, "mods.lock.json")
OPTIONS = {"api": "d3d11", "resolution": "2560x1440"}
LUA_SRC = os.path.join(HERE, "lua", "capture_mod.lua")

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<kcd_mod>
  <info>
    <name>capture_mod</name>
    <modid>capture_mod</modid>
    <description>Multi-view capture session script (capture_mod repository)</description>
    <author>capture_mod</author>
    <version>1</version>
    <created_on>2026-11-23</created_on>
  </info>
</kcd_mod>
"""
# No <supports> block: with one naming 1.9.7 the game (which calls itself 1.9.8, its exe 1.9.7.0)
# disabled the mod ("doesn't support game version '1.9.8'", kcd.log, 2026-11-23).

# console variables (CryEngine's and Warhorse's names; values written as `name=value` lines)
CVARS = [
    ("r_MotionBlur", "0", "a lens effect, not part of the scene"),
    ("r_DepthOfField", "0", "differs from view to view"),
    ("r_HDRVignetting", "0", "a lens effect"),
    ("r_HDRGrainAmount", "0", "film grain: noise that differs from frame to frame"),
    ("r_ChromaticAberration", "0", "a lens effect"),
    ("r_VSync", "0", "frame rate sets the shot time"),
    ("sys_MaxFPS", "0", "no frame rate cap"),
    ("wh_sys_HideIntroVideo", "1", "no intro films at start"),
    ("sys_PakPriority", "0", "loose files in Data are read: our script's long inputs (Data\\capture_mod_in)"),
    ("r_Width", "2560", "the capture size"),
    ("r_Height", "1440", "the capture size"),
    ("r_Fullscreen", "0", "a window: frames are read from it and keys sent to it"),
    ("r_FullscreenWindow", "0", "a plain window, not borderless full screen"),
]


def build_pak():
    """Mods\\capture_mod\\Data\\capture_mod.pak's content, built into out/build (the same bytes for
    the same script)."""
    out = os.path.join(capture_paths.OUT, "build", GAME, "capture_mod.pak")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("Scripts/Startup/capture_mod.lua", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, open(LUA_SRC, "rb").read())
    data = buf.getvalue()
    if not os.path.exists(out) or open(out, "rb").read() != data:
        with open(out, "wb") as f:
            f.write(data)
    return out


def find_game_dir():
    """The game folder: this machine's config, the environment variable, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("KCD_DIR")
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
    return [paths.bin_dir(game_dir), os.path.join(system.program_data(), "ReShade")]


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    b = paths.bin_dir(g)
    exe = os.path.join(g, EXE_PATH)
    api = opt.get("api") or "d3d11"
    if api != "d3d11":
        raise ValueError("Kingdom Come: Deliverance runs on Direct3D 11, not %s" % api)
    exchange = opt.get("exchange_dir") or paths.exchange()
    out = []

    # our session script as a mod, run by the game at start
    m = paths.mod_dir(g)
    out.append(WriteText(os.path.join(m, "mod.manifest"), MANIFEST, tag="scripts", what="the mod's manifest"))
    out.append(CopyFile(build_pak, os.path.join(m, "Data", "capture_mod.pak"), tag="scripts", closed=True,
                        what="capture_mod.pak (adapters/kcd/lua/capture_mod.lua)"))
    out.append(MakeDir(exchange, tag="scripts"))
    out.append(MakeDir(paths.inbox(g), tag="scripts"))     # our script's long inputs (sys_PakPriority 0)

    # ReShade (dxgi.dll beside the exe, no effects) and our add-on
    out += reshade.steps(ctx, exe, api)
    out += addon.steps(ctx, b, exchange)
    out += wine.dll_overrides(ctx, EXE, ["dxgi"])     # under Proton: the game folder's dxgi.dll (ReShade)

    # console variables, read at every start
    cfg = opt.get("user_cfg") or paths.user_cfg(g)
    for key, value, why in CVARS:
        out.append(IniSet(cfg, "", key, value, tag="settings", why=why))
    return out


def after_install(ctx):
    return ["Start it with: %s verify kcd --launch (adapters/kcd/launch.py starts the exe with -devmode)." % host.CLI]
