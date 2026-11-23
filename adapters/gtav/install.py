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

Visual presets (--preset; off by default): the colour grade (qUINT Lightroom) with Clarity as the
capture preset, plus no effects, the grade with screen-space effects (MXAO, SSR, Clarity), a depth
check and the grade alone, switched live by F14-F18 (visual_steps). Without --preset captures have
no ReShade effects.
A graphics mod (--graphics-mod; Enhanced only, on by default there): NaturalVision Enhanced,
installed from its archive (components/pack.py), with the settings the edition gives
(install_enhanced.py). Without it, an install removes its files.
OptiScaler is not offered for Legacy: it has no upscaler call for it to take over.
"""
import os
import re

from capture import config, host
from capture import paths as capture_paths
from capture.install.components import addon, optiscaler, pack, reshade, wine
from capture.install.plan import CopyFile, IniSet, JsonSet, MakeDir, RemoveFile, WriteText, XmlSet

from ..common import redlua
from . import settings_menu

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = "gtav"
TITLE = "Grand Theft Auto V Legacy (story mode, Steam)"
EXE = "GTA5.exe"
STEAM_APP = "271590"
FOLDER = "Grand Theft Auto V"           # under steamapps\common (Enhanced is "Grand Theft Auto V Enhanced")
LOCK = os.path.join(HERE, "mods.lock.json")
EXCHANGE = os.path.join(host.user_dir(GAME, "documents"), "RDR2Modding", "captures_gtav")
OPTIONS = {"native_trainer": True, "preset": False, "api": "d3d11", "resolution": "2560x1440"}
REDLUA_SETTINGS = {"auto_updates": False, "autorun": True, "menu_hotkey": 118, "menu_language": "ingame",
                   "menu_position": 0}
DX_VERSION = {"d3d10": "0", "d3d10_1": "1", "d3d11": "2"}   # settings.xml <DX_Version>
# Enhanced's DLSS mode (settings.xml <dlssQuality>, the order of its menu; Quality renders 1706x960
# for 2560x1440, DLAA 2560x1440, as OptiScaler's log shows)
DLSS_MODES = settings_menu.DLSS_MODES
DLSS_SHARPEN = "0.800000"   # the value on the development machine


def settings_xml():
    return os.path.join(host.user_dir(GAME, "documents"), "Rockstar Games", "GTA V", "settings.xml")


def default_game_dir(game=GAME, folder=FOLDER):
    """Windows: Steam's default library. Linux (the game under Proton, capture/host): where a
    download of the game's Windows depots is kept, since there is no Steam client there."""
    if host.LINUX:
        return os.path.join(capture_paths.OUT, "games", game)
    return os.path.join(r"C:\Program Files (x86)\Steam\steamapps\common", folder)


def find_game_dir(game=GAME, exe=EXE, folder=FOLDER, env="GTAV_DIR"):
    """The game folder: this machine's config, the environment variable, then the Steam libraries."""
    known = config.game(game).get("game_dir") or os.environ.get(env)
    if known and os.path.exists(os.path.join(known, exe)):
        return known
    if host.LINUX:   # no Steam client: the game's Windows depots, downloaded to out/games/<game>
        d = default_game_dir(game, folder)
        return d if os.path.exists(os.path.join(d, exe)) else None
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
        d = os.path.join(lib, "steamapps", "common", folder)
        if os.path.exists(os.path.join(d, exe)):
            return d
    return None


def installed_dirs(game_dir, system):
    """Folders of an existing install, searched (not recursively) as a source of the pinned files."""
    return [game_dir, os.path.join(game_dir, "RedLua"), os.path.join(game_dir, "RedLua", "Langs"),
            os.path.join(system.program_data(), "ReShade")]


# What differs between the editions; install_enhanced.py passes its own.
LEGACY = {"title": "GTA V Legacy", "exe": EXE, "exchange": EXCHANGE, "settings_xml": settings_xml,
          "apis": tuple(DX_VERSION), "default_api": "d3d11", "dx_version_setting": True,
          # Script Hook V's own ASI loader: GTA5.exe loads dinput8.dll
          "asi_loader": ("scripthook_v", "dinput8.dll", "dinput8.dll")}


