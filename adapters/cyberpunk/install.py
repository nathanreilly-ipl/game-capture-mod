"""What a Cyberpunk 2077 (patch 2.5, Steam) install needs, for `capture install cyberpunk`.

Game-agnostic components do ReShade and the capture add-on; this file says how Cyberpunk wants
them (Direct3D 12, ReShade as an .asi plug-in) and adds what only Cyberpunk needs:

- Cyber Engine Tweaks: the game's script API in Lua, and an ASI loader (version.dll) that also
  loads ReShade.asi. Its files are installed where its archive has them (bin\\x64\\...). A build
  supports exactly one game version (1.38.1: patch 2.5, file version 3.0.88.46235); a game update
  needs a new build.
- RED4ext (native plug-ins; winmm.dll loader), redscript (the script compiler) and Codeware (more
  of the engine opened to scripts): the adapter sets the weather through Codeware, which patch 2.5
  no longer allows through the game's own script interface.
- Its overlay key set beforehand (bindings.json: the ~ key), or its first start opens the overlay
  and waits for a key to be bound.
- Our mod (lua/capture_mod/init.lua) in its mods folder, with the exchange folder inside it:
  a Cyber Engine Tweaks mod reads and writes only inside its own folder (paths.py).
- Our clock plug-in (capture/install/components/clock.py) in bin\\x64\\plugins, holding the clock
  of the game's exe and of Bink, its video player: video ads, holograms and blinking lights run
  on that clock, not on the simulation's, so a time dilation does not hold them.

- Game settings for captures (settings.py: path tracing with Ray Reconstruction and DLAA, no
  frame generation, no lens effects, the render window), written into the game's own settings
  file while the game is closed. The game writes that file on its first start, so on a fresh
  machine: start the game once, close it, run install again.

- DLSS 5 (option "optiscaler", `--optiscaler`, off by default until it is measured in the game):
  the shared OptiScaler component (the DLSS 5 fork) as OptiScaler.asi in bin\\x64\\plugins, with
  your nvngx_dlssnr.dll (`--dlss-nr`). It runs on the output of the game's own DLSS (DLAA with Ray
  Reconstruction), with skin structure 2; F13 switches it live (tools/upscaler_ab.py).

- The visual set (option "preset", off by default until it is measured in the game): Ultra Plus
  (path tracing tuned further), Nova LUT (colour grading) and Remove Mods Menu, from Nexus Mods,
  which needs a login, so they are supplied by hand (docs/MOD_FILES.md). They are mods, not a
  ReShade preset: captures still pass through ReShade with no effects.
"""
import os
import re

from capture import config, host
from capture.install.components import addon, clock, optiscaler, reshade
from capture.install.plan import Call, CopyFile, IniSet, JsonSet, MakeDir, RemoveFile, WriteText

from . import paths, settings as game_settings

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = paths.GAME
TITLE = "Cyberpunk 2077 (Steam)"
EXE = paths.EXE_NAME          # the process name
EXE_PATH = paths.EXE          # where it is in the game folder
STEAM_APP = paths.STEAM_APP
FOLDER = paths.FOLDER
LOCK = os.path.join(HERE, "mods.lock.json")
OPTIONS = {"preset": False, "api": "d3d12", "resolution": "2560x1440",   # the render size (adapter.py)
           "optiscaler": False}   # DLSS 5, until measured in this game
CET = "cyber_engine_tweaks"
FRAMEWORKS = ("red4ext", "redscript", "codeware")
VISUAL_SET = ("ultra_plus", "nova_lut", "remove_mods_menu")   # the option "preset"; from Nexus Mods, supplied
# Ultra Plus for captures (its UltraPlusConfig.ini): the path tracing mode and top quality its
# makers give for an RTX 5090, fixed instead of scaled to a frame rate, and nothing drawn on screen.
ULTRA_PLUS = [("internal.mode", "PT21"), ("internal.quality", "Insane"), ("internal.sharc", "Insane"),
              ("internal.streaming", "High"), ("internal.simpleMode", "false"), ("internal.showFps", "false"),
              ("internal.showVram", "false"), ("internal.showVramWarnings", "false"),
              ("internal.showIncompatibleModWarnings", "false"), ("internal.showPQSaturationWarning", "false")]
# DLSS 5 for captures (--optiscaler), on top of the shared component's settings: skin structure 2,
# the most pore and beard detail (Nathan, 2026-11-22, after tools/dlss5_skin_sweep.py; as GTA V and RDR2)
OPTISCALER_SETTINGS = [("DlssNr", "SkinStructure", "2", "skin structure 2: more skin detail (chosen 2026-11-22)")]
MOD_SRC = os.path.join(HERE, "lua", paths.MOD_NAME)
OVERLAY_KEY = 0xC0 << 48      # the ~ key (VK_OEM_3), as Cyber Engine Tweaks stores a single key


def find_game_dir():
    """The game folder: this machine's config, the environment variable, then the Steam libraries."""
    known = config.game(GAME).get("game_dir") or os.environ.get("CYBERPUNK_DIR")
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
    b = paths.bin_dir(game_dir)
    return [b, os.path.join(b, "plugins"), os.path.join(system.program_data(), "ReShade")]


