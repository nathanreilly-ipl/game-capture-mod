"""`capture host steam <game>`: a Steam client inside the game's prefix, for games that only start
through one (Rockstar's launcher checks the Steam copy's ownership with it; without a client it
offers BUY NOW). On Windows there is nothing to do: Steam is installed there.

    capture host steam <game> --client <zip|folder>   the Windows client's files into the prefix
    capture host steam <game>                          its service, and the game in its library
    capture host steam <game> --keep                   starts the client and keeps it running

The Linux Steam client is a 32-bit program, and so is a helper service of the 64-bit Windows one;
where 32-bit system calls are forbidden neither starts without wow64/tls32.c (`capture host setup`
builds it). The client's files come from a Windows machine's Steam folder (without steamapps,
userdata, config: no games, no account): Valve's installer is a 32-bit program too and its client
repairs itself from its `package` folder on first start. The game's files are not downloaded by
this client: the folder they were downloaded to is linked into its library, with an app manifest
written from the game's `STEAM` facts (adapters/<game>/install.py), so it sees the game installed.

The owner signs in once, in the client's window on the game's display (a remote view of it:
README); the login is remembered in the prefix. `--keep` belongs in a job step with one GPU: the
client and every game it starts run there.
"""
import os
import shutil
import time
import zipfile

from . import proton

SERVICE = "Steam Client Service"


def _steam_dir(game):
    return os.path.join(proton.drive_c(game), *proton.STEAM_PARTS)


def unpack_client(game, source, log=print):
    """The Windows client's folder (a zip holding Steam/..., or the folder itself) into the prefix."""
    dst = _steam_dir(game)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(source):
        shutil.copytree(source, dst, dirs_exist_ok=True)
    else:
        with zipfile.ZipFile(source) as z:
            top = {n.split("/", 1)[0] for n in z.namelist()}
            if top != {"Steam"}:
                raise proton.HostError("%s does not hold one folder named Steam" % source)
            z.extractall(os.path.dirname(dst))
    log("Steam client files in %s" % dst)


def _service_installed(game):
    try:
        text = open(os.path.join(proton.prefix(game), "pfx", "system.reg"), encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return ("\\\\Services\\\\%s]" % SERVICE).lower() in text.lower()


def install_service(game, log=print):
    if _service_installed(game):
        return
    exe = os.path.join(_steam_dir(game), "bin", "SteamService.exe")
    r = proton.wine_direct(game, "C:\\Program Files (x86)\\Steam\\bin\\SteamService.exe", "/Install", cwd=os.path.dirname(exe))
    if r.returncode != 0:
        raise proton.HostError("Steam's service did not install:\n%s" % (r.stdout + r.stderr)[-1200:])
    log("installed Steam's service (bin\\SteamService.exe /Install)")


def _vdf(d, depth=0):
    pad = "\t" * depth
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out += ['%s"%s"' % (pad, k), pad + "{"] + _vdf(v, depth + 1) + [pad + "}"]
        else:
            out.append('%s"%s"\t\t"%s"' % (pad, k, v))
    return out


def register_game(game, game_dir, facts, log=print):
    """Links the downloaded game folder into the client's library and writes its app manifest.
    facts: {"app", "name", "installdir", "buildid", "size", "depots": {id: (manifest, size)},
    "scripts": {depot: file}, "shared": {depot: app}}."""
    apps = os.path.join(_steam_dir(game), "steamapps")
    common = os.path.join(apps, "common")
    os.makedirs(common, exist_ok=True)
    link = os.path.join(common, facts["installdir"])
    if not os.path.lexists(link):
        os.symlink(os.path.realpath(game_dir), link)
        log("linked %s -> %s" % (link, os.path.realpath(game_dir)))
    acf = os.path.join(apps, "appmanifest_%s.acf" % facts["app"])
    if not os.path.exists(acf):
        state = {"appid": facts["app"], "Universe": "1", "name": facts["name"], "StateFlags": "4",
                 "installdir": facts["installdir"], "LastUpdated": str(int(time.time())), "SizeOnDisk": str(facts["size"]),
                 "StagingSize": "0", "buildid": str(facts["buildid"]), "LastOwner": "0", "UpdateResult": "0",
                 "BytesToDownload": "0", "BytesDownloaded": "0", "BytesToStage": "0", "BytesStaged": "0",
                 "TargetBuildID": str(facts["buildid"]),
                 "AutoUpdateBehavior": "1",     # update only when the game is started: an update breaks the script layer
                 "AllowOtherDownloadsWhileRunning": "0", "ScheduledAutoUpdate": "0",
                 "InstalledDepots": {d: {"manifest": m, "size": str(s)} for d, (m, s) in facts["depots"].items()},
                 "InstallScripts": dict(facts.get("scripts") or {})}
        if facts.get("shared"):
            state["SharedDepots"] = dict(facts["shared"])
        state["UserConfig"] = {"language": "english"}
        state["MountedConfig"] = {"language": "english"}
        with open(acf, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(_vdf({"AppState": state})) + "\n")
        log("wrote %s (build %s)" % (acf, facts["buildid"]))
    # the library index: every app with a manifest here
    listed = {}
    for name in sorted(os.listdir(apps)):
        if name.startswith("appmanifest_") and name.endswith(".acf"):
            text = open(os.path.join(apps, name), encoding="utf-8", errors="replace").read()
            size = text.split('"SizeOnDisk"', 1)[1].split('"')[1] if '"SizeOnDisk"' in text else "0"
            listed[name[len("appmanifest_"):-4]] = size
    lib = os.path.join(apps, "libraryfolders.vdf")
    text = open(lib, encoding="utf-8", errors="replace").read() if os.path.exists(lib) else ""
    if "Program Files (x86)" not in text or any('"%s"' % a not in text for a in listed):
        with open(lib, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(_vdf({"libraryfolders": {"0": {"path": "C:\\\\Program Files (x86)\\\\Steam", "label": "",
                                                               "apps": listed}}})) + "\n")
        log("library index %s lists %s" % (lib, ", ".join(listed)))


def keep(game, log=print):
    """Starts the client and keeps it running; it has ended by itself after a game it had started
    was killed ("BMainLoop appears to have stalled", 2026-11-23)."""
    while True:
        if not proton.steam_running(game):
            try:
                proton.start_steam(game)
                log("%s the Steam client is up (its sign-in window, if it shows one, is on display %s)" % (
                    time.strftime("%H:%M:%S"), proton.tools()["display"]))
            except proton.HostError as e:
                log("%s the Steam client did not start: %s" % (time.strftime("%H:%M:%S"), e))
        time.sleep(15)


def main(game, client=None, keep_running=False, log=print):
    from ..install import installer
    mod = installer(game)
    facts = getattr(mod, "STEAM", None)
    if client:
        unpack_client(game, client, log)
    if not proton.steam_exe(game):
        raise proton.HostError("no Steam client in %s yet: capture host steam %s --client <the Windows client's folder or zip>" % (
            _steam_dir(game), game))
    install_service(game, log)
    if facts:
        game_dir = mod.find_game_dir()
        if not game_dir:
            raise proton.HostError("%s's files were not found (download them first: README)" % game)
        register_game(game, game_dir, facts, log)
    if keep_running:
        keep(game, log)
    else:
        log("next: %s host steam %s --keep, in a job step with one GPU; the owner signs in once in its window" % (proton.CLI, game))
    return True
