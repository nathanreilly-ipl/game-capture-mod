"""ReShade with add-on support, for any game (game-agnostic).

Needed by every game: our capture add-on runs inside it. The game's adapter says which
graphics API the game uses and which preset captures are taken with; this component does the rest.

- Vulkan: ReShade is a machine-wide Vulkan layer, as its own setup installs it: ReShade64.dll
  and ReShade64.json in %ProgramData%\\ReShade, the manifest registered under
  HKLM\\SOFTWARE\\Khronos\\Vulkan\\ImplicitLayers (machine-wide, so Windows asks for administrator
  approval once per machine), and the game's exe listed in ReShadeApps.ini (the layer only
  loads into listed applications).
- Direct3D / OpenGL: ReShade64.dll goes into the game folder under the API's DLL name.

The add-on saves frames after ReShade's effects, so the preset is part of what a capture looks
like. A game's visual set (adapters/<game>/visual/ReShadePreset.ini) is installed as the game's
ReShadePreset.ini, with the shader files it uses; without one (or with --no-preset) captures use
an empty preset of their own and the game's ReShadePreset.ini is left alone.

config_dir: a game that locks its own folder while it runs (GTA V Enhanced opens every file there
read-only, denying writes, so ReShade shows "Unable to save configuration" over every frame) keeps
ReShade's config, preset and log in a folder of ours instead: the game folder's ReShade.ini only
says [INSTALL] BasePath=<config_dir>, which ReShade reads first.
"""
import os

from ..plan import Call, CopyFile, Ini, IniListAdd, IniSet, MakeDir, RemoveFile, WriteText

MOD = "reshade"
API_DLL = {"d3d9": "d3d9.dll", "d3d10": "dxgi.dll", "d3d11": "dxgi.dll", "d3d12": "dxgi.dll", "dxgi": "dxgi.dll",
           "opengl": "opengl32.dll"}
EMPTY_PRESET = "Techniques=\r\nTechniqueSorting=\r\n"
PRESET = "ReShadePreset.ini"            # ReShade's default name
EMPTY_PRESET_NAME = "ReShadePreset.capture.ini"
SHADERS = ".\\reshade-shaders\\Shaders\\**"
TEXTURES = ".\\reshade-shaders\\Textures\\**"


def common_dir(ctx):
    return os.path.join(ctx.system.program_data(), "ReShade")


def _apps(ctx):
    v = Ini(os.path.join(common_dir(ctx), "ReShadeApps.ini")).get("", "Apps")
    return [a for a in (v or "").split(",") if a]


OTHER_NAME = "ReShade64.dll"  # the name other mods load ReShade by (OptiScaler's LoadReshade)


ASI_NAME = "ReShade.asi"


def config_path(game_dir, config_dir=None):
    """ReShade.ini as ReShade uses it: in config_dir when the game has one (see the module doc)."""
    return os.path.join(config_dir or game_dir, "ReShade.ini")