def steps(ctx, ed=LEGACY):
    g, opt = ctx.game_dir, ctx.options
    exe = os.path.join(g, ed["exe"])
    api = opt.get("api") or ed["default_api"]
    if api not in ed["apis"]:
        raise ValueError("%s runs on %s, not %s" % (ed["title"], ", ".join(ed["apis"]), api))
    if opt.get("optiscaler") and not ed.get("optiscaler"):
        raise ValueError("--optiscaler: GTA V Legacy has no upscaler (DLSS, FSR, XeSS) for OptiScaler to take over")
    if opt.get("ray_tracing"):
        raise ValueError("--ray-tracing is RDR2's Reality Redemption 2; there is none for GTA V")
    if opt.get("graphics_mod") and not ed.get("graphics_mod"):
        raise ValueError("--graphics-mod: none is pinned for %s" % ed["title"])
    if opt.get("dlss_mode") and (not ed.get("dlss_mode") or opt["dlss_mode"] not in DLSS_MODES):
        raise ValueError("--dlss-mode %s: %s" % (opt["dlss_mode"], "one of " + ", ".join(DLSS_MODES) if ed.get("dlss_mode")
                                                 else "%s has no DLSS" % ed["title"]))
    exchange = opt.get("exchange_dir") or ed["exchange"]      # tests point these two elsewhere
    xml = opt.get("settings_xml") or ed["settings_xml"]()
    out = []

    # Script Hook V and an ASI loader the game loads, RedLua, Native Trainer
    out.append(CopyFile(ctx.file("scripthook_v", "ScriptHookV.dll"), os.path.join(g, "ScriptHookV.dll")))
    mod, name, installed_as = ed["asi_loader"]
    out.append(CopyFile(ctx.file(mod, name), os.path.join(g, installed_as),
                        what="ASI loader (%s) as %s" % (ctx.files.mods[mod].get("title", mod), installed_as)))
    out += wine.dll_overrides(ctx, ed["exe"], [os.path.splitext(installed_as)[0]])     # under Proton: the ASI loader
    if installed_as != "dinput8.dll":
        # Script Hook V's own loader, where its readme puts it: Enhanced loads dinput8.dll only late,
        # for DirectInput, and that loader then loads every plug-in a second time
        sha = next(f["sha256"] for f in ctx.files.mods["scripthook_v"]["files"] if f["name"] == "dinput8.dll")
        out.append(RemoveFile(os.path.join(g, "dinput8.dll"), sha, tag="mods",
                              why="Script Hook V's own ASI loader: a second loader, loaded late"))
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
    out.append(WriteText(os.path.join(g, "RedLua", "Scripts", "capture_loader.lua"), redlua.loader_text(ctx.system.game_path(exchange)),
                         tag="scripts", what="adapters/common/lua/capture_loader.lua, watching %s" % exchange))
    out.append(MakeDir(exchange, tag="scripts"))

    # game-agnostic components, as GTA V wants them: ReShade through Script Hook V's loader, no effects
    config_dir = os.path.join(exchange, "reshade") if ed.get("reshade_outside") else None
    if opt.get("preset"):
        out += visual_steps(ctx, g, exe, api, config_dir)
    else:
        out += reshade.steps(ctx, exe, api, asi_loader=True, config_dir=config_dir)
    out += addon.steps(ctx, g, exchange, config_dir=config_dir)

    # OptiScaler (Enhanced has DLSS for it to take over), loaded as an .asi like ReShade
    if ed.get("optiscaler"):
        if opt.get("optiscaler"):
            out += optiscaler.steps(ctx, g, api, loader="asi", settings=ed.get("optiscaler_settings", ()))
        else:
            out += optiscaler.not_loaded(ctx, g, loader="asi")

    # the edition's graphics mod (Enhanced: NaturalVision Enhanced), straight from its archive
    gm = ed.get("graphics_mod")
    if gm:
        if opt.get("graphics_mod"):
            out += pack.steps(ctx, g, gm["mod"], tag="graphicsmod")
            gm_settings = opt.get("graphics_mod_settings") or gm["settings_file"]()     # tests point it elsewhere
            for key, value, why in gm["settings"]:
                out.append(JsonSet(gm_settings, key, value, tag="graphicsmod", why=why))
        else:
            out += pack.not_installed(ctx, g, gm["mod"], tag="graphicsmod", why="not part of this install "
                                      "(--graphics-mod puts it back; its settings file stays)")

    # game settings
    if ed["dx_version_setting"]:
        out.append(XmlSet(xml, "DX_Version", DX_VERSION[api], why="the graphics API ReShade is installed for"))
    if ed.get("optiscaler"):   # Enhanced: upscalers and frame generation built in
        out.append(XmlSet(xml, "FrameGenType", "0", why="no frame generation: a generated frame is not a render"))
        if ed.get("ray_tracing_setting"):
            out.append(XmlSet(xml, "Raytracing_Enabled", "true", why="the game's ray tracing (the capture default)"))
        # the game's own motion blur (its slider, 0-1; 1 on this machine): a camera move between two
        # shots must not smear the next one
        out.append(XmlSet(xml, "MotionBlurStrength", "0.000000", why="no motion blur"))
        if opt.get("optiscaler"):
            # ResScalingType: 0 off, 1 SSAA, 2 FSR 1, 3 FSR 3, 4 DLSS/DLAA (PCGamingWiki, 2026-11-21)
            out.append(XmlSet(xml, "ResScalingType", "4", why="the game's DLSS on: OptiScaler takes over that call"))
            mode = opt.get("dlss_mode") or ed["dlss_mode"]
            out.append(XmlSet(xml, "dlssQuality", DLSS_MODES[mode], why="DLSS mode: %s" % mode))
            out.append(XmlSet(xml, "dlssSharpen", DLSS_SHARPEN, why="pinned (DLSS itself does not sharpen: "
                                                                     "OptiScaler logs SharpenEnabled false)"))
    card = ctx.system.gpu_name()
    if card:
        # as RDR2: the game throws its graphics settings away when the card named in the file is not
        # the machine's (RDR2 did, with the PC's file on the CoreWeave node, 2026-11-23)
        out.append(XmlSet(xml, "VideoCardDescription", card, why="this machine's GPU: the game resets its settings otherwise"))
    out.append(XmlSet(xml, "VSync", "0", why="uncapped frame rate"))
    out.append(XmlSet(xml, "PauseOnFocusLoss", "0", why="the game keeps running if focus is lost"))
    if opt.get("resolution"):
        w, h = (int(v) for v in opt["resolution"].lower().split("x"))
        if abs(w / h - 16 / 9) > 0.01:
            raise ValueError("the capture window must be 16:9, not %dx%d" % (w, h))
        mode, why = "1", "windowed"
        if host.LINUX and ed.get("title") == "GTA V Enhanced":
            from ..common import window
            if tuple(window.desktop_size()) == (w, h):
                # On a display of exactly the capture size Enhanced does not open a window that large:
                # set to windowed it came up 1920x1080 in the middle of a 2560x1440 headless display,
                # and did not follow a resize. 3 is what the game itself wrote there on its first
                # start, and it then fills the display (2026-11-23).
                mode, why = "3", "fills the display, which is the capture size (what the game chose there)"
        out += [XmlSet(xml, "Windowed", mode, why=why), XmlSet(xml, "ScreenWidth", str(w)),
                XmlSet(xml, "ScreenHeight", str(h))]
    return out


