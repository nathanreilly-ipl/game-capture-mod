"""The game settings captures are taken with.

Frame rate does not matter for captures (each shot waits for the picture to settle), so
everything is at its best: path tracing ("Ray Tracing: Overdrive") with DLSS Ray Reconstruction
and DLAA (no upscaling) on the second-generation transformer model, no frame generation (a
generated frame is not a render), and none of the lens effects that differ from view to view
or are not part of the scene (film grain, chromatic aberration, depth of field, lens flares,
motion blur, vignette). The window is the adapter's render size (2560x1440 by default; see
adapter.py for when 3840x2160 is worth it).

How they are set: `capture install cyberpunk` writes them into the game's own settings file
(%LOCALAPPDATA%\\CD Projekt Red\\Cyberpunk 2077\\UserSettings.json) while the game is closed, and
the adapter reads them back from the running game when a session opens (check). Setting them
in the running game through its settings system worked once and crashed the game the second
time (an access violation as the renderer changed, 2026-11-21), and was not written to the file.

Names and values are the settings system's own, listed in the game with probes/repl.py
(2026-11-21, patch 2.5). The file stores a list setting as its value and its index, so the
lists are kept here; the resolutions are the ones the game offered on a 3840x2160 display.
"""
import json
import os

LISTS = {
    ("/video/display", "WindowMode"): ["Windowed", "BorderlessWindowed", "Fullscreen"],
    ("/video/display", "Resolution"): ["1024x768", "1280x720", "1280x960", "1280x1024", "1366x768", "1600x900", "1600x1200",
                                       "1680x1050", "1760x990", "1920x1080", "1920x1200", "2048x1536", "2560x1440",
                                       "3072x1728", "3200x1800", "3840x2160"],
    ("/video/display", "VSync"): ["UI-Settings-Video-QualitySetting-Off", "59"],
    ("/graphics/presets", "QuickPresets"): ["Custom", "Low", "Medium", "High", "Ultra", "Steam Deck", "Ray Tracing Low",
                                            "Ray Tracing Medium", "Ray Tracing Ultra", "Ray Tracing Overdrive"],
    ("/graphics/presets", "ResolutionScaling"): ["Off", "DLSS", "FSR2", "XeSS"],
    ("/graphics/presets", "DLSS"): ["Auto", "DLAA", "Quality", "Balanced", "Performance", "Ultra Performance", "Dynamic"],
    ("/graphics/presets", "DLSS_BackendPreset"): ["Transformer", "Transformer2", "Legacy"],
    ("/graphics/presets", "FrameGeneration"): ["Off", "DLSS", "FSR3"],
    ("/graphics/raytracing", "RayTracedLighting"): ["Off", "Medium", "Ultra", "Psycho"],
    ("/graphics/basic", "MotionBlur"): ["Off", "Low", "High"],
    ("/graphics/advanced", "LODPreset"): ["Low", "Medium", "High"],
    ("/graphics/performance", "CrowdDensity"): ["Low", "Medium", "High"],
}

# With path tracing on, the game itself turns the plain ray tracing switch off, hides its
# sub-settings and calls the quick preset "Custom" (seen 2026-11-21), so those are left alone:
# the installer would otherwise find them changed back after every run of the game.
QUALITY = [  # (group, name, value)
    ("/graphics/raytracing", "RayTracedPathTracing", "true"),
    ("/graphics/presets", "ResolutionScaling", "DLSS"),
    ("/graphics/presets", "DLSS", "DLAA"),
    ("/graphics/presets", "DLSS_BackendPreset", "Transformer2"),
    ("/graphics/presets", "DLSS_D", "true"),                           # Ray Reconstruction
    ("/graphics/presets", "DLAA_NewSharpness", "0"),
    ("/graphics/presets", "FrameGeneration", "Off"),
    ("/graphics/basic", "FilmGrain", "false"),
    ("/graphics/basic", "ChromaticAberration", "false"),
    ("/graphics/basic", "DepthOfField", "false"),
    ("/graphics/basic", "LensFlares", "false"),
    ("/graphics/basic", "MotionBlur", "Off"),
    ("/graphics/basic", "Vignette", "false"),
    ("/graphics/advanced", "LODPreset", "High"),
    ("/graphics/performance", "CrowdDensity", "High"),
]


def user_settings_path():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "CD Projekt Red", "Cyberpunk 2077", "UserSettings.json")


def display(size=(2560, 1440), desktop=None):
    """The window the game renders into: a plain window of that client size, or a borderless one
    when it is as large as the desktop (a window with a title bar would not fit)."""
    if desktop is None:
        from ..common import window
        desktop = (window.user32.GetSystemMetrics(0), window.user32.GetSystemMetrics(1))
    mode = "BorderlessWindowed" if tuple(size) == tuple(desktop) else "Windowed"
    return [("/video/display", "WindowMode", mode),
            ("/video/display", "Resolution", "%dx%d" % tuple(size)),
            ("/video/display", "VSync", "UI-Settings-Video-QualitySetting-Off"),
            ("/video/display", "MaximumFPS_OnOff", "false")]


def profile(size=(2560, 1440), desktop=None):
    return display(size, desktop) + QUALITY


def _stored(option, value):
    """The option as the file must hold it for `value`: {"value": ...} and, for lists, {"index": ...}."""
    kind = option.get("type", "")
    if kind == "bool":
        return {"value": value == "true"}
    if kind in ("float", "int"):
        return {"value": float(value) if kind == "float" else int(float(value))}
    return {"value": value}


def file_changes(path, settings):
    """[(group, name, what the file has, what it should have)] for the settings not yet in the
    game's settings file; raises ValueError for a setting or list value the file does not know."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    groups = {g["group_name"]: {o["name"]: o for o in g["options"]} for g in doc["data"]}
    out = []
    for group, name, value in settings:
        option = groups.get(group, {}).get(name)
        if option is None:
            raise ValueError("the game's settings file has no %s %s (a game update?)" % (group, name))
        want = _stored(option, value)
        if option.get("type", "").endswith("_list"):
            values = option.get("values") or LISTS.get((group, name))
            if not values or value not in values:
                raise ValueError("%s is not a value of %s %s (%s)" % (value, group, name, values))
            want["index"] = values.index(value)
        if any(option.get(k) != v for k, v in want.items()):
            out.append((group, name, {k: option.get(k) for k in want}, want))
    return out


def write_file(path, settings):
    """Writes the settings into the game's settings file (the game must be closed: it writes the
    file itself when it exits). Returns the changes made, as file_changes gives them."""
    changes = file_changes(path, settings)
    if not changes:
        return []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    todo = {(g, n): want for g, n, _, want in changes}
    for g in doc["data"]:
        for o in g["options"]:
            want = todo.get((g["group_name"], o["name"]))
            if want:
                o.update(want)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=4)
        f.write("\n")
    return changes


def check(sess, exchange, settings):
    """Reads the settings from the running game. Returns {"values": {(group, name): value now},
    "different": [(group, name, wanted, has)]}."""
    with open(os.path.join(exchange, "settings_in.txt"), "w", encoding="utf-8", newline="\n") as f:
        for group, name, value in settings:
            f.write("%s %s %s\n" % (group, name, value))
    st = sess.cmd("settings", "get", timeout=60)
    values, different = {}, []
    for n, (group, name, value) in enumerate(settings, 1):
        answer = st.get("s%d" % n, "")
        now = answer.split(" ", 2)[2] if answer.count(" ") >= 2 else answer
        values[(group, name)] = now
        if now != value:
            different.append((group, name, value, now))
    return {"values": values, "different": different}
