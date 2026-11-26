"""What an RDR2 (story mode, Steam) install needs, for `capture install rdr2`.

Game-agnostic components do ReShade, the capture add-on and (optionally) OptiScaler; this file
says how RDR2 wants them (Direct3D 12 by default, ReShade and OptiScaler as .asi plug-ins) and
adds what only RDR2 needs:

- Script Hook RDR2 with its ASI loader (dinput8.dll): loads script plug-ins and exposes the game's
  natives. ScriptHookRDR2.dev turns on its CTRL+R script reload, used for unattended recovery.
- RedLua: runs our Lua scripts in the game. Autorun on, so the loader starts by itself; its
  natives database patched with names for the photo-mode exposure natives.
- Native Trainer (optional, on by default): handy while scouting. Its menu is F5.
- Our scripts: capture_loader.lua (shared, adapters/common/lua: runs jobs without a keyboard),
  scout_overlay.lua.
- RDR2's visual set (adapters/rdr2/visual/): the ReShade preset captures are taken with, and the
  SweetFX and standard effects it uses (--no-preset: captures without effects). With
  --optiscaler, OptiScaler loads as an .asi through Script Hook's loader; its F6 comparison key
  is unbound because F6 is the game's camera mode.
- Game settings: VSync off (uncapped frame rate, so the settle after each camera move is
  shorter), no pause on focus loss, and the windowed size when --resolution is given.
"""
import json
import os
import re

from capture import config, host
from capture import paths as capture_paths
from capture.install.components import addon, optiscaler, reshade, wine

from . import raytracing
from ..common import redlua
from capture.install.plan import Call, CopyFile, JsonSet, MakeDir, WriteText, XmlSet
from capture.util import sha256_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = "rdr2"
TITLE = "Red Dead Redemption 2 (story mode, Steam)"
EXE = "RDR2.exe"
STEAM_APP = "1174180"
LOCK = os.path.join(HERE, "mods.lock.json")
# The Steam copy as the PC has it (2026-11-23), for a Steam client that is given the downloaded
# files instead of downloading them (capture/host/steam.py): RDR2.exe 1.0.1491.50
STEAM = {"app": STEAM_APP, "name": "Red Dead Redemption 2", "installdir": "Red Dead Redemption 2", "buildid": "13773296",
         "size": 128327186218,
         "depots": {"1174181": ("4757128409362785099", 746), "1174182": ("2258488483491377476", 78804578319),
                    "1174183": ("4785346550216140531", 390640), "1174184": ("2698939236196220127", 5460348964),
                    "1174185": ("8173342615013177810", 17767404187), "1174186": ("357926288062992323", 26009156930),
                    "1899671": ("4635231945872575760", 285697072)},
         "scripts": {"1174181": "installscript.vdf", "1899671": "installscript_sdk.vdf"},
         "shared": {"228987": "228980", "228990": "228980"}}
# Windows: Steam's default library. Linux (the game under Proton, capture/host): where a download
# of the game's Windows depots is kept, since there is no Steam client there.
DEFAULT_GAME_DIR = (os.path.join(capture_paths.OUT, "games", "rdr2") if host.LINUX
                    else r"C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2")
# Under Proton, Wine must load the game folder's own dinput8.dll (Script Hook's ASI loader)
DLL_OVERRIDES = "dinput8=n,b"
EXCHANGE = os.path.join(host.user_dir(GAME, "documents"), "RDR2Modding", "captures")
SCRIPTS = ("capture_loader.lua", "scout_overlay.lua")
# The default capture setup (2026-11-20): DLSS 5 (OptiScaler) and ray tracing (Reality Redemption 2),
# so Direct3D 12, at the 2560x1440 capture size. --no-optiscaler, --no-ray-tracing, --api vulkan
# and --resolution change it.
OPTIONS = {"native_trainer": True, "optiscaler": True, "preset": True, "ray_tracing": True, "api": "d3d12",
           "resolution": "2560x1440", "dlss_mode": "dlaa"}
