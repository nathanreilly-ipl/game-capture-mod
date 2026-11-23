"""Our frame-capture ReShade add-on (addons/capture), for any game (game-agnostic).

It is built from source when the machine has the C++ build tools (Visual Studio or Build Tools
with "Desktop development with C++", which includes CMake). Without them (any Linux machine: the
add-on is a Windows DLL that runs inside the game under Proton), a prebuilt add-on from a mods
bundle is used, if it was built from exactly these sources (`capture mods bundle` on a machine
that built it puts the file and its stamp in). prebuilt() does that for the clock plug-in too.
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


def digest_of(src_dir, tag=b""):
    """One hash over a source folder, the same on every checkout: line ends are taken as LF
    (git on Windows may check the same file out with CRLF in one worktree and LF in another,
    which made a build look stale, 2026-11-23)."""
    parts = []
    for d, _, names in os.walk(src_dir):
        for n in sorted(names):
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n")
            parts.append(os.path.relpath(p, src_dir).replace(os.sep, "/").encode() + b"\0" + data)
    return sha256_bytes(b"\0".join(sorted(parts)) + tag)


def source_digest():
    return digest_of(ADDON_SRC, RESHADE_TAG.encode())


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


def prebuilt(ctx, name, stamp, digest):
    """(path of a copy, where it was found) of one of our own built files from the mods folders or
    a bundle, if its stamp says it was built from the sources with this digest; else (None, None)."""
    a, s = ctx.files.named(name), ctx.files.named(stamp)
    if a and s and s.read().decode("ascii", "replace").strip() == digest:
        cache = os.path.join(ctx.record.dir, "prebuilt", name)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            f.write(a.read())
        return cache, a.where
    return None, None


def no_build_note(what):
    if os.name == "nt":
        return ("%s cannot be built here: install Visual Studio Build Tools with 'Desktop development with C++', "
                "or use a mods bundle that includes it" % what)
    return ("%s is a Windows DLL, built on a Windows machine: pass --mods a bundle made there by `capture mods bundle` "
            "(it carries the built file and its stamp), from the same sources as this checkout" % what)


def _prebuilt(ctx):
    return prebuilt(ctx, NAME, STAMP, source_digest())


def steps(ctx, game_dir, output_dir, config_dir=None):
    """config_dir: where ReShade keeps its config for this game (reshade.steps' config_dir)."""
    from .reshade import config_path
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
        return "missing", no_build_note("the capture add-on")

    out = [Call("capture add-on built from addons/capture", build_status, lambda c: build(c.log), tag="addon"),
           CopyFile(usable, os.path.join(game_dir, NAME), tag="addon", what="capture add-on"),
           IniSet(config_path(game_dir, config_dir), "CAPTURE_MOD", "OutputDir", output_dir, tag="addon",
                  why="where the add-on exchanges files with the scripts", game_path=True)]
    if config_dir:
        # ReShade looks for add-ons in its base folder, which is config_dir then
        out.append(IniSet(config_path(game_dir, config_dir), "ADDON", "AddonPath", game_dir, tag="addon",
                          why="the add-on stays in the game folder; ReShade's base folder is elsewhere", game_path=True))
    return out
