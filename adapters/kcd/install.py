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
from capture.install.plan import CopyFile, IniSet, MakeDir, WriteText, XmlAttrSet

from . import paths

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = paths.GAME
TITLE = "Kingdom Come: Deliverance (Steam)"
EXE = paths.EXE_NAME
EXE_PATH = paths.EXE
STEAM_APP = paths.STEAM_APP
# On Linux the game checks its licence through a running Steam client (the rockstar prefix's,
# capture/host/steam.py), which must list it as installed: `capture host steam kcd` links the
# downloaded folder into that client's library and writes this manifest (values from the PC's
# appmanifest_379430.acf, 2026-11-24, without the DLC depot 836900 the node did not download).
STEAM = {"app": STEAM_APP, "name": "Kingdom Come: Deliverance", "installdir": "KingdomComeDeliverance", "buildid": "22623230",
         "size": 64209572471,
         "depots": {"379432": ("5694983311934705492", 64160333425), "379433": ("717100730472011277", 49239046)},
         "shared": {"228986": "228980", "228990": "228980"}}
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
    ("sys_PakPriority", "2", "the game's own files from its paks only: with loose files first (0) or after the paks (1), "
     "every file the engine looks for and lacks (level of detail models, ...) is looked up on disk, which under Wine on a "
     "network folder took minutes per level (the menu's did not load in 5 min on CoreWeave, 2026-11-24); our script "
     "switches to 0 for each read of its long inputs (Data\\capture_mod_in)"),
    ("r_Width", "2560", "the capture size"),
    ("r_Height", "1440", "the capture size"),
    ("r_Fullscreen", "0", "a window: frames are read from it and keys sent to it"),
    ("r_FullscreenWindow", "0", "a plain window, not borderless full screen"),
]


# The options the game saves from its menu (profiles\default\attributes.xml), applied at start over
# user.cfg: the capture look (adapter.VISUAL) written there with the game closed, so the game starts
# with it and the session's switch at run time changes nothing. Switching the specs at run time
# crashed the game once on a CoreWeave node (0xC0000005 right after sys_spec_Shading 4, whose file
# had no saved options; 2026-11-24); the PC's file had them all at 3 (High), with r_MotionBlur 2
# and vsync 1 over user.cfg's 0. Names as the game writes them (LodRatio and the other ratios are
# its e_* variables, on the same scale).
SPECS = ["sys_spec_GameEffects", "sys_spec_ObjectDetail", "sys_spec_Particles", "sys_spec_Physics", "sys_spec_PostProcessing",
         "sys_spec_Shading", "sys_spec_Shadows", "sys_spec_Texture", "sys_spec_Vegetation", "sys_spec_VolumetricEffects",
         "sys_spec_Water", "sys_spec_light"]
ATTRS = [(k, "4", "Ultra High") for k in SPECS] + [
    ("r_AntialiasingMode", "3", "SMAA 2TX"),
    ("LodRatio", "100", "object detail at the menu's maximum (e_LodRatio)"),
    ("ViewDistRatio", "100", "view distance at the menu's maximum (e_ViewDistRatio)"),
    ("MergedMeshesRatio", "100", "grass and small plants at the menu's maximum (e_MergedMeshesViewDistRatio)"),
    ("r_MotionBlur", "0", "a lens effect, not part of the scene"),
    ("vsync", "0", "frame rate sets the shot time"),
]
ATTRIBUTES_EMPTY = '<?xml version="1.0" encoding="us-ascii"?>\r\n<Attributes Version="31">\r\n</Attributes>\r\n'


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


MOD_STATUS = ("<ModStatus>\n  <modFolderWasMoved>true</modFolderWasMoved>\n"
              "  <playerWasNotified>true</playerWasNotified>\n</ModStatus>\n")


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
    # Without this file the game takes its first start for an update from an older version and
    # moves the whole mods folder, ours included, to mods_old (a CoreWeave node, 2026-11-24: then
    # "0 mods loaded"). The game's own copy, as it wrote it on the PC, never written over.
    out.append(WriteText(os.path.join(g, "mod_status.xml"), MOD_STATUS, tag="scripts", only_if_missing=True,
                         what="the game's mod status: mods were set up (it moves Mods\\ away at a first start otherwise)"))
    out.append(WriteText(os.path.join(m, "mod.manifest"), MANIFEST, tag="scripts", what="the mod's manifest"))
    out.append(CopyFile(build_pak, os.path.join(m, "Data", "capture_mod.pak"), tag="scripts", closed=True,
                        what="capture_mod.pak (adapters/kcd/lua/capture_mod.lua)"))
    out.append(MakeDir(exchange, tag="scripts"))
    out.append(MakeDir(paths.inbox(g), tag="scripts"))     # our script's long inputs (read with sys_PakPriority 0)

    # ReShade (dxgi.dll beside the exe, no effects) and our add-on
    out += reshade.steps(ctx, exe, api)
    out += addon.steps(ctx, b, exchange)
    out += wine.dll_overrides(ctx, EXE, ["dxgi"])     # under Proton: the game folder's dxgi.dll (ReShade)

    # console variables, read at every start
    cfg = opt.get("user_cfg") or paths.user_cfg(g)
    for key, value, why in CVARS:
        out.append(IniSet(cfg, "", key, value, tag="settings", why=why))

    # the options the game saves and applies at start, over user.cfg (see ATTRS)
    attrs = opt.get("attributes_xml") or paths.attributes_xml()
    for key, value, why in ATTRS:
        out.append(XmlAttrSet(attrs, key, value, empty=ATTRIBUTES_EMPTY, tag="settings", why=why))
    return out


def after_install(ctx):
    return ["Start it with: %s verify kcd --launch (adapters/kcd/launch.py starts the exe with -devmode)." % host.CLI]
