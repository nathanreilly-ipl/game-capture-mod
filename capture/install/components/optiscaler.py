"""OptiScaler (the DLSS 5 fork, Skynizz/optiscaler-dlss5), optional, for any game (game-agnostic).

Turned on with --optiscaler. It takes over the game's own upscaler call (the game must have DLSS
turned on) and runs NVIDIA's DLSS 5 Neural Rendering model on the result. The game's adapter
says how the game loads it: as an .asi plug-in when the game has an ASI loader, else under a
proxy DLL name (winmm.dll), and may add settings of its own.

Files (from the lockfile entry "optiscaler_dlss5", each with its install path; {loader} is the
name the game loads it by): OptiScaler itself, the forwarder NVIDIA's model needs
(nvngx.dll_dlssnr.dll), OptiScaler.ini as shipped (copied once, then edited setting by setting,
so your own changes in its menu stay), and NVIDIA's model nvngx_dlssnr.dll, supplied by you.

Settings for captures, on top of the shipped defaults:
- No frame generation: a generated frame is not a render of the frozen world.
- DLSS 5 on, its edit cache off: the model runs on every frame, so nothing is carried over from
  the previous camera onto the next (with the cache, an edit is reprojected for up to 16 frames
  and its regional light eased over many more).
- Automatic white point (as the fork recommends), no before/after frames written beside the game.
- Its menu on End: ReShade's is Home by default (or Insert). F13 (on no keyboard, so never pressed by accident)
  switches DLSS 5 on and off live, which is how tools/upscaler_ab.py compares both at one frozen
  instant; the fork's other live switch (dlssnr-set.txt) is read on Direct3D 12 only.
- A log file (OptiScaler.log beside the game), to see whether DLSS 5 engaged.
"""
import os

from ..plan import CopyFile, IniSet, RemoveFile

MOD = "optiscaler_dlss5"
MODEL = "nvngx_dlssnr"
LOADERS = {"asi": "OptiScaler.asi", "winmm": "winmm.dll"}
UPSCALER_KEY = {"vulkan": "VulkanUpscaler", "d3d12": "Dx12Upscaler", "dxgi": "Dx12Upscaler", "d3d11": "Dx11Upscaler"}

SETTINGS = [  # (section, key, value, why)
    ("FrameGen", "Enabled", "false", "no generated frames in captures"),
    ("FrameGen", "FGInput", "nofg", ""),
    ("FrameGen", "FGOutput", "nofg", ""),
    ("DlssNr", "Enabled", "true", "DLSS 5 Neural Rendering"),
    ("DlssNr", "CacheEnabled", "false", "the model on every frame: nothing carried over between cameras"),
    ("DlssNr", "WhitePointSource", "3", "automatic white point"),
    ("DlssNr", "AutoCapture", "false", "no before/after frames written beside the game"),
    ("DlssNr", "ToggleKey", "124", "F13 switches DLSS 5 on and off live (tools/upscaler_ab.py); no keyboard has it"),
    ("Menu", "ShortcutKey", "0x23", "OptiScaler's menu on End; ReShade's is Home by default (Insert here)"),
    ("Log", "LogToFile", "true", "OptiScaler.log, to check that DLSS 5 engaged"),
    ("Plugins", "LoadReshade", "false", "ReShade loads itself; a second copy crashes the game"),
    ("Log", "LogLevel", "2", ""),
]


def not_loaded(ctx, game_dir, loader="winmm"):
    """OptiScaler is optional: installing without it removes the file the game loads it by (backed
    up); its settings and NVIDIA's model stay, so turning it on again is quick."""
    spec = next(f for f in ctx.files.mods[MOD]["files"] if f.get("install") == "{loader}")
    return [RemoveFile(os.path.join(game_dir, LOADERS[loader]), spec["sha256"], tag="optiscaler",
                       why="OptiScaler not loaded (install with --optiscaler to load it)")]


def steps(ctx, game_dir, api, loader="winmm", settings=()):
    """settings: [(section, key, value, why)] the game adds or overrides."""
    out = []
    ini = os.path.join(game_dir, "OptiScaler.ini")
    for spec in ctx.files.mods[MOD]["files"]:
        rel = spec.get("install", spec["name"]).replace("{loader}", LOADERS[loader])
        out.append(CopyFile(ctx.file(MOD, spec["name"]), os.path.join(game_dir, *rel.split("/")), tag="optiscaler",
                            only_if_missing=bool(spec.get("config"))))
    out.append(CopyFile(ctx.file(MODEL, "nvngx_dlssnr.dll"), os.path.join(game_dir, "nvngx_dlssnr.dll"), tag="optiscaler",
                        what="NVIDIA's DLSS 5 model"))
    chosen = {}
    for section, key, value, why in list(SETTINGS) + ([(("Upscalers", UPSCALER_KEY[api], "dlss", "DLSS as the upscaler"))]
                                                     if api in UPSCALER_KEY else []) + list(settings):
        chosen[(section, key)] = (value, why)
    for (section, key), (value, why) in chosen.items():
        out.append(IniSet(ini, section, key, value, tag="optiscaler", why=why))
    return out
