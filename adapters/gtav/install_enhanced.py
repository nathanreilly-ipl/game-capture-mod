"""What a GTA V Enhanced (story mode, Steam) install needs, for `capture install gtave`.

The same plan as Legacy (install.py), with what differs:

- The ASI loader. GTA5_Enhanced.exe does not import dinput8.dll (Legacy's GTA5.exe does; checked
  with dumpbin, 2026-11-21), so Script Hook V's own loader never runs at start, nor Script Hook V,
  and no log appears. Ultimate ASI Loader goes in as xinput1_4.dll, a DLL Enhanced does import.
  Script Hook V's dinput8.dll from a manual install is removed: Enhanced loads it late (for
  DirectInput) and it then loads every plug-in a second time.
- Direct3D 12 only; frame generation and the game's motion blur off; the game's ray tracing on.
  Enhanced has DLSS (through NVIDIA Streamline), FSR and SSAA built in: DLSS 5 (OptiScaler as an
  .asi through the same loader, as in RDR2; on by default, --no-optiscaler) turns the game's DLSS
  on (settings.xml ResScalingType 4) for OptiScaler to take over, with skin structure 2.
- NaturalVision Enhanced, the July 2026 build (on by default, --no-graphics-mod), with its lens
  effects (reflections and fringing around bright lights) and lateral chromatic aberration off:
  they depend on where each camera points, so neighbouring views would disagree. Its settings
  live outside the game folder (%APPDATA%\\NVE\\settings-gen9.json, read at start). No ReShade
  effects on top (the visual presets stay available with --preset): NVE has its own tonemapping
  and grading, so our grade would grade twice (Nathan, 2026-11-21).
- Its own settings file (Documents\\Rockstar Games\\GTAV Enhanced\\settings.xml) and exchange folder.
- ReShade's config outside the game folder. While Enhanced runs it holds every file in its folder
  open read-only and denies writes (BattlEye's texts too; seen 2026-11-21), so ReShade could never
  save and printed "Unable to save configuration" over every frame. The game folder's ReShade.ini
  only says [INSTALL] BasePath=<exchange>\\reshade, where ReShade keeps its config, preset and log.
  The same lock means nothing in the game folder (our loader script, RedLua's Settings.json) can
  be changed while the game runs.

Script Hook V 3889.0.1158.13 supports Enhanced 1.0.1158.13; an Enhanced update needs a new build.
"""
import os

from . import install as legacy

HERE = legacy.HERE
GAME = "gtave"
TITLE = "Grand Theft Auto V Enhanced (story mode, Steam)"
EXE = "GTA5_Enhanced.exe"
STEAM_APP = "3240220"
FOLDER = "Grand Theft Auto V Enhanced"
LOCK = legacy.LOCK
EXCHANGE = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "RDR2Modding", "captures_gtave")
# The capture default (Nathan, 2026-11-21): NaturalVision Enhanced, the game's ray tracing and
# DLSS 5 (OptiScaler, skin structure 2), no ReShade effects. --no-graphics-mod / --no-optiscaler /
# --preset change it.
OPTIONS = {"native_trainer": True, "preset": False, "api": "d3d12", "resolution": "2560x1440", "optiscaler": True,
           "graphics_mod": True}


from .settings_menu import settings_xml  # noqa: E402  (Documents\Rockstar Games\GTAV Enhanced\settings.xml)


def nve_settings():
    """NaturalVision Enhanced's settings, which it reads at start (and writes back on exit)."""
    return os.path.join(os.environ.get("APPDATA", ""), "NVE", "settings-gen9.json")


# NVE's effects that differ from camera to camera; its menu is in ReShade's overlay. Its motion blur
# (graphics.mb_config) has no label in this build, so the game's own motion blur is turned off instead.
NVE_SETTINGS = [(["graphics", "enable_lens_effects"], False, "no lens reflections or fringing around bright lights"),
                (["graphics", "LateralChromaticAberration"], False, "no colour fringing towards the frame edges"),
                # its screen-space ambient occlusion: off in this build's defaults, on in a settings file
                # a newer build left behind; pinned off, since the game's ray tracing does the occlusion
                (["graphics", "enable_vbao"], False, "no screen-space ambient occlusion on top of the ray-traced one")]

ENHANCED = {"title": "GTA V Enhanced", "exe": EXE, "exchange": EXCHANGE, "settings_xml": settings_xml,
            "apis": ("d3d12",), "default_api": "d3d12", "dx_version_setting": False, "optiscaler": True,
            "asi_loader": ("ultimate_asi_loader", "dinput8.dll", "xinput1_4.dll"), "reshade_outside": True,
            "ray_tracing_setting": True,
            # the game's DLSS mode under DLSS 5 (--dlss-mode; settings_menu.DLSS_MODES): DLAA, the full
            # 2560x1440 in, for DLSS 5's guides too; more fine detail than Quality in all 13 views at
            # Vinewood (4-16%), cleaner edges, the same frame rate (2026-11-22)
            "dlss_mode": "dlaa",
            # DLSS 5's skin structure: 2 (more pore and edge detail on skin only), Nathan's pick after
            # tools/dlss5_skin_sweep.py at Vinewood, 2026-11-21; the model's default is -1
            "optiscaler_settings": [("DlssNr", "SkinStructure", "2", "skin structure 2: more skin detail (chosen 2026-11-21)")],
            "graphics_mod": {"mod": "nve", "settings_file": nve_settings, "settings": NVE_SETTINGS}}


def find_game_dir():
    return legacy.find_game_dir(GAME, EXE, FOLDER, "GTAVE_DIR")


installed_dirs = legacy.installed_dirs


def steps(ctx):
    return legacy.steps(ctx, ENHANCED)


def after_install(ctx):
    return ["Start GTA V Enhanced through Steam and load story mode (never GTA Online with mods).",
            "Keys in game: F7 RedLua menu, F4 Native Trainer"
            + (", Home ReShade's overlay (NaturalVision Enhanced's menu is a tab there)." if ctx.options.get("graphics_mod")
               else ".")]
