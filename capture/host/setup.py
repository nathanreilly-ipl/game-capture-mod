"""`capture host`: what a Linux machine needs to run a Windows game, besides the game and its mods.

    capture host status            what is there and what is missing
    capture host setup             fetches and unpacks what is missing into out/host (no root needed)
    capture host prefix <game>     makes the game's Proton prefix; prints where its saves and settings go
    capture host stop <game>       ends the game and everything else in its prefix
    capture host steam <game> [--client <zip|folder>] [--keep]
                                   a Steam client in the game's prefix, for games that need one (steam.py)

The parts and where they come from are pinned in linux.lock.json, next to this file: Proton, the
Steam Linux Runtime it runs in, a headless display with its tools (Ubuntu packages, unpacked into a
folder), NVIDIA's NGX DLLs for the machine's driver version, and ffmpeg (from conda-forge, in the
machine's conda environment: proton.env_dir; other ordinary programs go there too). Setup
downloads from their makers' servers; say so to whoever owns the machine before running it. On
Windows there is nothing to set up.

Not done here: the game itself (its Windows files from Steam: docs/LINUX_PORT.md) and the GPU
driver, which the machine must have (NVIDIA, with its Vulkan and NGX libraries visible).
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile

from ..util import read_json, sha256_file
from . import proton

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux.lock.json")


def lock():
    doc = read_json(LOCK)
    if doc.get("schema") != "capture_host_lock/v1":
        raise ValueError("%s is not a capture_host_lock/v1 file" % LOCK)
    return doc["parts"]


def driver_version():
    return proton.driver_version()


def _gpus():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True)
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except OSError:
        return []


def _user_namespaces():
    try:
        return subprocess.run(["unshare", "-Ur", "true"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ffmpeg():
    from ..package import ffmpeg_exe
    return ffmpeg_exe()


def status(log=print):
    """Prints what is there; returns True when a game can be started and a take packaged."""
    t, parts, ok = proton.tools(), lock(), True
    version = driver_version()

    def row(name, good, note, needed=True):
        nonlocal ok
        log("  %-7s %s: %s" % ("ok" if good else ("MISSING" if needed else "-"), name, note))
        ok = ok and (bool(good) or not needed)

    gpus = _gpus()
    row("NVIDIA GPU and driver", bool(gpus and version), "%s; driver %s" % ("; ".join(gpus) or "none seen by nvidia-smi", version))
    if len(gpus) > 1:
        row("one GPU visible", False, "%d are: a game then finds no display modes; start it in a job step with one "
            "(srun --exact --gres=gpu:1 ...)" % len(gpus), needed=False)
    row("unprivileged user namespaces (Proton's container; Xvfb's private /usr/bin)", _user_namespaces(),
        "unshare -Ur works" if _user_namespaces() else "refused: the Steam Linux Runtime cannot start its container here")
    row("Proton", t["proton"], t["proton"] or "wanted: %s" % parts["proton"]["version"])
    row("Steam Linux Runtime", t["runtime"], t["runtime"] or "wanted: %s" % parts["runtime"]["version"])
    for prog in parts["packages"]["programs"]:
        if prog == "xkbcomp" and os.path.exists("/usr/bin/xkbcomp"):
            continue
        row(prog, proton.tool(prog), proton.tool(prog) or "neither installed nor in out/host/sysroot")
    want_ngx = os.path.join(proton.host_dir(), "nvidia", version or "?")
    have = t["ngx"] and os.path.basename(t["ngx"]) == version
    row("NVIDIA NGX DLLs for driver %s (DLSS under Proton)" % version, have,
        t["ngx"] if have else "wanted in %s%s" % (want_ngx, " (found for another driver: %s)" % t["ngx"] if t["ngx"] else ""))
    row("32-bit Windows programs (wow64/tls32.c, for a Steam client in a prefix)", proton.tls32(),
        proton.tls32() or "not built (host setup builds it where there is a C compiler)", needed=False)
    row("ffmpeg (packaging takes into videos)", _ffmpeg(), _ffmpeg() or "none installed, none in the conda environment %s" % proton.env_dir())
    alive = proton.display_alive() if proton.tool("xdotool") else False
    row("headless display %s (%s)" % (t["display"], t["screen"]), alive, "up" if alive else "not running; started with the game", needed=False)
    log("%s  (%s)" % ("ready: games can be started here" if ok else "not ready: run `%s host setup`" % proton.CLI, proton.host_dir()))
    return ok


def _fetch(part, name, log, version=None):
    """Downloads a part's archive into out/host/downloads (once), checking its pinned sha256."""
    from ..install.sources import _download
    url = part["url"].format(version=version) if version else part["url"]
    dst = os.path.join(proton.host_dir(), "downloads", name)
    pin = part.get("sha256")
    if isinstance(pin, dict):
        pin = pin.get(version)
    if os.path.exists(dst) and (not pin or sha256_file(dst) == pin):
        return dst
    got = _download(url, dst, pin, part.get("size"), log)
    if not pin:
        log("  %s is not pinned (its address serves the current build): sha256 %s" % (name, got))
    return dst