def steps(ctx):
    g, opt = ctx.game_dir, ctx.options
    b = paths.bin_dir(g)
    exe = os.path.join(g, EXE_PATH)
    api = opt.get("api") or "d3d12"
    if api != "d3d12":
        raise ValueError("Cyberpunk 2077 runs on Direct3D 12 only, not %s" % api)
    if opt.get("ray_tracing"):
        raise ValueError("--ray-tracing is not set up for Cyberpunk 2077 (the game path traces by itself)")
    exchange = opt.get("exchange_dir") or paths.exchange(g)   # tests point it elsewhere
    mod = os.path.dirname(exchange)
    out = []

    # Cyber Engine Tweaks and the frameworks, every file where its archive has it
    for name in (CET,) + FRAMEWORKS:
        for f in ctx.files.mods[name]["files"]:
            out.append(CopyFile(ctx.file(name, f["name"]), os.path.join(g, *f["name"].split("/"))))
    if opt.get("preset"):
        # the visual set: mods, not a ReShade preset (captures still pass through ReShade with no effects)
        for name in VISUAL_SET:
            for f in ctx.files.mods[name]["files"]:
                out.append(CopyFile(ctx.file(name, f["name"]), os.path.join(g, *f["name"].split("/"))))
        ultra_ini = os.path.join(g, paths.CET_DIR, "mods", "UltraPlus", "UltraPlusConfig.ini")
        for key, value in ULTRA_PLUS:
            out.append(IniSet(ultra_ini, "UltraPlus", key, value, tag="settings",
                              why="Ultra Plus for captures: fixed top quality, nothing on screen"))
    else:
        # the visual set is optional: installing without it takes its files out again (backed up)
        for name in VISUAL_SET:
            for f in ctx.files.mods[name]["files"]:
                out.append(RemoveFile(os.path.join(g, *f["name"].split("/")), f["sha256"], tag="mods",
                                      why="the visual set is off (install with the preset option to have it)"))
    out.append(JsonSet(os.path.join(g, paths.CET_DIR, "bindings.json"), "cet", {"overlay_key": OVERLAY_KEY}, tag="mods",
                       why="the overlay on the ~ key: no first-start prompt to bind one"))

    # our mod (can be written while the game runs; Cyber Engine Tweaks reloads mods from its overlay)
    for d, _, names in os.walk(MOD_SRC):
        for n in sorted(names):
            src = os.path.join(d, n)
            rel = os.path.relpath(src, MOD_SRC)
            out.append(WriteText(os.path.join(mod, rel), open(src, encoding="utf-8").read(), tag="scripts",
                                 what="adapters/cyberpunk/lua/%s/%s" % (paths.MOD_NAME, rel.replace(os.sep, "/"))))
    out += [MakeDir(exchange, tag="scripts"), MakeDir(os.path.join(exchange, "jobs"), tag="scripts")]

    # game-agnostic components, as Cyberpunk wants them: ReShade through the ASI loader, no effects
    # (the loader only reads bin\x64\plugins: its global.ini has LoadFromScriptsOnly=1)
    plugins = os.path.join(b, "plugins")
    out += reshade.steps(ctx, exe, api, asi_loader=True, asi_dir=plugins)
    out += addon.steps(ctx, plugins, exchange)   # ReShade's config and add-ons: beside its own file
    # the clock the game and its video player (Bink) read, held while a held world is captured
    out += clock.steps(plugins, os.path.join(exchange, "clock.txt"), os.path.join(exchange, "clock_status.txt"),
                       (paths.EXE_NAME, "bink2w64.dll"))
    # DLSS 5 (--optiscaler; off until it is measured here): OptiScaler.asi through the same loader,
    # its settings, the forwarder and NVIDIA's model beside it (the model may sit beside OptiScaler
    # or the exe). The game's own DLSS stays on (DLAA with Ray Reconstruction, settings.py); with Ray
    # Reconstruction the fork runs DLSS 5 on the upscaler's output (its 1.3.0 notes).
    if opt.get("optiscaler"):
        out += optiscaler.steps(ctx, plugins, api, loader="asi", settings=OPTISCALER_SETTINGS)
    else:
        out += optiscaler.not_loaded(ctx, plugins, loader="asi")

    # game settings, in the game's own settings file
    size = tuple(int(v) for v in (opt.get("resolution") or "2560x1440").lower().split("x"))
    if abs(size[0] / size[1] - 16 / 9) > 0.01:
        raise ValueError("the render size must be 16:9, not %dx%d" % size)
    path = opt.get("user_settings") or game_settings.user_settings_path()   # tests point it elsewhere
    wanted = game_settings.profile(size, desktop=opt.get("desktop"))

    def settings_status(c):
        if not os.path.exists(path):
            return "ok", "skipped: no settings file yet (start the game once, close it, then run install again)"
        changes = game_settings.file_changes(path, wanted)
        return ("ok", "set") if not changes else ("todo", "%d to change: %s" % (len(changes), ", ".join(
            "%s=%s" % (n, w["value"]) for _, n, _, w in changes)))

    def settings_apply(c):
        c.record.file(path, None)   # backed up before the first change
        game_settings.write_file(path, wanted)

    out.append(Call("game settings for captures (%s): path tracing, Ray Reconstruction, DLAA, no frame generation, "
                    "no lens effects, %dx%d" % ((os.path.basename(path),) + size), settings_status, settings_apply,
                    tag="settings", closed=True))
    return out


def after_install(ctx):
    """What to tell the user once the files are in place."""
    if host.LINUX:
        return ["The game starts under Proton without Steam: %s verify cyberpunk --launch (adapters/cyberpunk/launch.py)." % host.CLI,
                "Its saves and settings are in its prefix: %s" % host.user_dir(GAME, "saved_games")]
    return ["Start Cyberpunk 2077 through Steam (launch options --launcher-skip -skipStartScreen skip its launcher).",
            "Keys in game: ~ Cyber Engine Tweaks overlay, Home ReShade."]
