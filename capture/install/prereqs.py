"""What the machine needs besides the game and the mods. Printed by `capture install` and
`capture verify`; nothing here changes the machine."""
import os
import shutil
import subprocess

from .. import paths
from ..package import ffmpeg_exe
from .components import addon


def check(options=None):
    """[(name, ok, note)]; ok None = optional and absent."""
    out = []
    git = shutil.which("git")
    out.append(("git", bool(git), git or "install Git for Windows"))
    ff = ffmpeg_exe()
    out.append(("ffmpeg (packaging takes into videos)", bool(ff), ff or "winget install Gyan.FFmpeg, or set FFMPEG"))
    cmake = addon.find_cmake()
    out.append(("C++ build tools (to build the capture add-on)", bool(cmake) or None,
                cmake or "not found: needed unless a mods bundle supplies the built add-on "
                         "(Visual Studio Build Tools, 'Desktop development with C++')"))
    sub = os.path.join(paths.REPO, "third_party", "gamecapture-camera-rigs-huixin", "camrigs")
    out.append(("camera-rig repository (for the camrigs rig provider)", os.path.isdir(sub) or None,
                "present" if os.path.isdir(sub) else "optional: git submodule update --init"))
    if (options or {}).get("optiscaler"):
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-CimInstance Win32_VideoController).Name -join '; '"], capture_output=True, text=True)
            gpus = r.stdout.strip()
        except OSError:
            gpus = ""
        out.append(("NVIDIA RTX 50 GPU (DLSS 5)", ("RTX 50" in gpus) or None, gpus or "unknown"))
    return out


def report(options=None, log=print):
    ok = True
    for name, state, note in check(options):
        log("  %-7s %s: %s" % ({True: "ok", False: "MISSING", None: "-"}[state], name, note))
        ok = ok and state is not False
    return ok