VISUAL = os.path.join(HERE, "visual")
PRESET_MODS = ("reshade_shaders", "sweetfx")     # the effects visual/ReShadePreset.ini uses
OPTISCALER_SETTINGS = [("DlssNr", "CompareKey", "-1", "F6 is the game's camera mode"),
                       # DLSS 5's skin structure 2 (more skin detail, an even tone), as for GTA V Enhanced;
                       # Nathan's pick after tools/dlss5_skin_sweep.py in Saint Denis, 2026-11-22
                       ("DlssNr", "SkinStructure", "2", "skin structure 2: more skin detail (chosen 2026-11-22)")]
# The DLSS mode (--dlss-mode). The game's own modes stay at Quality (dlssQuality 2, the one it
# creates the DLSS feature for); DLAA comes from OptiScaler answering the game's render-size query
# with a ratio of 1.0 for Quality, so the game renders the full window size.
DLSS_MODES = {
    "dlaa": [("QualityOverrides", "QualityRatioOverrideEnabled", "true", "DLAA: OptiScaler's own ratio for Quality"),
             ("QualityOverrides", "QualityRatioQuality", "1.0", "DLAA: the game renders the full window size")],
    "quality": [("QualityOverrides", "QualityRatioOverrideEnabled", "false", "the game's Quality mode (1.5x up)")]}
REDLUA_SETTINGS = {"auto_updates": False, "autorun": True, "menu_hotkey": 118, "menu_language": "ingame",
                   "menu_position": 0}

# hash, name, parameter type, parameter name (names and types from alloc8or's rdr3-nativedb-data)
NATIVE_PATCHES = (("0x5CD6A2CCE5087161", "_SET_PHOTO_MODE_EXPOSURE_LOCKED", "BOOL", "locked"),
                  ("0xC8D0611D9A0CF5D3", "_CHANGE_PHOTO_MODE_EXPOSURE", "float", "value"),
                  ("0x9229ED770975BD9E", "_UPDATE_PHOTO_MODE_EXPOSURE", None, None))


def settings_xml():
    return os.path.join(host.user_dir(GAME, "documents"), "Rockstar Games", "Red Dead Redemption 2",
                        "Settings", "system.xml")


