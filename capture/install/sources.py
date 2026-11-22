"""Where mod files come from.

Lockfiles (committed) pin every third-party file an install needs: its version, size and sha256,
where to get it, its licence and whether it may be redistributed.
    capture/install/mods.lock.json     game-agnostic mods (ReShade, OptiScaler, the NVIDIA DLL)
    adapters/<game>/mods.lock.json     the game's own mods

The files themselves are never committed. They are found, by hash, in:
    the folders, archives or bundles given with --mods
    out/mods/ (drop files or archives here; `capture mods fetch` downloads into it)
Archives are searched inside as downloaded (.zip, and .exe files that are zip archives, like
ReShade's setup), so nothing has to be unpacked or renamed. A file pinned by name only (sha256
null, e.g. a DLL whose version is yours to choose) is matched by its file name.

A bundle (`capture mods bundle`) is a zip of exactly the pinned files plus a manifest; it is just
another place to look, checked against the lockfiles like any other.
"""
import json
import os
import zipfile

from .. import paths
from ..util import now_iso, read_json, sha256_bytes, sha256_file

SHARED_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mods.lock.json")
MODS_DIR = os.path.join(paths.OUT, "mods")
DOCS_PAGE = "docs/MOD_FILES.md"


def load_locks(*lock_paths):
    """mod id -> entry, from several lockfiles (later files may not redefine an id)."""
    mods = {}
    for p in lock_paths:
        doc = read_json(p)
        if doc.get("schema") != "capture_mods_lock/v1":
            raise ValueError("%s is not a capture_mods_lock/v1 file" % p)
        for mod_id, entry in doc["mods"].items():
            if mod_id in mods:
                raise ValueError("mod %s is pinned twice" % mod_id)
            mods[mod_id] = dict(entry, lock=os.path.relpath(p, paths.REPO).replace(os.sep, "/"))
    return mods


def _unpacked(archive, size):
    """The files of a RAR archive, unpacked once into out/mods/.unpacked with Windows' own tar
    (libarchive reads RAR); [] if it cannot be read."""
    import subprocess
    dst = os.path.join(MODS_DIR, ".unpacked", "%s-%d" % (os.path.basename(archive), size))
    if not os.path.isdir(dst):
        tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        os.makedirs(dst + ".part", exist_ok=True)
        if subprocess.run([tar, "-xf", archive, "-C", dst + ".part"], capture_output=True).returncode != 0:
            return []
        os.replace(dst + ".part", dst)
    return [os.path.join(d, n) for d, _, names in os.walk(dst) for n in names]


class Located:
    """One found file: on disk, or a member of an archive."""

    def __init__(self, path, member=None):
        self.path, self.member = path, member

    @property
    def where(self):
        return "%s!%s" % (self.path, self.member) if self.member else self.path

    def read(self):
        if self.member:
            with zipfile.ZipFile(self.path) as z:
                return z.read(self.member)
        with open(self.path, "rb") as f:
            return f.read()


class FileRef:
    """A pinned file and where (if anywhere) it was found."""

    def __init__(self, mod_id, mod, spec, located):
        self.mod_id, self.mod, self.spec, self.located = mod_id, mod, spec, located
        self.label = "%s (%s)" % (spec["name"], mod.get("title", mod_id))

    @property
    def found(self):
        return self.located is not None

    @property
    def sha256(self):
        return self.spec.get("sha256")

    @property
    def where(self):
        return self.located.where if self.located else None

    @property
    def content_sha256(self):
        """The pinned sha256, or for a file pinned by name only, the found file's own."""
        if self.sha256 or not self.found:
            return self.sha256
        if not hasattr(self, "_content_sha256"):
            self._content_sha256 = sha256_bytes(self.read())
        return self._content_sha256

    def read(self):
        return self.located.read()

    @property
    def missing_note(self):
        return "%s, from %s: %s  (see %s)" % (self.spec["name"], self.mod.get("title", self.mod_id),
                                               self.mod.get("page") or self.mod.get("archive", {}).get("url", "?"), DOCS_PAGE)