VISUAL = os.path.join(HERE, "visual")
VISUAL_MODS = ("reshade_shaders", "quint", "astrayfx")     # the effects the presets use (mods.lock.json)
# --preset: five presets, switched live by keys no keyboard has (tools/preset_ab.py presses them).
# With --preset the capture preset is the grade with Clarity (Nathan's pick before NVE, 2026-11-21);
# ReShade remembers whichever was switched to last. Enhanced's default is NVE without these.
CAPTURE_PRESET = "ReShadePreset.grade_clarity.ini"
PRESETS = (("ReShadePreset.capture.ini", None, 125, "no effects (F14)"),
           ("ReShadePreset.ini", CAPTURE_PRESET, 126, "the capture preset: the colour grade with Clarity (F15)"),
           ("ReShadePreset.grade_ss.ini", "ReShadePreset.grade_ss.ini", 127, "the grade with screen-space MXAO, SSR "
                                                                              "and Clarity (F16)"),
           ("ReShadePreset.depth.ini", "ReShadePreset.depth.ini", 128, "the depth buffer, to check it (F17)"),
           ("ReShadePreset.grade.ini", "ReShadePreset.grade.ini", 129, "the colour grade alone (F18)"))


def visual_steps(ctx, g, exe, api, config_dir):
    """GTA V's visual presets (adapters/gtav/visual/), for comparing a colour grade and screen-space
    effects at one frozen instant; measured on Enhanced (README)."""
    effects = [(ctx.file(m, f["name"]), f["install"]) for m in VISUAL_MODS for f in ctx.files.mods[m]["files"]]
    out = reshade.steps(ctx, exe, api, preset=os.path.join(VISUAL, CAPTURE_PRESET),
                        preset_label="GTA V's capture preset: colour grade + Clarity (adapters/gtav/visual)",
                        effects=effects, asi_loader=True, config_dir=config_dir)
    base = config_dir or g
    for name, src, _, what in PRESETS:
        if src is None:
            out.append(WriteText(os.path.join(base, name), reshade.EMPTY_PRESET, tag="reshade", closed=True,
                                 what="preset: " + what))
        elif name != "ReShadePreset.ini":          # that one is the capture preset, copied above
            out.append(CopyFile(lambda p=os.path.join(VISUAL, src): p, os.path.join(base, name), tag="reshade",
                                what="preset: " + what))
    ini = reshade.config_path(g, config_dir)
    out += [IniSet(ini, "GENERAL", "PresetShortcutKeys", ",".join("%d,0,0,0" % k for _, _, k, _ in PRESETS),
                   tag="reshade", why="F14-F18 switch the presets"),
            IniSet(ini, "GENERAL", "PresetShortcutPaths", ",".join(".\\" + n for n, _, _, _ in PRESETS), tag="reshade")]
    return out


def after_install(ctx):
    """What to tell the user once the files are in place."""
    return ["Start GTA V Legacy through Steam and load story mode (never GTA Online with mods).",
            "Keys in game: F7 RedLua menu, F4 Native Trainer."]