def find_game_dir():
    """The game folder: this machine's config, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("RDR2_DIR")
    if known and os.path.exists(os.path.join(known, EXE)):
        return known
    if host.LINUX:   # no Steam client: the game's Windows depots, downloaded to the default place
        return DEFAULT_GAME_DIR if os.path.exists(os.path.join(DEFAULT_GAME_DIR, EXE)) else None
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
        d = os.path.join(lib, "steamapps", "common", "Red Dead Redemption 2")
        if os.path.exists(os.path.join(d, EXE)):
            return d
    return None


def installed_dirs(game_dir, system):
    """Folders of an existing install, searched (not recursively) as a source of the pinned files."""
    shaders = os.path.join(game_dir, "reshade-shaders", "Shaders")
    return [game_dir, os.path.join(game_dir, "RedLua"), os.path.join(game_dir, "RedLua", "Langs"),
            os.path.join(system.program_data(), "ReShade"), shaders, os.path.join(shaders, "SweetFX")]


API_SETTING = {"vulkan": "kSettingAPI_Vulkan", "d3d12": "kSettingAPI_DX12"}  # system.xml <API>


def game_api():
    """The graphics API the game is set to, from its settings file (Vulkan when unknown)."""
    try:
        text = open(settings_xml(), encoding="utf-8", errors="replace").read()
    except OSError:
        return "vulkan"
    return "d3d12" if "kSettingAPI_DX12" in text else "vulkan"


def patch_natives(text):
    for h, name, ptype, pname in NATIVE_PATCHES:
        text = text.replace('"name": "_%s"' % h, '"name": "%s"' % name)
        if ptype:
            i = text.index('"%s"' % h)
            j = text.index('"return_type"', i)
            entry = text[i:j].replace('"type": "Any"', '"type": "%s"' % ptype).replace('"name": "p0"', '"name": "%s"' % pname)
            text = text[:i] + entry + text[j:]
    json.loads(text)  # must still be valid JSON
    return text


def _natives_step(ctx, dst):
    ref = ctx.file("redlua", "RedLua/natives.json")

    def patched(text):
        return all('"name": "%s"' % name in text for _, name, _, _ in NATIVE_PATCHES)

    def status(c):
        if os.path.exists(dst):
            return ("ok", "patched") if patched(open(dst, encoding="utf-8").read()) else ("todo", "patch")
        return ("todo", "copy and patch") if ref.found else ("missing", ref.missing_note)

    def apply(c):
        text = open(dst, encoding="utf-8").read() if os.path.exists(dst) else ref.read().decode("utf-8")
        data = patch_natives(text).encode("utf-8")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        c.record.file(dst, sha256_bytes(data))
        with open(dst, "wb") as f:
            f.write(data)

    return Call("RedLua natives database with the photo-mode exposure natives named -> %s" % dst, status, apply, closed=True)


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    exe = os.path.join(g, EXE)
    api = opt.get("api") or game_api()
    exchange = opt.get("exchange_dir") or EXCHANGE      # tests point these two elsewhere
    xml = opt.get("settings_xml") or settings_xml()
    if opt.get("graphics_mod"):
        raise ValueError("--graphics-mod: none is pinned for RDR2 (its look is the visual set and Reality Redemption 2)")
    if opt.get("dlss_mode") and opt["dlss_mode"] not in DLSS_MODES:
        raise ValueError("--dlss-mode %s: RDR2 takes %s (its own modes stay at Quality; DLAA goes through OptiScaler)"
                         % (opt["dlss_mode"], " or ".join(DLSS_MODES)))
    out = []

    # Script Hook, RedLua, Native Trainer
    for name in ("ScriptHookRDR2.dll", "dinput8.dll"):
        out.append(CopyFile(ctx.file("scripthook_rdr2", name), os.path.join(g, name)))
    if opt.get("native_trainer", True):
        out.append(CopyFile(ctx.file("scripthook_rdr2", "NativeTrainer.asi"), os.path.join(g, "NativeTrainer.asi")))
    out += wine.dll_overrides(ctx, EXE, ["dinput8"])      # under Proton: Script Hook's ASI loader
    out.append(WriteText(os.path.join(g, "ScriptHookRDR2.dev"), "", what="turns on Script Hook's CTRL+R script reload",
                         only_if_missing=True))
    for name in ("RedLua.asi", "lua51.dll", "RedLua/Langs/en.lng", "RedLua/Langs/ru.lng"):
        out.append(CopyFile(ctx.file("redlua", name), os.path.join(g, *name.split("/"))))
    out.append(_natives_step(ctx, os.path.join(g, "RedLua", "natives.json")))
    out.append(JsonSet(os.path.join(g, "RedLua", "Settings.json"), "autorun", True, default=REDLUA_SETTINGS, tag="mods",
                       why="our loader starts with the game"))

    # our scripts (can be copied while the game runs; reload with reload_scripts.ps1); the loader is
    # shared with other RedLua games and watches RDR2's exchange folder by default
    for name in SCRIPTS:
        src = os.path.join(HERE, "lua", name) if name != "capture_loader.lua" else redlua.LOADER
        out.append(CopyFile(lambda p=src: p, os.path.join(g, "RedLua", "Scripts", name), tag="scripts", closed=False,
                            what=os.path.relpath(src, os.path.dirname(os.path.dirname(HERE))).replace("\\", "/")))
    out.append(MakeDir(exchange, tag="scripts"))

    # game-agnostic components, as RDR2 wants them
    visual_preset = os.path.join(VISUAL, "ReShadePreset.ini")
    if opt.get("ray_tracing"):
        if api != "d3d12":
            raise ValueError("--ray-tracing (Reality Redemption 2) runs on Direct3D 12 only: add --api d3d12")
        if not opt.get("preset", True):
            raise ValueError("--ray-tracing needs the visual set's preset (it is added to it): leave out --no-preset")
    if opt.get("preset", True):
        effects = [(ctx.file(m, f["name"]), f["install"]) for m in PRESET_MODS for f in ctx.files.mods[m]["files"]]
        out += reshade.steps(ctx, exe, api, preset=None if opt.get("ray_tracing") else visual_preset,
                             preset_label="adapters/rdr2/visual/ReShadePreset.ini", effects=effects,
                             keep_preset=bool(opt.get("ray_tracing")), asi_loader=True)  # Script Hook's loader
    else:
        out += reshade.steps(ctx, exe, api, asi_loader=True)
    if opt.get("ray_tracing"):  # its presets (the visual set's with the effect added) take ReShadePreset.ini
        out += raytracing.steps(ctx, g, visual_preset)
    else:  # optional: without it, its add-on is not loaded (its other files stay)
        out += raytracing.not_loaded(ctx, g)
    out += addon.steps(ctx, g, exchange)
    if opt.get("optiscaler"):
        out += optiscaler.steps(ctx, g, api, loader="asi",   # Script Hook's ASI loader
                                settings=OPTISCALER_SETTINGS + DLSS_MODES[opt.get("dlss_mode") or OPTIONS["dlss_mode"]])
    else:  # optional: without --optiscaler it is not loaded (its loader file goes; its other files stay)
        out += optiscaler.not_loaded(ctx, g, loader="asi")

    # game settings
    card = ctx.system.gpu_name()
    if card:
        # the game throws its graphics settings away (1280x720, DLSS off) when the card named in the file
        # is not the machine's: seen with the PC's file on the CoreWeave node, 2026-11-23
        out.append(XmlSet(xml, "videoCardDescription", card, why="this machine's GPU: the game resets its settings otherwise"))
    if opt.get("api") in API_SETTING:  # --api switches the game itself too
        out.append(XmlSet(xml, "API", API_SETTING[opt["api"]], why="the graphics API ReShade is installed for"))
    if opt.get("optiscaler"):
        out.append(XmlSet(xml, "dlssIndex", "2", why="the game's DLSS on: OptiScaler takes over that call"))
        # quality 2 (the value that engaged on Vulkan); the game wrote 5 on its first Direct3D 12 start
        # and then never created a DLSS feature
        out.append(XmlSet(xml, "dlssQuality", "2", why="a DLSS mode the game creates the feature for"))
    out.append(XmlSet(xml, "vSync", "0", why="uncapped frame rate"))
    out.append(XmlSet(xml, "pauseOnFocusLoss", "false", why="the game keeps running if focus is lost"))
    # the PC's profile had it on (2026-11-24): moving people blurred along their 1/30 s motion, a
    # per-camera effect (AGENTS.md section 1, docs/VISUAL_CHECKS.md C)
    out.append(XmlSet(xml, "motionBlur", "false", why="no motion blur"))
    # the game relights its light probes only now and then: a gable switched between lit and shaded at
    # single clip frames (QC round 1, rdr2-001/006); every frame, a step's light follows the step
    out.append(XmlSet(xml, "probeRelightEveryFrame", "true", why="light probes relit every frame (no light switching at one step)"))
    if opt.get("resolution"):
        w, h = (int(v) for v in opt["resolution"].lower().split("x"))
        if abs(w / h - 16 / 9) > 0.01:
            raise ValueError("the capture window must be 16:9 (the frozen frame is letterboxed otherwise), not %dx%d" % (w, h))
        out += [XmlSet(xml, "windowed", "1", why="windowed"), XmlSet(xml, "screenWidthWindowed", str(w)),
                XmlSet(xml, "screenHeightWindowed", str(h))]
    return out


def after_install(ctx):
    """What to tell the user once the files are in place."""
    return ["Start the game through Steam and load story mode (or: .\\capture.ps1 verify rdr2 --launch).",
            "Keys in game: F7 RedLua menu, F5 Native Trainer, F8-F11 the scout overlay."]