class Files:
    """Finds the pinned files of the given mods in the search roots."""

    def __init__(self, mods, roots=(), installed=(), extra_names=()):
        """roots: folders, archives or bundles. installed: folders to look in without recursion
        (an existing install is also a source, e.g. for making a bundle). extra_names: file names
        to find that no lockfile pins (our own built files in a bundle)."""
        self.mods = mods
        self.roots = [r for r in list(roots) + [MODS_DIR] if r and os.path.exists(r)]
        self.installed = [d for d in installed if d and os.path.isdir(d)]
        self._by_hash, self._by_name, self._scanned = {}, {}, False
        self._sizes, self._hashes, self._names = set(), set(), {n.lower() for n in extra_names}
        for mod in mods.values():
            if mod.get("pack"):     # gigabytes in a folder tree: found by components/pack.py instead
                continue
            for f in mod.get("files", []):
                if f.get("sha256"):
                    self._sizes.add(f["size"])
                    self._hashes.add(f["sha256"])
                else:
                    self._names.add(f["name"].lower())

    def _consider(self, name, size, read, located):
        if size in self._sizes:
            h = sha256_bytes(read())
            if h in self._hashes:
                self._by_hash.setdefault(h, located)
        if os.path.basename(name).lower() in self._names:
            self._by_name.setdefault(os.path.basename(name).lower(), located)

    def _scan_file(self, p):
        try:
            size = os.path.getsize(p)
        except OSError:
            return
        self._consider(p, size, lambda: open(p, "rb").read(), Located(p))
        if p.lower().endswith(".rar"):
            for f in _unpacked(p, size):
                self._consider(f, os.path.getsize(f), lambda f=f: open(f, "rb").read(), Located(f))
            return
        if p.lower().endswith((".zip", ".exe")) and size < (2 << 30):
            try:
                if not zipfile.is_zipfile(p):
                    return
                with zipfile.ZipFile(p) as z:
                    for info in z.infolist():
                        if not info.is_dir():
                            self._consider(info.filename, info.file_size, lambda i=info: z.read(i), Located(p, info.filename))
            except (zipfile.BadZipFile, OSError, NotImplementedError):
                pass

    def _scan(self):
        if self._scanned:
            return
        self._scanned = True
        for root in self.roots:
            if os.path.isfile(root):
                self._scan_file(root)
                continue
            base = root.rstrip("\\/").count(os.sep)
            for d, dirs, names in os.walk(root):
                if d.count(os.sep) - base >= 3:
                    dirs[:] = []
                for n in names:
                    self._scan_file(os.path.join(d, n))
        for d in self.installed:
            for n in os.listdir(d):
                p = os.path.join(d, n)
                if os.path.isfile(p) and not p.lower().endswith((".zip", ".exe")):
                    self._consider(p, os.path.getsize(p), lambda p=p: open(p, "rb").read(), Located(p))

    def rescan(self):
        """Look again (after files were added, e.g. downloaded)."""
        self._by_hash, self._by_name, self._scanned = {}, {}, False

    def ref(self, mod_id, name):
        self._scan()
        mod = self.mods[mod_id]
        spec = next((f for f in mod.get("files", []) if f["name"] == name), None)
        if spec is None:
            raise KeyError("%s has no pinned file %s" % (mod_id, name))
        located = self._by_hash.get(spec["sha256"]) if spec.get("sha256") else self._by_name.get(name.lower())
        return FileRef(mod_id, mod, spec, located)

    def named(self, name):
        """A file found by name alone (one of extra_names), or None."""
        self._scan()
        return self._by_name.get(name.lower())

    def refs(self, mod_id):
        return [self.ref(mod_id, f["name"]) for f in self.mods[mod_id].get("files", [])]

    def status(self):
        """[(mod id, mod, [(FileRef)])] for every pinned mod but packs (see packs())."""
        return [(mod_id, mod, self.refs(mod_id)) for mod_id, mod in self.mods.items() if not mod.get("pack")]

    def packs(self):
        """[(mod id, mod)] of the pinned packs: large mods installed from their archive
        (components/pack.py), never searched file by file, fetched or bundled."""
        return [(mod_id, mod) for mod_id, mod in self.mods.items() if mod.get("pack")]