def steps(ctx, exe_path, api, preset=None, preset_label=None, effects=(), keep_preset=False, asi_loader=False,
          config_dir=None):
    """preset: path of the game's preset file, or None for no effects. effects: [(FileRef,
    path relative to the game folder)] of the shader files the preset uses. keep_preset: another
    step writes ReShadePreset.ini (e.g. a game's preset with an added effect); only the effects,
    search paths and PresetPath are set here. ReShade always loads itself, whatever other mods
    are installed (OptiScaler is told not to load it). asi_loader: the game loads .asi plug-ins
    (e.g. Script Hook's loader); on Direct3D ReShade then goes in as ReShade.asi, since a mod like
    OptiScaler preloads Windows' own dxgi.dll and a dxgi.dll ReShade would never load
    (measured in RDR2 on Direct3D 12, 2026-11-20)."""
    game_dir = os.path.dirname(exe_path)
    out = []
    dll = ctx.file(MOD, "ReShade64.dll")
    if api == "vulkan":
        common = common_dir(ctx)
        manifest = os.path.join(common, "ReShade64.json")
        apps_ini = os.path.join(common, "ReShadeApps.ini")

        def layer_status(c):
            return ("ok", "registered") if c.system.vulkan_layer_registered(manifest) else (
                "todo", "Windows will ask for administrator approval")

        def layer_apply(c):
            c.system.register_vulkan_layer(manifest)
            c.record.note(kind="machine", what="ReShade's Vulkan layer (%s)" % manifest)

        def apps_status(c):
            return ("ok", "listed") if exe_path in _apps(c) else ("todo", "add; Windows may ask for administrator approval")

        def apps_apply(c):
            ini = Ini(apps_ini)
            old = ini.get("", "Apps")
            new = ",".join(_apps(c) + [exe_path])
            c.record.setting("ini", apps_ini, "|Apps", old, new)
            ini.set("", "Apps", new)
            ini.save(c.system)  # ProgramData\ReShade: administrators only

        # a ReShade in the game folder from a Direct3D install would load a second time
        for other in sorted({ASI_NAME, OTHER_NAME} | set(API_DLL.values())):
            out.append(RemoveFile(os.path.join(game_dir, other), dll.sha256, tag="reshade",
                                  why="a second copy of ReShade; it must load once"))
        out += [CopyFile(dll, os.path.join(common, "ReShade64.dll"), tag="reshade", shared=True),
                CopyFile(ctx.file(MOD, "ReShade64.json"), manifest, tag="reshade", shared=True),
                Call("ReShade's Vulkan layer registered for this machine", layer_status, layer_apply, tag="reshade"),
                Call("%s listed in ReShadeApps.ini" % os.path.basename(exe_path), apps_status, apps_apply, tag="reshade",
                     closed=True)]
    elif api in API_DLL:
        name = ASI_NAME if asi_loader else API_DLL[api]
        out.append(CopyFile(dll, os.path.join(game_dir, name), tag="reshade", what="ReShade64.dll as " + name))
        # a copy under any other name would load a second time (two ReShades crash RDR2)
        for other in {OTHER_NAME, ASI_NAME, API_DLL[api]} - {name}:
            out.append(RemoveFile(os.path.join(game_dir, other), dll.sha256, tag="reshade",
                                  why="a second copy of ReShade; it must load once"))
        apps_ini = os.path.join(common_dir(ctx), "ReShadeApps.ini")

        def unlisted_status(c):
            return ("todo", "remove (the game ran on Vulkan before); Windows asks for administrator approval")                 if exe_path in _apps(c) else ("ok", "not listed")

        def unlisted_apply(c):
            ini = Ini(apps_ini)
            old = ini.get("", "Apps")
            new = ",".join(a for a in _apps(c) if a != exe_path)
            c.record.setting("ini", apps_ini, "|Apps", old, new)
            ini.set("", "Apps", new)
            ini.save(c.system)  # ProgramData\ReShade: administrators only

        # a machine-wide Vulkan layer from an earlier install must not hook the game as well
        out.append(Call("%s not in ReShadeApps.ini (ReShade's Vulkan layer stays out)" % os.path.basename(exe_path),
                        unlisted_status, unlisted_apply, tag="reshade", closed=True))
        manifest = os.path.join(common_dir(ctx), "ReShade64.json")

        def layer_status(c):
            if not c.system.vulkan_layer_registered(manifest):
                return "ok", "not registered"
            if _apps(c):
                return "ok", "registered, used by: %s" % ", ".join(os.path.basename(a) for a in _apps(c))
            return "todo", "unregister: no Vulkan app is listed, yet its copy of ReShade loads into the game; " \
                           "Windows asks for administrator approval"

        def layer_apply(c):
            c.system.unregister_vulkan_layer(manifest)
            c.record.note(kind="machine", what="ReShade's Vulkan layer unregistered (%s); capture install --api vulkan "
                                               "registers it again" % manifest)

        # Measured 2026-11-20: with RDR2 on Direct3D 12 and off the app list, the layer still loaded
        # ReShade from ProgramData into the game, next to the game's own: out of memory on start.
        out.append(Call("ReShade's machine-wide Vulkan layer unregistered while no Vulkan app uses it", layer_status,
                        layer_apply, tag="machine", closed=True))
    else:
        raise ValueError("ReShade cannot hook graphics API %r" % api)

    # relative paths in ReShade's config (presets, search paths) are relative to its base folder
    base = config_dir or game_dir
    if config_dir:
        out += [MakeDir(config_dir, tag="reshade"),
                IniSet(os.path.join(game_dir, "ReShade.ini"), "INSTALL", "BasePath", config_dir, tag="reshade",
                       why="ReShade's config, preset and log live there: the game denies writes to its own folder")]
    ini = config_path(game_dir, config_dir)
    if keep_preset:
        for ref, rel in effects:
            out.append(CopyFile(ref, os.path.join(base, *rel.split("/")), tag="reshade"))
        out += [IniSet(ini, "GENERAL", "PresetPath", ".\\" + PRESET, tag="reshade", why="the game's preset"),
                IniListAdd(ini, "GENERAL", "EffectSearchPaths", SHADERS, tag="reshade", why="where the preset's effects are"),
                IniListAdd(ini, "GENERAL", "TextureSearchPaths", TEXTURES, tag="reshade")]
    elif preset:
        out.append(CopyFile(lambda: preset, os.path.join(base, PRESET), tag="reshade",
                            what=preset_label or "the game's ReShade preset"))
        for ref, rel in effects:
            out.append(CopyFile(ref, os.path.join(base, *rel.split("/")), tag="reshade"))
        out += [IniSet(ini, "GENERAL", "PresetPath", ".\\" + PRESET, tag="reshade", why="the game's preset"),
                IniListAdd(ini, "GENERAL", "EffectSearchPaths", SHADERS, tag="reshade", why="where the preset's effects are"),
                IniListAdd(ini, "GENERAL", "TextureSearchPaths", TEXTURES, tag="reshade")]
    else:
        out += [WriteText(os.path.join(base, EMPTY_PRESET_NAME), EMPTY_PRESET, tag="reshade", closed=True,
                          what="an empty ReShade preset: captures without effects"),
                IniSet(ini, "GENERAL", "PresetPath", ".\\" + EMPTY_PRESET_NAME, tag="reshade",
                       why="captures without effects; your own preset file is left as it is")]
    out.append(IniSet(ini, "OVERLAY", "TutorialProgress", "4", tag="reshade", why="no first-run tutorial over the game"))
    return out