def _unpack(archive, into, log):
    os.makedirs(into, exist_ok=True)
    log("  unpacking %s into %s" % (os.path.basename(archive), into))
    r = subprocess.run(["tar", "-xf", archive, "-C", into], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("tar could not unpack %s: %s" % (archive, r.stderr[-500:]))


def _setup_packages(part, log):
    need = [p for p in part["programs"] if not proton.tool(p) and not (p == "xkbcomp" and os.path.exists("/usr/bin/xkbcomp"))]
    if not need:
        return
    if not shutil.which("apt-get") or not shutil.which("dpkg"):
        raise RuntimeError("%s not found and this is not a Debian/Ubuntu machine: install Xvfb and xdotool" % ", ".join(need))
    debs = os.path.join(proton.host_dir(), "downloads", "debs")
    os.makedirs(debs, exist_ok=True)
    log("  apt-get download %s" % " ".join(part["apt"]))
    r = subprocess.run(["apt-get", "download"] + part["apt"], cwd=debs, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("apt-get download failed: %s" % r.stderr[-500:])
    sysroot = os.path.join(proton.host_dir(), "sysroot")
    os.makedirs(sysroot, exist_ok=True)
    for deb in sorted(glob.glob(os.path.join(debs, "*.deb"))):
        subprocess.run(["dpkg", "-x", deb, sysroot], check=True)
    log("  unpacked %d packages into %s" % (len(glob.glob(os.path.join(debs, "*.deb"))), sysroot))


def _setup_ngx(part, log):
    version = driver_version()
    if not version:
        raise RuntimeError("no NVIDIA driver found (nvidia-smi, /proc/driver/nvidia/version)")
    dst = os.path.join(proton.host_dir(), "nvidia", version)
    if all(os.path.exists(os.path.join(dst, n)) for n in part["files"]):
        return
    os.makedirs(dst, exist_ok=True)
    for d in part["installed_in"]:      # a machine with the driver's Wine files installed needs no download
        if all(os.path.exists(os.path.join(d, n)) for n in part["files"]):
            for n in part["files"]:
                shutil.copyfile(os.path.join(d, n), os.path.join(dst, n))
            log("  copied %s from %s" % (", ".join(part["files"]), d))
            return
    run_file = _fetch(part, "NVIDIA-Linux-x86_64-%s.run" % version, log, version=version)
    tmp = tempfile.mkdtemp(prefix="nvidia_", dir=os.path.join(proton.host_dir(), "downloads"))
    try:
        target = os.path.join(tmp, "x")
        log("  unpacking %s (nothing is installed)" % os.path.basename(run_file))
        r = subprocess.run(["sh", run_file, "--extract-only", "--target", target], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("could not unpack %s: %s" % (run_file, (r.stdout + r.stderr)[-500:]))
        for n in part["files"]:
            shutil.copyfile(os.path.join(target, n), os.path.join(dst, n))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log("  %s in %s" % (", ".join(part["files"]), dst))


def _setup_conda(part, log):
    """Ordinary programs (ffmpeg) go from conda-forge into one conda environment (proton.env_dir),
    made here if it is not there. Nothing is done when the programs are already found."""
    if all(_ffmpeg() if prog == "ffmpeg" else proton.tool(prog) for prog in part["programs"]):
        return
    conda = next((shutil.which(n) for n in ("micromamba", "mamba", "conda") if shutil.which(n)), None)
    env = proton.env_dir()
    if not conda:
        raise RuntimeError("no micromamba, mamba or conda here to install %s into %s: install one, or "
                           "put the programs on PATH (ffmpeg: or set FFMPEG)" % (", ".join(part["packages"]), env))
    verb = "install" if os.path.isdir(os.path.join(env, "conda-meta")) else "create"
    log("%s:\n  %s %s -p %s -c %s %s" % (part["title"], os.path.basename(conda), verb, env, part["channel"], " ".join(part["packages"])))
    r = subprocess.run([conda, verb, "-y", "-p", env, "--override-channels", "-c", part["channel"]] + part["packages"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("%s %s failed: %s" % (os.path.basename(conda), verb, (r.stdout + r.stderr)[-800:]))
    log("  %s in %s" % (", ".join(part["programs"]), os.path.join(env, "bin")))


def _tls32_source():
    return os.path.join(proton.WOW64_DIR, "tls32.c")


def _setup_tls32(log):
    """Builds wow64/tls32.c (32-bit Windows programs where 32-bit system calls are forbidden) into
    out/host/lib with the machine's C compiler; rebuilt when the source is newer."""
    dst = os.path.join(proton.host_dir(), "lib", "tls32.so")
    src = _tls32_source()
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        log("  no C compiler here: %s is not built (only 32-bit Windows programs need it: a Steam client's service)" % dst)
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run([cc, "-O2", "-fPIC", "-shared", "-o", dst, src, "-ldl"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("could not build %s: %s" % (src, r.stderr[-800:]))
    log("  built %s" % dst)


def setup(log=print):
    """Fetches and unpacks what is missing. Returns status()."""
    parts = lock()
    host = proton.host_dir()
    for key in ("proton", "runtime"):
        if not os.path.exists(os.path.join(host, parts[key]["has"])):
            log("%s:" % parts[key]["title"])
            _unpack(_fetch(parts[key], parts[key]["name"], log), os.path.join(host, parts[key]["into"]), log)
    for key, fn in (("packages", _setup_packages), ("ngx", _setup_ngx), ("conda", _setup_conda)):
        fn(parts[key], lambda m, key=key: log(m))
    _setup_tls32(log)
    return status(log)


def prefix(game, log=print):
    """Makes the game's prefix (with what DLSS needs) and says where the game user's files go."""
    from .. import adapters_registry  # noqa: F401  (the game's name is checked by its installer below)
    from ..install import installer
    mod = installer(game)
    proton.ensure_prefix(game, getattr(mod, "STEAM_APP", None))
    log("prefix of %s: %s" % (game, proton.prefix(game)))
    for kind in ("saved_games", "local_appdata", "documents"):
        log("  %-14s %s" % (kind, proton.user_dir(game, kind)))


def main(action, game=None, log=print, client=None, keep=False):
    if os.name == "nt":
        log("nothing to set up on Windows: the game runs as it is")
        return True
    if action == "status":
        return status(log)
    if action == "setup":
        return setup(log)
    if not game:
        raise SystemExit("capture host %s <game>" % action)
    if action == "steam":
        from . import steam
        return steam.main(game, client, keep, log)
    if action == "prefix":
        prefix(game, log)
    elif action == "stop":
        from ..install import installer
        proton.stop(game, [installer(game).EXE])
        log("stopped %s" % game)
    return True
