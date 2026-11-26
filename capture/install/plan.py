"""Install steps: each says whether it is already satisfied, applies itself, and records what
it changed so `capture uninstall` can put things back.

A step has a tag (mods, reshade, addon, scripts, settings, optiscaler) so parts of an install can
be run alone (`capture install <game> --only scripts`). Steps that write files the running game
holds open say needs_game_closed.

The install record (out/install/<game>/installed.json) lists every file written (with a backup
of what it replaced), every setting changed (with its old value) and every folder created.
"""
import json
import os
import re
import shutil
import subprocess

from ..util import now_iso, read_json, sha256_bytes, sha256_file, write_json


class InstallError(RuntimeError):
    pass


# --- the machine ---------------------------------------------------------------------------------
class System:
    """What an install touches outside the game folder, on Windows. Tests replace it; under Proton
    it is ProtonSystem (default_system picks)."""
    game = None     # the game being installed (install.context sets it)
    wine = False    # True where the game runs under Wine (components/wine.py adds its steps then)

    def game_path(self, path):
        """A path of this machine as code inside the game sees it (a config value the game reads)."""
        return path

    def gpu_name(self):
        """The GPU's name as the game will read it, where the installer can tell (None: not asked)."""
        return None

    def program_data(self):
        return os.environ.get("ProgramData", r"C:\ProgramData")

    def process_running(self, exe_name):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe_name, "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return exe_name.lower() in out.lower()

    VK_LAYERS = r"SOFTWARE\Khronos\Vulkan\ImplicitLayers"

    def vulkan_layer_registered(self, manifest):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.VK_LAYERS) as key:
                winreg.QueryValueEx(key, manifest)
                return True
        except OSError:
            return False

    def register_vulkan_layer(self, manifest):
        """Writes HKLM (machine-wide), which needs administrator approval: one Windows prompt."""
        args = 'add "HKLM\\%s" /v "%s" /t REG_DWORD /d 0 /f' % (self.VK_LAYERS, manifest)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Start-Process reg -ArgumentList '%s' -Verb RunAs -Wait -WindowStyle Hidden" % args.replace("'", "''")])
        if not self.vulkan_layer_registered(manifest):
            raise InstallError("the Vulkan layer was not registered (was the administrator prompt declined?)")

    def unregister_vulkan_layer(self, manifest):
        """Removes a machine-wide Vulkan layer (HKLM): one Windows administrator prompt."""
        args = 'delete "HKLM\\%s" /v "%s" /f' % (self.VK_LAYERS, manifest)
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Start-Process reg -ArgumentList '%s' -Verb RunAs -Wait -WindowStyle Hidden" % args.replace("'", "''")])
        if self.vulkan_layer_registered(manifest):
            raise InstallError("the Vulkan layer is still registered (was the administrator prompt declined?)")

    def write_file(self, path, data):
        """Writes a file; where only administrators may (ProgramData\\ReShade is read-only for
        users), through one Windows administrator prompt."""
        try:
            with open(path, "wb") as f:
                f.write(data)
            return
        except PermissionError:
            pass
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(path)[1])
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        cmd = "Copy-Item -LiteralPath '%s' -Destination '%s' -Force" % (tmp.replace("'", "''"), path.replace("'", "''"))
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Start-Process powershell -ArgumentList '-NoProfile','-Command',\"%s\" -Verb RunAs -Wait -WindowStyle Hidden"
                        % cmd.replace('"', '`"')])
        os.remove(tmp)
        if open(path, "rb").read() != data:
            raise InstallError("could not write %s (was the administrator prompt declined?)" % path)


