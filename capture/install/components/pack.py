"""A large mod installed as a folder tree straight from its archive, for any game (game-agnostic).

For mods of gigabytes (a world mod's DLC packs: GTA V's NaturalVision Enhanced is 6.5 GB in 110
files). Pinned in the game's lockfile like any mod, with "pack": true, its archive (name, size,
sha256 and "root", the folder inside it that maps onto the game folder) and every file it installs
(path relative to the game folder, size, sha256).

The generic file search (sources.Files) reads whole files into memory and skips archives over
2 GiB, so a pack is found on its own terms, in out/mods and the --mods places (searched all the way
down):
- the archive, by its name and size, exactly as downloaded;
- or a folder already holding the files at their paths (the archive unpacked by hand).
Files are streamed and hashed while copying; a file that does not match its sha256 stops the
install. Checking an installed pack compares every file's size, and the sha256 of files under
64 MiB (hashing gigabytes on every `capture install` would take a minute each time).

Turning a pack off removes exactly its pinned files (by path and size) and the folders it leaves
empty, without a backup: the archive installs it again.
"""
import hashlib
import os
import zipfile

from ...util import sha256_file
from ..plan import InstallError, Step

HASH_BELOW = 64 << 20


def files(mod):
    return mod.get("files", [])


def _installed(game_dir, f):
    p = os.path.join(game_dir, *f["name"].split("/"))
    if not os.path.isfile(p) or os.path.getsize(p) != f["size"]:
        return False
    return f["size"] >= HASH_BELOW or sha256_file(p) == f["sha256"]


class Source:
    """Where a pack's files are: an archive (path, root folder inside it) or a folder."""

    def __init__(self, path, root=None):
        self.path, self.root, self.is_archive = path, root, root is not None

    def open(self, f):
        if self.is_archive:
            z = zipfile.ZipFile(self.path)
            return _Closing(z.open(self.root + f["name"]), z)
        return open(os.path.join(self.path, *f["name"].split("/")), "rb")

    def __str__(self):
        return self.path


class _Closing:
    """A member stream that also closes its archive."""

    def __init__(self, stream, archive):
        self.stream, self.archive = stream, archive

    def read(self, n):
        return self.stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stream.close()
        self.archive.close()


def find_source(mod, roots):
    """The archive (by name and size) or an unpacked folder (every file at its path, right size;
    the small ones hashed) under the given roots, or None."""
    a, fs = mod.get("archive") or {}, files(mod)
    if not fs:
        return None
    marker = fs[0]
    marker_base = os.path.basename(marker["name"]).lower()
    folders = []
    for root in roots:
        if os.path.isfile(root):
            walk = [(os.path.dirname(root), [], [os.path.basename(root)])]
        else:
            walk = os.walk(root)
        for d, dirs, names in walk:
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for n in names:
                p = os.path.join(d, n)
                if a and n == a.get("name") and os.path.getsize(p) == a.get("size"):
                    return Source(p, a.get("root", ""))
                if n.lower() == marker_base:
                    base = d
                    for _ in range(marker["name"].count("/")):
                        base = os.path.dirname(base)
                    folders.append(base)
    for base in folders:
        if all(_installed(base, f) for f in fs):
            return Source(base)
    return None


def _copy(src, f, dst):
    h, tmp = hashlib.sha256(), dst + ".part"
    with src.open(f) as s, open(tmp, "wb") as d:
        while True:
            chunk = s.read(1 << 22)
            if not chunk:
                break
            h.update(chunk)
            d.write(chunk)
    if h.hexdigest() != f["sha256"]:
        os.remove(tmp)
        raise InstallError("%s from %s: sha256 %s, the lockfile pins %s" % (f["name"], src, h.hexdigest(), f["sha256"]))
    if os.path.exists(dst):
        os.remove(dst)
    os.replace(tmp, dst)


class Install(Step):
    needs_game_closed = True

    def __init__(self, mod_id, game_dir, tag):
        self.mod_id, self.game_dir, self.tag = mod_id, game_dir, tag

    def describe(self):
        return "%s: its files into the game folder" % self.mod_id

    def _todo(self, ctx):
        return [f for f in files(ctx.files.mods[self.mod_id]) if not _installed(self.game_dir, f)]

    def status(self, ctx):
        mod = ctx.files.mods[self.mod_id]
        todo = self._todo(ctx)
        if not todo:
            return "ok", "installed (%d files)" % len(files(mod))
        src = find_source(mod, ctx.files.roots)
        if src is None:
            a = mod.get("archive") or {}
            return "missing", "%s (%s bytes) from %s: put it in out/mods or pass --mods  (see docs/MOD_FILES.md)" % (
                a.get("name", self.mod_id), "{:,}".format(a.get("size", 0)), mod.get("page"))
        return "todo", "copy %d files (%.1f GB) from %s" % (len(todo), sum(f["size"] for f in todo) / 1e9, src)

    def apply(self, ctx):
        mod = ctx.files.mods[self.mod_id]
        src = find_source(mod, ctx.files.roots)
        if src is None:
            raise InstallError("no source for %s" % self.mod_id)
        for f in self._todo(ctx):
            dst = os.path.join(self.game_dir, *f["name"].split("/"))
            ctx.record.makedirs(os.path.dirname(dst))
            ctx.record.file(dst, f["sha256"])
            _copy(src, f, dst)


class Remove(Step):
    needs_game_closed = True

    def __init__(self, mod_id, game_dir, tag, why=""):
        self.mod_id, self.game_dir, self.tag, self.why = mod_id, game_dir, tag, why

    def describe(self):
        return "%s: its files out of the game folder%s" % (self.mod_id, "  (%s)" % self.why if self.why else "")

    def _present(self, ctx):
        out = []
        for f in files(ctx.files.mods[self.mod_id]):
            p = os.path.join(self.game_dir, *f["name"].split("/"))
            if os.path.isfile(p) and os.path.getsize(p) == f["size"]:
                out.append(p)
        return out

    def status(self, ctx):
        present = self._present(ctx)
        return ("todo", "remove %d files" % len(present)) if present else ("ok", "absent")

    def apply(self, ctx):
        dirs = set()
        for p in self._present(ctx):
            os.remove(p)
            d = os.path.dirname(p)
            while os.path.normcase(d) != os.path.normcase(self.game_dir) and d.startswith(self.game_dir):
                dirs.add(d)
                d = os.path.dirname(d)
        for d in sorted(dirs, key=len, reverse=True):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        ctx.record.note(kind="removed", what="%s's files (install it again to put them back)" % self.mod_id)


def steps(ctx, game_dir, mod_id, tag):
    return [Install(mod_id, game_dir, tag)]


def not_installed(ctx, game_dir, mod_id, tag, why=""):
    return [Remove(mod_id, game_dir, tag, why)]