def _download(url, dst, sha256=None, size=None, log=print):
    import urllib.request
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    log("  downloading %s%s" % (url, " (%.1f MB)" % (size / 1e6) if size and size > 1e6 else ""))
    tmp = dst + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "capture-install"})) as r, \
            open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    got = sha256_file(tmp)
    if sha256 and got != sha256:
        os.remove(tmp)
        raise RuntimeError("%s: sha256 %s, the lockfile pins %s" % (url, got, sha256))
    os.replace(tmp, dst)
    return got


def fetch(files, log=print):
    """Downloads into out/mods what may be downloaded and is not found yet (in the --mods places,
    out/mods or the existing install), checking every sha256: a pinned archive with a URL, or
    each file that has its own URL. Files that must be supplied by hand are listed with where
    to get them."""
    for mod_id, mod, refs in files.status():
        if refs and all(r.found for r in refs):
            log("%-18s have it" % mod_id)
            continue
        if mod.get("source") != "download":
            log("%-18s supply it yourself: %s" % (mod_id, mod.get("page")))
            continue
        a = mod.get("archive")
        if a and a.get("url"):
            dst = os.path.join(MODS_DIR, a["name"])
            if not (os.path.exists(dst) and a.get("sha256") and sha256_file(dst) == a["sha256"]):
                _download(a["url"], dst, a.get("sha256"), a.get("size"), log)
            log("%-18s saved %s" % (mod_id, dst))
            continue
        for r in refs:
            if not r.found and r.spec.get("url"):
                dst = os.path.join(MODS_DIR, mod_id, r.spec["name"])
                _download(r.spec["url"], dst, r.spec.get("sha256"), r.spec.get("size"), log)
        log("%-18s saved into %s" % (mod_id, os.path.join(MODS_DIR, mod_id)))
    for mod_id, mod in files.packs():
        log("%-18s supply it yourself: %s (%s)" % (mod_id, mod.get("page"), mod.get("archive", {}).get("name")))
    files.rescan()


def bundle(files, out_path, with_supplied=False, extra=(), log=print):
    """A zip of the pinned files that were found (files/<mod id>/<name>) and a manifest. Files that
    may not be redistributed are left out unless with_supplied (for moving between your own
    machines only). extra: [(archive name, path)] of our own built files."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    manifest = {"schema": "capture_mods_bundle/v1", "made": now_iso(), "with_supplied": with_supplied, "mods": {}}
    skipped, missing = [], []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for mod_id, mod, refs in files.status():
            if not mod.get("redistributable") and not with_supplied:
                skipped.append(mod_id)
                continue
            got = []
            for ref in refs:
                if not ref.found:
                    missing.append("%s/%s" % (mod_id, ref.spec["name"]))
                    continue
                data = ref.read()
                z.writestr("files/%s/%s" % (mod_id, ref.spec["name"]), data)
                got.append({"name": ref.spec["name"], "sha256": sha256_bytes(data), "size": len(data)})
            manifest["mods"][mod_id] = {"title": mod.get("title"), "version": mod.get("version"),
                                        "licence": mod.get("licence"), "redistributable": bool(mod.get("redistributable")),
                                        "files": got}
        for name, path in extra:
            z.write(path, "files/%s" % name)
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
    log("bundle %s (%.1f MB): %d mods%s%s" % (
        out_path, os.path.getsize(out_path) / 1e6, len(manifest["mods"]),
        "; left out (not redistributable, use --with-supplied for your own machines): " + ", ".join(skipped) if skipped else "",
        "; NOT FOUND: " + ", ".join(missing) if missing else ""))
    if with_supplied:
        log("this bundle holds files that may not be redistributed: keep it on your own machines, never in git")
    return manifest
