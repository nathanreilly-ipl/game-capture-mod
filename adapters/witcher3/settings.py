"""The game settings captures are taken with, in the game's own user settings file.

The Witcher 3 (the "Remastered" build, 5.01c) keeps what differs from its defaults in
Documents\\The Witcher 3\\dx12user.settings, an INI file. `capture install witcher3` writes the
values below while the game is closed; the adapter reads them back when a session opens.

Names and values are the game's own: sections and keys from the file, option values from its
settings definitions (bin\\config\\r4game\\user_config_matrix\\pc\\display.xml and graphics.xml,
read 2026-11-23): FullScreenMode 0 windowed, 1 borderless, 2 fullscreen; LimitFPS 0 unlimited;
AAMode 6 DLSS; DLSSQuality 5 DLAA.

Frame rate does not matter for captures (each shot waits for the picture to settle), so nothing
is traded for speed: no upscaling (DLAA), Ray Reconstruction on, no frame generation, and none of
the lens effects that differ from view to view or are not part of the scene (motion blur, blur,
depth of field, chromatic aberration, vignette, lens effects, sharpening).
"""
import os

from capture.install.plan import Ini


def window(size):
    return [
        ("Viewport", "FullScreenMode", "0", "windowed: the render size is the window's client size"),
        ("Viewport", "Resolution", '"%dx%d"' % size, "the render size"),
        ("Viewport", "VSync", "false", "frame rate sets the shot time"),
        ("Engine", "LimitFPS", "0", "no frame rate cap"),
        ("Game", "DoNotPauseWhileStopped", "true", "the game keeps running when its window is not in front"),
    ]


QUALITY = [
    ("PostProcess", "AAMode", "6", "DLSS"),
    ("PostProcess", "DLSSQuality", "5", "DLAA: no upscaling"),
    ("PostProcess", "EnableDLSSRR", "true", "Ray Reconstruction"),
    ("PostProcess", "DLSSGMode", "0", "no frame generation: a generated frame is not a render"),
    ("PostProcess", "FSRFramegen", "0", "no frame generation"),
    ("PostProcess", "XessFrameGeneration", "false", "no frame generation"),
    ("PostProcess", "AllowMotionBlur", "false", "a lens effect, not part of the scene"),
    ("PostProcess", "AllowBlur", "false", "a lens effect, not part of the scene"),
    ("PostProcess", "AllowDOF", "false", "differs from view to view"),
    ("PostProcess", "AllowCutsceneDOF", "false", "differs from view to view"),
    ("PostProcess", "AllowChromaticAberration", "false", "a lens effect, not part of the scene"),
    ("PostProcess", "AllowVignette", "false", "a lens effect, not part of the scene"),
    ("PostProcess", "AllowLensEffects", "false", "lens flares and dirt: not part of the scene"),
    ("PostProcess", "SharpenAmount", "0", "no sharpening"),
]

# no hints or welcome panels over the picture, and none that pause the world after a load
QUIET = [
    ("Gameplay", "HudTutorialEnabled", "false", "no tutorial hints on screen"),
    ("Hidden", "HasSeenEP1WelcomeMessage", "true", "no welcome panel after a load"),
    ("Hidden", "HasSeenEP2WelcomeMessage", "true", "no welcome panel after a load"),
    ("Hidden", "HasSeenDLCMessage", "true", "no welcome panel after a load"),
    ("Hidden", "HasSeen410WelcomeMessage", "true", "no welcome panel after a load"),
    ("Gameplay", "GameTelemetryConsent", "false", "no telemetry"),
    ("Gameplay", "MarketingTelemetryConsent", "false", "no telemetry"),
]


def ray_tracing(path_tracing):
    return [
        ("Rendering/RT", "EnableRT", "true", "ray-traced lighting, shadows and reflections"),
        ("Rendering/RT/PathTracer", "PTEnable", "true" if path_tracing else "false",
         "path tracing" if path_tracing else "path tracing off (ray tracing only)"),
    ]


def profile(size=(2560, 1440), path_tracing=True):
    """[(section, key, value, why)] for a capture install."""
    return window(size) + QUALITY + QUIET + ray_tracing(path_tracing)


def differences(path, wanted):
    """[(section, key, value in the file or None, wanted value)] where the file differs."""
    ini = Ini(path)
    return [(s, k, ini.get(s, k), v) for s, k, v, _ in wanted if ini.get(s, k) != v]


def read(path, keys):
    """{"Section/Key": value} for the given (section, key) pairs, for a take's record."""
    ini = Ini(path)
    return {"%s %s" % (s, k): ini.get(s, k) for s, k in keys}


RECORDED = [("Viewport", "FullScreenMode"), ("Viewport", "Resolution"), ("Viewport", "VSync"), ("Engine", "LimitFPS"),
            ("Rendering/RT", "EnableRT"), ("Rendering/RT/PathTracer", "PTEnable"), ("PostProcess", "AAMode"),
            ("PostProcess", "DLSSQuality"), ("PostProcess", "EnableDLSSRR"), ("PostProcess", "DLSSGMode"),
            ("PostProcess", "AllowMotionBlur"), ("PostProcess", "AllowDOF"), ("PostProcess", "AllowChromaticAberration"),
            ("PostProcess", "AllowVignette"), ("PostProcess", "AllowLensEffects"), ("PostProcess", "SharpenAmount")]


def exists(path):
    return os.path.exists(path)
