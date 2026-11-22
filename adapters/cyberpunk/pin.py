"""Pins every file of a mod's archive in the Cyberpunk lockfile (mods.lock.json), for mods that are
installed as their archive lays them out (a tree under the game folder: bin/x64/..., red4ext/...,
r6/..., archive/pc/mod/...). Run after the archive is in out/mods, when a mod is added or updated:

    uv run --project . python -m adapters.cyberpunk.pin <mod id> <archive in out/mods or a path>

The lockfile entry must exist already (title, version, source, page, licence, and for a download
its archive name, url, size and sha256). An archive whose sha256 differs from the entry is refused.
"""
import hashlib
import json
import os
import sys
import zipfile

from capture.install import sources

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mods.lock.json")


def find(name):
    if os.path.exists(name):
        return name
    for d, _, names in os.walk(sources.MODS_DIR):
        if name in names:
            return os.path.join(d, name)
    raise FileNotFoundError("%s is not in %s" % (name, sources.MODS_DIR))


def pin(mod_id, archive):
    with open(LOCK, encoding="utf-8") as f:
        doc = json.load(f)
    entry = doc["mods"][mod_id]
    path = find(archive)
    data = open(path, "rb").read()
    digest = hashlib.sha256(data).hexdigest()
    a = entry.setdefault("archive", {"name": os.path.basename(path)})
    if a.get("sha256") and a["sha256"] != digest:
        raise ValueError("%s has sha256 %s, the lockfile pins %s" % (path, digest, a["sha256"]))
    a.update(size=len(data), sha256=digest)
    files = []
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            if not i.is_dir():
                b = z.read(i)
                files.append({"name": i.filename, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    entry["files"] = files
    with open(LOCK, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=4)
        f.write("\n")
    return files


if __name__ == "__main__":
    for spec in pin(sys.argv[1], sys.argv[2]):
        print("%10d  %s" % (spec["size"], spec["name"]))
