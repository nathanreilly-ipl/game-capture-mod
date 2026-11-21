"""What a GTA V Legacy (story mode, Steam) install needs, for `capture install gtav`.

Game-agnostic components do ReShade and the capture add-on; this file says how GTA V wants them
(Direct3D 11, ReShade as an .asi plug-in) and adds what only GTA V needs:

- Script Hook V with its ASI loader (dinput8.dll): loads script plug-ins and exposes the game's
  natives. Supplied by the person installing (no redistribution). ScriptHookV.dev turns on its
  CTRL+R script reload (after a script error, Script Hook V stops that script).
- RedLua for GTA V: runs our Lua scripts in the game, Autorun on, so the loader starts by itself.
- Native Trainer (optional, on by default): handy while scouting. Its menu is F4.
- Our scripts: the shared loader (adapters/common/lua/capture_loader.lua), written with GTA V's
  own exchange folder, so it never answers for another game.
- BattlEye off (-nobattleye in commandline.txt): mods run in story mode only, and with BattlEye
  off the game cannot go online.
- Game settings: Direct3D 11, VSync off, no pause on focus loss, and the windowed capture size.

No visual set yet: captures are taken without ReShade effects (an empty preset). OptiScaler is
not offered: GTA V Legacy has no upscaler call for it to take over.
"""
import os
import re

from capture import config
from capture.install.components import addon, reshade
from capture.install.plan import CopyFile, JsonSet, MakeDir, WriteText, XmlSet

from ..common import redlua

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = "gtav"
TITLE = "Grand Theft Auto V Legacy (story mode, Steam)"
EXE = "GTA5.exe"
STEAM_APP = "271590"
FOLDER = "Grand Theft Auto V"           # under steamapps\common (Enhanced is "Grand Theft Auto V Enhanced")
LOCK = os.path.join(HERE, "mods.lock.json")
EXCHANGE = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "RDR2Modding", "captures_gtav")
OPTIONS = {"native_trainer": True, "preset": False, "api": "d3d11", "resolution": "2560x1440"}
REDLUA_SETTINGS = {"auto_updates": False, "autorun": True, "menu_hotkey": 118, "menu_language": "ingame",
                   "menu_position": 0}
DX_VERSION = {"d3d10": "0", "d3d10_1": "1", "d3d11": "2"}   # settings.xml <DX_Version>


def settings_xml():
    return os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "Rockstar Games", "GTA V", "settings.xml")


def find_game_dir():
    """The game folder: this machine's config, GTAV_DIR, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("GTAV_DIR")
    if known and os.path.exists(os.path.join(known, EXE)):
        return known
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
        if os.path.exists(os.path.join(d, EXE)):
            return d
    return None


def installed_dirs(game_dir, system):
    """Folders of an existing install, searched (not recursively) as a source of the pinned files."""
    return [game_dir, os.path.join(game_dir, "RedLua"), os.path.join(game_dir, "RedLua", "Langs"),
            os.path.join(system.program_data(), "ReShade")]


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    exe = os.path.join(g, EXE)
    api = opt.get("api") or "d3d11"
    if api not in DX_VERSION:
        raise ValueError("GTA V Legacy runs on Direct3D 10, 10.1 or 11, not %s" % api)
    if opt.get("optiscaler"):
        raise ValueError("--optiscaler: GTA V Legacy has no upscaler (DLSS, FSR, XeSS) for OptiScaler to take over")
    if opt.get("ray_tracing"):
        raise ValueError("--ray-tracing is RDR2's Reality Redemption 2; there is none for GTA V")
    if opt.get("preset"):
        raise ValueError("GTA V has no visual set yet (adapters/gtav/visual/); leave out --preset")
    exchange = opt.get("exchange_dir") or EXCHANGE      # tests point these two elsewhere
    xml = opt.get("settings_xml") or settings_xml()
    out = []

    # Script Hook V, RedLua, Native Trainer
    for name in ("ScriptHookV.dll", "dinput8.dll"):
        out.append(CopyFile(ctx.file("scripthook_v", name), os.path.join(g, name)))
    if opt.get("native_trainer", True):
        out.append(CopyFile(ctx.file("scripthook_v", "NativeTrainer.asi"), os.path.join(g, "NativeTrainer.asi")))
    out.append(WriteText(os.path.join(g, "ScriptHookV.dev"), "", what="turns on Script Hook V's CTRL+R script reload",
                         only_if_missing=True))
    for name in ("RedLua.asi", "lua51.dll", "RedLua/natives.json", "RedLua/Langs/en.lng", "RedLua/Langs/ru.lng"):
        out.append(CopyFile(ctx.file("redlua_v", name), os.path.join(g, *name.split("/"))))
    out.append(JsonSet(os.path.join(g, "RedLua", "Settings.json"), "autorun", True, default=REDLUA_SETTINGS, tag="mods",
                       why="our loader starts with the game"))
    out.append(WriteText(os.path.join(g, "commandline.txt"), "-nobattleye\n", tag="mods", closed=True,
                         what="-nobattleye: story mode with mods, never online"))

    # our scripts (can be written while the game runs)
    out.append(WriteText(os.path.join(g, "RedLua", "Scripts", "capture_loader.lua"), redlua.loader_text(exchange),
                         tag="scripts", what="adapters/common/lua/capture_loader.lua, watching %s" % exchange))
    out.append(MakeDir(exchange, tag="scripts"))

    # game-agnostic components, as GTA V wants them: ReShade through Script Hook V's loader, no effects
    out += reshade.steps(ctx, exe, api, asi_loader=True)
    out += addon.steps(ctx, g, exchange)

    # game settings
    out.append(XmlSet(xml, "DX_Version", DX_VERSION[api], why="the graphics API ReShade is installed for"))
    out.append(XmlSet(xml, "VSync", "0", why="uncapped frame rate"))
    out.append(XmlSet(xml, "PauseOnFocusLoss", "0", why="the game keeps running if focus is lost"))
    if opt.get("resolution"):
        w, h = (int(v) for v in opt["resolution"].lower().split("x"))
        if abs(w / h - 16 / 9) > 0.01:
            raise ValueError("the capture window must be 16:9, not %dx%d" % (w, h))
        out += [XmlSet(xml, "Windowed", "1", why="windowed"), XmlSet(xml, "ScreenWidth", str(w)),
                XmlSet(xml, "ScreenHeight", str(h))]
    return out


def after_install(ctx):
    """What to tell the user once the files are in place."""
    return ["Start GTA V Legacy through Steam and load story mode (never GTA Online with mods).",
            "Keys in game: F7 RedLua menu, F4 Native Trainer."]
