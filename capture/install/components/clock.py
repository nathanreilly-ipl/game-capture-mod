"""Our clock plug-in (addons/clock, capture_clock.asi), for any game whose ASI loader loads
plug-ins: it holds the clock the game's own code reads, so what animates on real time (video
screens, holograms, blinking lights) stands still while a held world is captured. A game's own
time controls hold its simulation, not that clock.

It hooks only the modules a game names (its exe, its video player): the graphics driver, DLSS,
ReShade and the script host keep the real clock. The capture scripts hold and release it through
a control file; capture_clock.ini, next to the plug-in, says where that is.

Built from source with the C++ build tools, as the capture add-on is (addon.py), or taken
prebuilt from a mods bundle when it was built from exactly these sources (a machine without the
build tools; any Linux machine, where it runs inside the game under Proton).
"""
import os
import subprocess

from ... import paths
from ..plan import Call, CopyFile, InstallError, IniSet
from .addon import digest_of, find_cmake, no_build_note, prebuilt

SRC = os.path.join(paths.REPO, "addons", "clock")
BUILD_DIR = os.path.join(paths.REPO, "addons", "build_clock")
NAME = "capture_clock.asi"
INI = "capture_clock.ini"
BUILT = os.path.join(BUILD_DIR, "Release", NAME)
STAMP = "capture_clock.src.sha256"
BUILT_STAMP = os.path.join(BUILD_DIR, STAMP)
EXTRA_NAMES = (NAME, STAMP)     # found by name in a mods bundle, as the add-on's are


def source_digest():
    return digest_of(SRC)


def is_built():
    return os.path.exists(BUILT) and os.path.exists(BUILT_STAMP) and open(BUILT_STAMP).read().strip() == source_digest()


def build(log=print):
    cmake = find_cmake()
    if not cmake:
        raise InstallError("no C++ build tools: install Visual Studio Build Tools with 'Desktop development with C++'")
    for args in (["-S", SRC, "-B", BUILD_DIR, "-A", "x64"], ["--build", BUILD_DIR, "--config", "Release"]):
        r = subprocess.run([cmake] + args, capture_output=True, text=True)
        if r.returncode != 0:
            raise InstallError("building the clock plug-in failed:\n" + (r.stdout + r.stderr)[-2000:])
    with open(BUILT_STAMP, "w") as f:
        f.write(source_digest())
    log("  built %s" % BUILT)


def steps(asi_dir, control, status, modules):
    """asi_dir: where the game's ASI loader looks; control, status: the files the capture scripts
    and the plug-in talk through; modules: the game's modules whose clock is held."""
    state = {}

    def usable(c=None):
        if is_built():
            return BUILT
        if c is not None and "prebuilt" not in state:
            state["prebuilt"] = prebuilt(c, NAME, STAMP, source_digest())
        return state.get("prebuilt", (None, None))[0]

    def build_status(c):
        if is_built():
            return "ok", "built"
        if usable(c):
            return "ok", "prebuilt from %s" % state["prebuilt"][1]
        if find_cmake():
            return "todo", "build with CMake"
        return "missing", no_build_note("the clock plug-in")

    ini = os.path.join(asi_dir, INI)
    why = "where the clock plug-in takes commands and which modules' clock it holds"
    return [Call("clock plug-in built from addons/clock", build_status, lambda c: build(c.log), tag="clock"),
            CopyFile(usable, os.path.join(asi_dir, NAME), tag="clock", what="clock plug-in"),
            IniSet(ini, "clock", "Control", control, tag="clock", why=why, game_path=True),
            IniSet(ini, "clock", "Status", status, tag="clock", why=why, game_path=True),
            IniSet(ini, "clock", "Modules", ",".join(modules), tag="clock", why=why)]
