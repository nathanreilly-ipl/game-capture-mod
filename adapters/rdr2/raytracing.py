"""Reality Redemption 2 (BadassBaboon's ray tracing for RDR2), for `capture install rdr2
--ray-tracing`. Direct3D 12 only.

It is a ReShade add-on (RealityFX.addon64, with replacement game shaders under RealityFX\\)
driven by a ReShade effect (RealityRedemption2.fx) whose settings say which ray-traced passes
run. So it joins the game's preset instead of replacing it: the visual set's preset gets the
effect added in front, with the author's settings, and wet-ground reflections turned on.

Three presets, switched live by keys no keyboard has (tools/raytracing_ab.py presses them):
    F14  ReShadePreset.ini          the visual set with Reality Redemption 2 (the default)
    F15  ReShadePreset.rt_off.ini   the same with every ray-traced pass off
    F16  ReShadePreset.mod_off.ini  the visual set alone, Reality Redemption 2's settings neutral
The add-on and its replacement shaders stay loaded in all three, so "mod off" is not exactly the
game without the mod; a game start without --ray-tracing is.
"""
import os

from capture.install.plan import CopyFile, IniSet, RemoveFile, WriteText

MOD = "reality_redemption2"
TECHNIQUE = "RealityRedemption2@RealityRedemption2.fx"
SECTION = "[RealityRedemption2.fx]"
ON = {"RDR2_RTR_Ground": "1"}  # wet ground and puddles reflect too (off in the author's defaults)
RT_OFF = {"RDR2_RTS_Mode": "0", "RDR2_RTAO_Mode": "0", "RDR2_RTGI_Mode": "0", "RDR2_RTR_Water": "0",
          "RDR2_RTR_Glass": "0", "RDR2_RTR_Ground": "0", "RDR2_RTR_Characters": "0"}
# as close to the game as the effect's settings go: tonemapper Game, no sharpening or micro-contrast,
# the game's reflection step count and water reflection strength
MOD_OFF = dict(RT_OFF, RDR2_Tonemapper="0", RDR2_Sharpen="0.000000", RDR2_LaplaceMC="0.000000",
               RDR2_SSR_StepMult="1.000000", RDR2_Water_ReflectionStrength="1.000000")
PRESETS = {"ReShadePreset.ini": (True, ON), "ReShadePreset.rt_off.ini": (True, RT_OFF),
           "ReShadePreset.mod_off.ini": (False, MOD_OFF)}
KEYS = {"ReShadePreset.ini": 125, "ReShadePreset.rt_off.ini": 126, "ReShadePreset.mod_off.ini": 127}  # F14 F15 F16


def _section(text):
    """key -> value of the author's [RealityRedemption2.fx] section."""
    out, inside = {}, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = s == SECTION
        elif inside and "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def merged(visual_preset, author_preset, enabled, overrides):
    """The visual set's preset with Reality Redemption 2 added in front (or listed but off)."""
    lines = visual_preset.replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        if line.startswith("Techniques=") and enabled:
            rest = line[len("Techniques="):]
            line = "Techniques=" + TECHNIQUE + ("," + rest if rest else "")
        elif line.startswith("TechniqueSorting="):
            rest = line[len("TechniqueSorting="):]
            line = "TechniqueSorting=" + TECHNIQUE + ("," + rest if rest else "")
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    values = dict(_section(author_preset), **overrides)
    out += ["", SECTION] + ["%s=%s" % kv for kv in sorted(values.items())] + [""]
    return "\r\n".join(out)


def not_loaded(ctx, game_dir):
    """Ray tracing is optional: installing without it removes the add-on file (backed up), so
    ReShade does not load it; the visual set's own preset goes back in through the ReShade steps."""
    spec = next(f for f in ctx.files.mods[MOD]["files"] if f["name"] == "RealityFX.addon64")
    return [RemoveFile(os.path.join(game_dir, "RealityFX.addon64"), spec["sha256"], tag="raytracing",
                       why="ray tracing not loaded (install with --ray-tracing to load it)")]


def steps(ctx, game_dir, visual_preset_path):
    out = []
    mod = ctx.files.mods[MOD]
    for spec in mod["files"]:
        if spec.get("install"):
            out.append(CopyFile(ctx.file(MOD, spec["name"]), os.path.join(game_dir, *spec["install"].split("/")),
                                tag="raytracing"))
    author = ctx.file(MOD, "RealityRedemption2.ini")
    if not author.found:
        return out  # the copy steps above already report the archive as missing
    author_text = author.read().decode("utf-8", "replace")
    visual = open(visual_preset_path, encoding="utf-8").read()
    for name, (enabled, overrides) in PRESETS.items():
        out.append(WriteText(os.path.join(game_dir, name), merged(visual, author_text, enabled, overrides),
                             tag="raytracing", closed=True, what="preset: %s" % {
                                 "ReShadePreset.ini": "the visual set with ray tracing (F14)",
                                 "ReShadePreset.rt_off.ini": "the same, ray tracing off (F15)",
                                 "ReShadePreset.mod_off.ini": "the visual set alone (F16)"}[name]))
    ini = os.path.join(game_dir, "ReShade.ini")
    keys = ",".join("%d,0,0,0" % KEYS[n] for n in PRESETS)
    paths = ",".join(".\\" + n for n in PRESETS)
    out += [IniSet(ini, "GENERAL", "PresetShortcutKeys", keys, tag="raytracing", why="F14/F15/F16 switch the presets"),
            IniSet(ini, "GENERAL", "PresetShortcutPaths", paths, tag="raytracing")]
    return out