class ProtonSystem(System):
    """The same for a game under Proton on Linux (capture/host/proton.py): the machine-wide places
    are inside the game's own prefix, nothing needs an administrator, and a path written for the
    game to read is given as the game sees it (Z:\\..., C:\\...)."""

    wine = True

    def game_path(self, path):
        from .. import host
        return host.game_path(path, self.game)

    def gpu_name(self):
        from .. import host
        return host.gpu_name()

    def program_data(self):
        from .. import host
        return host.program_data(self.game)

    def process_running(self, exe_name):
        from .. import host
        return host.process_running(exe_name)

    def vulkan_layer_registered(self, manifest):
        return False    # a prefix of ours has no machine-wide ReShade layer

    def register_vulkan_layer(self, manifest):
        raise InstallError("ReShade as a Vulkan layer is not set up for games under Proton; use the game's Direct3D API")

    def unregister_vulkan_layer(self, manifest):
        pass

    def write_file(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


def default_system(game=None):
    """The System of the machine this runs on, for `game`."""
    system = System() if os.name == "nt" else ProtonSystem()
    system.game = game
    return system


# --- the record ----------------------------------------------------------------------------------
class Record:
    def __init__(self, work_dir):
        self.dir = work_dir
        self.path = os.path.join(work_dir, "installed.json")
        self.data = read_json(self.path) if os.path.exists(self.path) else {
            "schema": "capture_install_record/v1", "entries": []}

    def _find(self, kind, **match):
        for e in self.data["entries"]:
            if e["kind"] == kind and all(e.get(k) == v for k, v in match.items()):
                return e
        return None

    def _backup(self, path, suffix=""):
        os.makedirs(os.path.join(self.dir, "backup"), exist_ok=True)
        dst = os.path.join(self.dir, "backup", "%03d_%s%s" % (len(self.data["entries"]), os.path.basename(path), suffix))
        shutil.copy2(path, dst)
        return dst

    def file(self, path, new_sha, config=False):
        """Call before writing `path`: backs up what is there (once) and notes the new content.
        config: a settings file the install created and then edits (uninstall removes it even if
        its content changed). Returns the path of an extra backup when the file was changed since
        the install (someone's edits, kept before they are replaced), else None."""
        e = self._find("file", path=path)
        kept = None
        if e is None:
            e = {"kind": "file", "path": path, "backup": self._backup(path) if os.path.exists(path) else None}
            if config:
                e["config"] = True
            self.data["entries"].append(e)
        elif os.path.exists(path) and e.get("sha256") and sha256_file(path) not in (e["sha256"], new_sha):
            kept = self._backup(path, ".changed-%s" % now_iso().replace(":", "")[:15])
            e.setdefault("changed_backups", []).append(kept)
        e["sha256"] = new_sha
        return kept

    def setting(self, kind, path, key, old, new):
        e = self._find(kind, path=path, key=key)
        if e is None:
            e = {"kind": kind, "path": path, "key": key, "old": old}
            self.data["entries"].append(e)
        e["new"] = new

    def folder(self, path):
        if self._find("dir", path=path) is None:
            self.data["entries"].append({"kind": "dir", "path": path})

    def makedirs(self, path):
        """Creates a folder and any missing parents, noting each one created."""
        missing = []
        while path and not os.path.isdir(path):
            missing.append(path)
            path = os.path.dirname(path)
        for d in reversed(missing):
            os.mkdir(d)
            self.folder(d)

    def note(self, **entry):
        if self._find(entry["kind"], **{k: v for k, v in entry.items() if k != "kind"}) is None:
            self.data["entries"].append(entry)

    def save(self, **info):
        self.data.update(info, updated=now_iso())
        write_json(self.path, self.data)


# --- small file editors ----------------------------------------------------------------------------
class Ini:
    """Line-based INI editing that keeps everything it does not touch. Section "" = before any header."""

    def __init__(self, path):
        self.path = path
        self.bom = False
        self.lines = []
        if os.path.exists(path):
            raw = open(path, "rb").read()
            self.bom = raw.startswith(b"\xef\xbb\xbf")
            self.lines = raw.decode("utf-8-sig", "replace").splitlines()

    def _section(self, section):
        """(start, end) line range of a section's body, or None."""
        start = 0 if section == "" else None
        for i, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                if start is not None:  # the next header ends the section
                    return start, i
                if s[1:-1] == section:
                    start = i + 1
        return (start, len(self.lines)) if start is not None else None

    def get(self, section, key):
        rng = self._section(section)
        if rng is None:
            return None
        for line in self.lines[rng[0]:rng[1]]:
            k, sep, v = line.partition("=")
            if sep and k.strip() == key:
                return v.strip()
        return None

    def set(self, section, key, value):
        rng = self._section(section)
        if rng is None:
            if value is None:
                return
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines += ["[%s]" % section, "%s=%s" % (key, value)]
            return
        for i in range(rng[0], rng[1]):
            k, sep, _ = self.lines[i].partition("=")
            if sep and k.strip() == key:
                if value is None:
                    del self.lines[i]
                    start, end = self._section(section)
                    if section and not any(line.strip() for line in self.lines[start:end]):
                        del self.lines[start - 1:end]  # the section is empty now: drop its header
                        while self.lines and not self.lines[-1].strip():
                            self.lines.pop()
                else:
                    self.lines[i] = "%s=%s" % (key, value)
                return
        if value is not None:
            end = rng[1]
            while end > rng[0] and not self.lines[end - 1].strip():
                end -= 1
            self.lines.insert(end, "%s=%s" % (key, value))

    def data(self):
        return (b"\xef\xbb\xbf" if self.bom else b"") + ("\r\n".join(self.lines) + "\r\n").encode("utf-8")

    def save(self, system=None):
        """system: write through System.write_file (an administrator prompt where needed)."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if system is not None:
            system.write_file(self.path, self.data())
            return
        with open(self.path, "wb") as f:
            f.write(self.data())


def xml_value(text, name):
    """The value of <name value="..."/> or <name>...</name> in a flat settings XML, or None."""
    m = re.search(r'<%s value="([^"]*)"\s*/>' % re.escape(name), text) or re.search(
        r"<%s>([^<]*)</%s>" % (re.escape(name), re.escape(name)), text)
    return m.group(1) if m else None


def xml_set(text, name, value):
    n = re.escape(name)
    new, count = re.subn(r'(<%s value=")[^"]*("\s*/>)' % n, lambda m: m.group(1) + value + m.group(2), text)
    if not count:
        new, count = re.subn(r"(<%s>)[^<]*(</%s>)" % (n, n), lambda m: m.group(1) + value + m.group(2), text)
    if not count:
        raise InstallError("no <%s> setting in the file" % name)
    return new


def xml_attr_value(text, name, element="Attr"):
    """The value of <element name="name" value="..."/> in a list-style settings XML (CryEngine's
    attributes.xml), or None."""
    m = re.search(r'<%s\s+name="%s"\s+value="([^"]*)"\s*/>' % (re.escape(element), re.escape(name)), text)
    return m.group(1) if m else None


def xml_attr_set(text, name, value, element="Attr"):
    """Sets <element name="name" value="value" />, adding it before the root's closing tag when it is
    not there; value None removes it."""
    pat = r'<%s\s+name="%s"\s+value="[^"]*"\s*/>' % (re.escape(element), re.escape(name))
    if value is None:
        return re.sub(r"[ \t]*" + pat + r"[ \t]*(\r?\n)?", "", text, count=1)
    line = '<%s name="%s" value="%s" />' % (element, name, value)
    new, n = re.subn(pat, lambda m: line, text, count=1)
    if n:
        return new
    close = text.rfind("</")
    if close < 0:
        raise InstallError('no root element to add <%s name="%s"> to' % (element, name))
    nl = "\r\n" if "\r\n" in text else "\n"
    start = text.rfind("\n", 0, close) + 1
    if text[start:close].strip():      # the closing tag shares its line: put ours on a line before it
        return text[:close] + nl + "  " + line + nl + text[close:]
    return text[:start] + "  " + line + nl + text[start:]


# --- steps ---------------------------------------------------------------------------------------
class Step:
    tag = "mods"
    needs_game_closed = False

    def describe(self):
        raise NotImplementedError

    def status(self, ctx):
        """(state, note): state is "ok" (nothing to do), "todo" or "missing" (cannot be done)."""
        raise NotImplementedError

    def apply(self, ctx):
        raise NotImplementedError


class CopyFile(Step):
    """Installs one file. src: a FileRef (capture/install/sources.py) or a callable returning a path."""

    def __init__(self, src, dst, tag="mods", closed=True, what=None, shared=False, only_if_missing=False):
        """shared: a machine-wide file other games may use too; uninstall leaves it in place
        (or puts back the version it replaced). only_if_missing: a settings file copied once and
        then edited by later steps (and by the user); uninstall removes it."""
        self.src, self.dst, self.tag, self.needs_game_closed, self.what = src, dst, tag, closed, what
        self.shared, self.only_if_missing = shared, only_if_missing

    def describe(self):
        return "%s -> %s" % (self.what or getattr(self.src, "label", "file"), self.dst)

    def _source(self):
        """(sha256 or None, reader or None, note)"""
        if callable(self.src):
            p = self.src()
            if p and os.path.exists(p):
                return sha256_file(p), (lambda: open(p, "rb").read()), p
            return None, None, "not built yet"
        return self.src.content_sha256, (self.src.read if self.src.found else None), self.src.where

    def status(self, ctx):
        if self.only_if_missing and os.path.exists(self.dst):
            return "ok", "present"
        sha, reader, note = self._source()
        have = sha256_file(self.dst) if os.path.exists(self.dst) else None
        if have and sha and have == sha:
            return "ok", "installed"
        if have and sha is None and reader is None and not callable(self.src):
            return "ok", "installed (version not pinned)"
        if reader is None:
            return ("todo", note) if callable(self.src) else ("missing", self.src.missing_note)
        return "todo", ("replace, was a different version" if have else "copy from %s" % note)

    def apply(self, ctx):
        sha, reader, _ = self._source()
        if reader is None:
            raise InstallError("no source for %s" % self.dst)
        data = reader()
        if self.shared and not os.path.exists(self.dst):
            os.makedirs(os.path.dirname(self.dst), exist_ok=True)
            ctx.record.note(kind="machine", what=self.dst)
        else:
            ctx.record.makedirs(os.path.dirname(self.dst))
            kept = ctx.record.file(self.dst, sha256_bytes(data), config=self.only_if_missing)
            if kept:
                ctx.log("  kept    your changed %s as %s" % (os.path.basename(self.dst), kept))
        with open(self.dst, "wb") as f:
            f.write(data)


class RemoveFile(Step):
    """Removes a file if it is a given version (sha256), e.g. a DLL another arrangement replaced;
    backed up first."""

    def __init__(self, path, sha256, tag="mods", closed=True, why=""):
        self.path, self.sha256, self.tag, self.needs_game_closed, self.why = path, sha256, tag, closed, why

    def describe(self):
        return "remove %s%s" % (self.path, "  (%s)" % self.why if self.why else "")

    def status(self, ctx):
        if os.path.exists(self.path) and (self.sha256 is None or sha256_file(self.path) == self.sha256):
            return "todo", "remove"
        return "ok", "absent"

    def apply(self, ctx):
        ctx.record.file(self.path, None)
        os.remove(self.path)


class WriteText(Step):
    def __init__(self, dst, text, tag="mods", closed=False, what=None, only_if_missing=False):
        self.dst, self.text, self.tag, self.needs_game_closed, self.what = dst, text, tag, closed, what
        self.only_if_missing = only_if_missing

    def describe(self):
        return "%s (%s)" % (self.dst, self.what or "written")

    def status(self, ctx):
        if os.path.exists(self.dst):
            if self.only_if_missing or open(self.dst, "rb").read() == self.text.encode("utf-8"):
                return "ok", "present"
            return "todo", "rewrite"
        return "todo", "create"

    def apply(self, ctx):
        ctx.record.makedirs(os.path.dirname(self.dst))
        data = self.text.encode("utf-8")
        ctx.record.file(self.dst, sha256_bytes(data))
        with open(self.dst, "wb") as f:
            f.write(data)


class MakeDir(Step):
    def __init__(self, path, tag="mods"):
        self.path, self.tag = path, tag

    def describe(self):
        return "folder %s" % self.path

    def status(self, ctx):
        return ("ok", "exists") if os.path.isdir(self.path) else ("todo", "create")

    def apply(self, ctx):
        ctx.record.makedirs(self.path)


class IniSet(Step):
    def __init__(self, path, section, key, value, tag="settings", closed=True, why="", game_path=False):
        """game_path: the value is a path on this machine that code inside the game reads; it is
        written as the game sees it (the same path on Windows, Z:\\... under Proton)."""
        self.path, self.section, self.key, self.value = path, section, key, value
        self.tag, self.needs_game_closed, self.why, self.game_path = tag, closed, why, game_path

    def describe(self):
        return "%s [%s] %s=%s%s" % (os.path.basename(self.path), self.section, self.key, self.value,
                                    "  (%s)" % self.why if self.why else "")

    def _value(self, ctx):
        return ctx.system.game_path(self.value) if self.game_path else self.value

    def status(self, ctx):
        cur = Ini(self.path).get(self.section, self.key)
        return ("ok", "set") if cur == self._value(ctx) else ("todo", "was %s" % (cur if cur is not None else "unset"))

    def apply(self, ctx):
        ini = Ini(self.path)
        value = self._value(ctx)
        ctx.record.makedirs(os.path.dirname(self.path))
        ctx.record.setting("ini", self.path, "%s|%s" % (self.section, self.key), ini.get(self.section, self.key), value)
        ini.set(self.section, self.key, value)
        ini.save()


class IniListAdd(Step):
    """Makes sure a comma-separated INI value (e.g. ReShade's EffectSearchPaths) contains an item,
    keeping the items already there."""

    def __init__(self, path, section, key, item, tag="settings", closed=True, why=""):
        self.path, self.section, self.key, self.item = path, section, key, item
        self.tag, self.needs_game_closed, self.why = tag, closed, why

    def describe(self):
        return "%s [%s] %s includes %s%s" % (os.path.basename(self.path), self.section, self.key, self.item,
                                             "  (%s)" % self.why if self.why else "")

    def _items(self, value):
        return [v for v in (value or "").split(",") if v]

    def status(self, ctx):
        cur = Ini(self.path).get(self.section, self.key)
        return ("ok", "included") if self.item.lower() in (v.lower() for v in self._items(cur)) else (
            "todo", "was %s" % (cur if cur is not None else "unset"))

    def apply(self, ctx):
        ini = Ini(self.path)
        old = ini.get(self.section, self.key)
        new = ",".join(self._items(old) + [self.item])
        ctx.record.makedirs(os.path.dirname(self.path))
        ctx.record.setting("ini", self.path, "%s|%s" % (self.section, self.key), old, new)
        ini.set(self.section, self.key, new)
        ini.save()


_MISSING = object()


def json_get(d, key):
    """d[key], where key is a top-level key or a list of keys into nested objects; None if absent."""
    for k in (key if isinstance(key, (list, tuple)) else [key]):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def json_put(d, key, value):
    """Sets d[key] (key as in json_get), creating nested objects; value _MISSING removes it."""
    keys = list(key) if isinstance(key, (list, tuple)) else [key]
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    if value is _MISSING:
        d.pop(keys[-1], None)
    else:
        d[keys[-1]] = value


class JsonSet(Step):
    """Sets one key of a JSON file: a top-level key, or a list of keys into nested objects
    (["graphics", "enable_lens_effects"]). A missing file is created from `default`."""

    def __init__(self, path, key, value, default=None, tag="settings", closed=True, why=""):
        self.path, self.key, self.value, self.default = path, key, value, default or {}
        self.tag, self.needs_game_closed, self.why = tag, closed, why

    def describe(self):
        key = ".".join(self.key) if isinstance(self.key, (list, tuple)) else self.key
        return "%s %s=%s%s" % (os.path.basename(self.path), key, json.dumps(self.value),
                               "  (%s)" % self.why if self.why else "")

    def _load(self):
        return read_json(self.path) if os.path.exists(self.path) else None

    def status(self, ctx):
        d = self._load()
        return ("ok", "set") if d is not None and json_get(d, self.key) == self.value else ("todo", "change")

    def apply(self, ctx):
        d = self._load()
        if d is None:
            d = json.loads(json.dumps(self.default))
            ctx.record.makedirs(os.path.dirname(self.path))
            ctx.record.file(self.path, None)
        else:
            key = list(self.key) if isinstance(self.key, (list, tuple)) else self.key
            ctx.record.setting("json", self.path, key, json_get(d, self.key), self.value)
        json_put(d, self.key, self.value)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=4)
            f.write("\n")


class XmlSet(Step):
    """Sets <name value="..."/> (or <name>...</name>) in a game's settings XML; skipped if the
    file does not exist yet (a game writes it on first launch)."""

    def __init__(self, path, name, value, tag="settings", closed=True, why=""):
        self.path, self.name, self.value = path, name, value
        self.tag, self.needs_game_closed, self.why = tag, closed, why

    def describe(self):
        return "%s <%s> = %s%s" % (os.path.basename(self.path), self.name, self.value, "  (%s)" % self.why if self.why else "")

    def status(self, ctx):
        if not os.path.exists(self.path):
            return "ok", "skipped: no settings file yet (start the game once, then run install again)"
        cur = xml_value(open(self.path, encoding="utf-8", errors="replace", newline="").read(), self.name)
        return ("ok", "set") if cur == self.value else ("todo", "was %s" % cur)

    def apply(self, ctx):
        text = open(self.path, encoding="utf-8", errors="replace", newline="").read()
        ctx.record.setting("xml", self.path, self.name, xml_value(text, self.name), self.value)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(xml_set(text, self.name, self.value))


class XmlAttrSet(Step):
    """Sets <Attr name="..." value="..." /> in a list-style settings XML (CryEngine's attributes.xml),
    adding the element when it is missing. empty: the file's text to start from when it does not
    exist or has no root element yet (a game that never saved its options); with None the step is
    skipped then. A file the step creates is removed by uninstall."""

    def __init__(self, path, name, value, element="Attr", empty=None, tag="settings", closed=True, why=""):
        self.path, self.name, self.value, self.element, self.empty = path, name, value, element, empty
        self.tag, self.needs_game_closed, self.why = tag, closed, why

    def describe(self):
        return "%s %s=%s%s" % (os.path.basename(self.path), self.name, self.value, "  (%s)" % self.why if self.why else "")

    def _text(self):
        if not os.path.exists(self.path):
            return None
        text = open(self.path, encoding="utf-8", errors="replace", newline="").read()
        return text if "</" in text else None

    def status(self, ctx):
        text = self._text()
        if text is None:
            return ("todo", "create the file") if self.empty is not None else ("ok", "skipped: no settings file yet")
        cur = xml_attr_value(text, self.name, self.element)
        return ("ok", "set") if cur == self.value else ("todo", "was %s" % ("missing" if cur is None else cur))

    def apply(self, ctx):
        text = self._text()
        if text is None:
            if self.empty is None:
                return
            ctx.record.makedirs(os.path.dirname(self.path))
            ctx.record.file(self.path, sha256_bytes(self.empty.encode("utf-8")), config=True)
            text = self.empty
        key = "%s|%s" % (self.element, self.name)
        ctx.record.setting("xmlattr", self.path, key, xml_attr_value(text, self.name, self.element), self.value)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(xml_attr_set(text, self.name, self.value, self.element))


def kv_get(text, key):
    """The value of a `"Key" "Value"` line (Decima's settings files, e.g. Death Stranding's
    game_settings.cfg), or None."""
    m = re.search(r'^"%s"\s+"([^"]*)"' % re.escape(key), text, re.M)
    return m.group(1) if m else None


def kv_set(text, key, value):
    line = '"%s" "%s"' % (key, value)
    pat = re.compile(r'^"%s"\s+"[^"]*"' % re.escape(key), re.M)
    if pat.search(text):
        return pat.sub(line.replace("\\", "\\\\"), text, count=1)
    nl = "\r\n" if "\r\n" in text else "\n"
    return text + ("" if text.endswith(nl) or not text else nl) + line + nl


class KvSet(Step):
    """Sets `"Key" "Value"` in a settings file made of such lines (Decima's .cfg files); skipped if
    the file does not exist yet (the game writes it on first launch). files: one path or several
    (one per game account)."""

    def __init__(self, path, key, value, tag="settings", closed=True, why=""):
        self.path, self.key, self.value = path, key, value
        self.tag, self.needs_game_closed, self.why = tag, closed, why

    def describe(self):
        return "%s %s=%s%s" % (os.path.basename(self.path), self.key, self.value, "  (%s)" % self.why if self.why else "")

    def status(self, ctx):
        if not os.path.exists(self.path):
            return "ok", "skipped: no settings file yet (start the game once, then run install again)"
        cur = kv_get(open(self.path, encoding="utf-8", errors="replace", newline="").read(), self.key)
        return ("ok", "set") if cur == self.value else ("todo", "was %s" % cur)

    def apply(self, ctx):
        text = open(self.path, encoding="utf-8", errors="replace", newline="").read()
        ctx.record.setting("kv", self.path, self.key, kv_get(text, self.key), self.value)
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(kv_set(text, self.key, self.value))


class Call(Step):
    """A step given as functions: status_fn(ctx) -> (state, note), apply_fn(ctx)."""

    def __init__(self, what, status_fn, apply_fn, tag="mods", closed=False):
        self.what, self.status_fn, self.apply_fn, self.tag, self.needs_game_closed = what, status_fn, apply_fn, tag, closed

    def describe(self):
        return self.what

    def status(self, ctx):
        return self.status_fn(ctx)

    def apply(self, ctx):
        self.apply_fn(ctx)


# --- running ---------------------------------------------------------------------------------------
class Ctx:
    def __init__(self, game, game_dir, exe_name, options, files, record, system=None, log=print):
        self.game, self.game_dir, self.exe_name, self.options = game, game_dir, exe_name, options
        self.files, self.record, self.system, self.log = files, record, system or default_system(game), log

    def file(self, mod_id, name):
        return self.files.ref(mod_id, name)


def run(ctx, steps, only=None, dry_run=False):
    """Shows every step's state, then applies the ones that are not satisfied. Returns the count applied."""
    steps = [s for s in steps if not only or s.tag in only]
    rows = [(s,) + tuple(s.status(ctx)) for s in steps]

    def short(text):
        return text.replace(ctx.game_dir, "<game>")

    for s, state, note in rows:
        ctx.log("  %-7s [%s] %s%s" % ({"ok": "ok", "todo": "TO DO", "missing": "MISSING"}[state], s.tag, short(s.describe()),
                                        "" if state == "ok" else "  <- " + short(note)))
    missing = [(s, note) for s, state, note in rows if state == "missing"]
    if missing:
        raise InstallError("%d files are missing; nothing was changed:\n%s" % (
            len(missing), "\n".join("  - %s" % note for _, note in missing)))
    pending = [s for s, state, _ in rows if state == "todo"]
    if dry_run or not pending:
        return 0 if not dry_run else len(pending)
    if any(s.needs_game_closed for s in pending) and ctx.system.process_running(ctx.exe_name):
        raise InstallError("close the game first: %d of the steps write files it has open" % sum(
            s.needs_game_closed for s in pending))
    for s in pending:
        s.apply(ctx)
        ctx.record.save()
        ctx.log("  done    [%s] %s" % (s.tag, s.describe()))
    left = [s for s in pending if s.status(ctx)[0] != "ok"]
    if left:
        raise InstallError("still not satisfied after applying: " + "; ".join(s.describe() for s in left))
    return len(pending)


def uninstall(record, log=print):
    """Puts back what the record says was changed, newest first. Files or settings changed since
    the install are left alone."""
    left = []
    for e in reversed(record.data["entries"]):
        kind, path = e["kind"], e.get("path")
        if kind == "file":
            cur = sha256_file(path) if os.path.exists(path) else None
            if e.get("config") and not e.get("backup") and cur is not None:
                os.remove(path)
                log("  removed %s" % path)
            elif e.get("sha256") and cur and cur != e["sha256"]:
                log("  left    %s (changed since the install)" % path)
                left.append(e)
            elif e.get("backup") and os.path.exists(e["backup"]):
                shutil.copy2(e["backup"], path)
                log("  restored %s" % path)
            elif cur is not None:
                os.remove(path)
                log("  removed %s" % path)
        elif kind == "ini":
            section, _, key = e["key"].partition("|")
            ini = Ini(path)
            if ini.get(section, key) == e["new"]:
                ini.set(section, key, e["old"])
                try:
                    if any(line.strip() for line in ini.lines):
                        ini.save()
                    else:
                        os.remove(path)  # nothing left in it: the install created it
                    log("  reset   %s [%s] %s" % (os.path.basename(path), section, key))
                except PermissionError:  # machine-wide (ProgramData\ReShade): administrators only
                    log("  left    %s [%s] %s=%s (needs an administrator; was %s)" % (
                        path, section, key, e["new"], e["old"]))
                    left.append(e)
        elif kind == "json" and os.path.exists(path):
            d = read_json(path)
            if json_get(d, e["key"]) == e["new"]:
                json_put(d, e["key"], _MISSING if e["old"] is None else e["old"])
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(d, f, indent=4)
                log("  reset   %s %s" % (os.path.basename(path), e["key"]))
        elif kind == "xml" and os.path.exists(path):
            text = open(path, encoding="utf-8", errors="replace", newline="").read()
            if xml_value(text, e["key"]) == e["new"] and e["old"] is not None:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(xml_set(text, e["key"], e["old"]))
                log("  reset   %s <%s>" % (os.path.basename(path), e["key"]))
        elif kind == "kv" and os.path.exists(path):
            text = open(path, encoding="utf-8", errors="replace", newline="").read()
            if kv_get(text, e["key"]) == e["new"] and e["old"] is not None:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(kv_set(text, e["key"], e["old"]))
                log("  reset   %s %s" % (os.path.basename(path), e["key"]))
        elif kind == "xmlattr" and os.path.exists(path):
            element, _, name = e["key"].partition("|")
            text = open(path, encoding="utf-8", errors="replace", newline="").read()
            if xml_attr_value(text, name, element) == e["new"]:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(xml_attr_set(text, name, e["old"], element))
                log("  reset   %s %s" % (os.path.basename(path), name))
        elif kind == "dir":
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
                log("  removed %s" % path)
        elif kind == "machine":
            log("  left    %s (machine-wide, may be used by other games)" % e.get("what"))
            left.append(e)
    record.data["entries"] = left
    record.save()
