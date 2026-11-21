"""What a GTA V Enhanced (story mode, Steam) install needs, for `capture install gtave`.

The same plan as Legacy (install.py), with what differs:

- The ASI loader. GTA5_Enhanced.exe does not import dinput8.dll (Legacy's GTA5.exe does; checked
  with dumpbin, 2026-11-21), so Script Hook V's own loader never runs at start, nor Script Hook V,
  and no log appears. Ultimate ASI Loader goes in as xinput1_4.dll, a DLL Enhanced does import.
  Script Hook V's dinput8.dll from a manual install is removed: Enhanced loads it late (for
  DirectInput) and it then loads every plug-in a second time.
- Direct3D 12 only; frame generation off. Enhanced has DLSS (through NVIDIA Streamline), FSR and
  SSAA built in: --optiscaler (DLSS 5, as an .asi through the same loader, as in RDR2) turns the
  game's DLSS on (settings.xml ResScalingType 4) for OptiScaler to take over.
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
OPTIONS = {"native_trainer": True, "preset": False, "api": "d3d12", "resolution": "2560x1440", "optiscaler": False}


from .settings_menu import settings_xml  # noqa: E402  (Documents\Rockstar Games\GTAV Enhanced\settings.xml)


ENHANCED = {"title": "GTA V Enhanced", "exe": EXE, "exchange": EXCHANGE, "settings_xml": settings_xml,
            "apis": ("d3d12",), "default_api": "d3d12", "dx_version_setting": False, "optiscaler": True,
            "asi_loader": ("ultimate_asi_loader", "dinput8.dll", "xinput1_4.dll"), "reshade_outside": True}


def find_game_dir():
    return legacy.find_game_dir(GAME, EXE, FOLDER, "GTAVE_DIR")


installed_dirs = legacy.installed_dirs


def steps(ctx):
    return legacy.steps(ctx, ENHANCED)


def after_install(ctx):
    return ["Start GTA V Enhanced through Steam and load story mode (never GTA Online with mods).",
            "Keys in game: F7 RedLua menu, F4 Native Trainer."]
