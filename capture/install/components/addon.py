"""Our frame-capture ReShade add-on (addons/capture), for any game (game-agnostic).

It is built from source when the machine has the C++ build tools (Visual Studio or Build Tools
with "Desktop development with C++", which includes CMake). Without them, a prebuilt add-on from
a mods bundle is used, if it was built from exactly these sources.
"""
import os
import shutil
import subprocess

from ... import paths
from ...util import sha256_bytes
from ..plan import Call, CopyFile, InstallError, IniSet

ADDON_SRC = os.path.join(paths.REPO, "addons", "capture")
BUILD_DIR = os.path.join(paths.REPO, "addons", "build")
RESHADE_HEADERS = os.path.join(paths.REPO, "addons", "deps", "reshade")
RESHADE_TAG = "v6.8.0"  # the add-on API version; match the pinned ReShade
NAME = "capture_mod.addon64"
STAMP = "capture_mod.src.sha256"
BUILT = os.path.join(BUILD_DIR, "Release", NAME)
BUILT_STAMP = os.path.join(BUILD_DIR, STAMP)
EXTRA_NAMES = (NAME, STAMP)


def source_digest():
    parts = []
    for d, _, names in os.walk(ADDON_SRC):
        for n in sorted(names):
            p = os.path.join(d, n)
            parts.append(os.path.relpath(p, ADDON_SRC).replace(os.sep, "/").encode() + b"\0" + open(p, "rb").read())
    return sha256_bytes(b"\0".join(sorted(parts)) + RESHADE_TAG.encode())


def find_cmake():
    exe = shutil.which("cmake")
    if exe:
        return exe
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.exists(vswhere):
        r = subprocess.run([vswhere, "-latest", "-products", "*", "-requires",
                            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                           capture_output=True, text=True)
        cand = os.path.join(r.stdout.strip(), "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake", "bin", "cmake.exe")
        if r.stdout.strip() and os.path.exists(cand):
            return cand
    return None


def is_built():
    return os.path.exists(BUILT) and os.path.exists(BUILT_STAMP) and open(BUILT_STAMP).read().strip() == source_digest()


def build(log=print):
    cmake = find_cmake()
    if not cmake:
        raise InstallError("no C++ build tools: install Visual Studio Build Tools with 'Desktop development with C++'")
    if not os.path.exists(os.path.join(RESHADE_HEADERS, "include", "reshade.hpp")):
        log("  fetching ReShade %s headers (git clone) into %s" % (RESHADE_TAG, RESHADE_HEADERS))
        os.makedirs(os.path.dirname(RESHADE_HEADERS), exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", RESHADE_TAG, "https://github.com/crosire/reshade.git",
                        RESHADE_HEADERS], check=True)
    cache = os.path.join(BUILD_DIR, "CMakeCache.txt")
    if os.path.exists(cache) and ADDON_SRC.replace("\\", "/").lower() not in open(cache, errors="replace").read().lower():
        shutil.rmtree(BUILD_DIR)  # configured for another source folder
    for args in (["-S", ADDON_SRC, "-B", BUILD_DIR, "-A", "x64"], ["--build", BUILD_DIR, "--config", "Release"]):
        r = subprocess.run([cmake] + args, capture_output=True, text=True)
        if r.returncode != 0:
            raise InstallError("building the add-on failed:\n" + (r.stdout + r.stderr)[-2000:])
    with open(BUILT_STAMP, "w") as f:
        f.write(source_digest())
    log("  built %s" % BUILT)


def _prebuilt(ctx):
    """A prebuilt add-on from the mods folders or a bundle, if built from these sources."""
    a, s = ctx.files.named(NAME), ctx.files.named(STAMP)
    if a and s and s.read().decode("ascii", "replace").strip() == source_digest():
        cache = os.path.join(ctx.record.dir, "prebuilt", NAME)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(a.read())
        return cache, a.where
    return None, None


def steps(ctx, game_dir, output_dir):
    state = {}

    def usable():
        if is_built():
            return BUILT
        if "prebuilt" not in state:
            state["prebuilt"] = _prebuilt(ctx)
        return state["prebuilt"][0]

    def build_status(c):
        if is_built():
            return "ok", "built"
        if usable():
            return "ok", "prebuilt from %s" % state["prebuilt"][1]
        if find_cmake():
            return "todo", "build with CMake"
        return "missing", ("the capture add-on cannot be built here: install Visual Studio Build Tools with 'Desktop "
                           "development with C++', or use a mods bundle that includes the add-on")

    return [Call("capture add-on built from addons/capture", build_status, lambda c: build(c.log), tag="addon"),
            CopyFile(usable, os.path.join(game_dir, NAME), tag="addon", what="capture add-on"),
            IniSet(os.path.join(game_dir, "ReShade.ini"), "CAPTURE_MOD", "OutputDir", output_dir, tag="addon",
                   why="where the add-on exchanges files with the scripts")]
