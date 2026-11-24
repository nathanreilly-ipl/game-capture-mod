"""The installer without touching a real game.

    uv run --project . python tests/test_install.py [--mods <folder with the real mod archives>]

A. The framework on made-up files: steps, dry run, backups, the install record, uninstall,
   files found by hash inside archives, missing files stop the install before any change.
P. A pack (a large mod installed from its archive) and nested JSON settings, on made-up files.
B. The RDR2 plan in a sandbox (a fake game folder, a fake ProgramData and registry), when the
   real mod files are available (--mods, or out/mods): install, install again (nothing to do),
   uninstall (everything back), then a bundle made from the sandbox installs into a second one
   on a "machine without build tools". With the OptiScaler release in out/mods, a third sandbox
   gets --optiscaler (a stand-in for NVIDIA's model), then its own preset edits survive a reinstall.
C. RDR2's default install (Direct3D 12, OptiScaler, ray tracing, 2560x1440), then both off, uninstall.
D. The GTA V Legacy plan in a sandbox: install, again (nothing to do), uninstall.
F. The Cyberpunk 2077 plan in a sandbox, when its mod files and our two built plug-ins are
   available (built here, or prebuilt in a mods bundle): install, again (nothing to do), uninstall;
   once as on Windows and once with a machine that gives the game its paths differently (as under
   Proton: Z:\\...), where only the paths written for the game to read may differ.
G. The Witcher 3 plan in a sandbox, the same two ways: our script as a loose script mod, the debug
   console switched on in the game's own config file, ReShade as dxgi.dll with the add-on,
   OptiScaler as winmm.dll (a stand-in for NVIDIA's model), the capture settings in the user
   settings file; again (nothing to do), --no-optiscaler, uninstall.
"""
import argparse
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import install as inst  # noqa: E402
from capture.install import plan, sources  # noqa: E402
from capture.install.components import addon, clock  # noqa: E402
from capture.util import sha256_bytes, sha256_file, write_json  # noqa: E402
from adapters.gtav import install as gtav_install  # noqa: E402


class FakeSystem(plan.System):
    def __init__(self, root, running=False):
        self.root, self.running, self.layers = root, running, set()

    def program_data(self):
        return os.path.join(self.root, "ProgramData")

    def process_running(self, exe_name):
        return self.running

    def vulkan_layer_registered(self, manifest):
        return manifest in self.layers

    def register_vulkan_layer(self, manifest):
        self.layers.add(manifest)

    def unregister_vulkan_layer(self, manifest):
        self.layers.discard(manifest)


class FakeProton(FakeSystem):
    """A machine where the game sees this machine's paths differently (Proton: drive Z:)."""

    def game_path(self, path):
        return "Z:" + path.replace("/", "\\")


def tree(root):
    out = {}
    for d, _, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            out[os.path.relpath(p, root)] = sha256_file(p)
    return out


def part_a(tmp):
    game = os.path.join(tmp, "game")
    os.makedirs(game)
    open(os.path.join(game, "old.dll"), "wb").write(b"the game's own file")
    open(os.path.join(game, "settings.ini"), "wb").write(b"[A]\r\nKeep=1\r\nKey=old\r\n[B]\r\nOther=2\r\n")
    open(os.path.join(game, "settings.xml"), "wb").write(b'<root>\r\n  <vSync value="1" />\r\n  <API>vulkan</API>\r\n</root>\r\n')
    before = tree(game)

    payload = b"mod payload " * 1000
    mods_dir = os.path.join(tmp, "mods")
    os.makedirs(mods_dir)
    with zipfile.ZipFile(os.path.join(mods_dir, "SomeMod_as_downloaded.zip"), "w") as z:
        z.writestr("bin/sub/mod.dll", payload)
        z.writestr("readme.txt", "hello")
    lock = os.path.join(tmp, "lock.json")
    write_json(lock, {"schema": "capture_mods_lock/v1", "mods": {
        "somemod": {"title": "Some Mod 1.0", "page": "https://example.invalid/somemod", "redistributable": True,
                    "files": [{"name": "mod.dll", "size": len(payload), "sha256": sha256_bytes(payload)}]},
        "absent": {"title": "Absent Mod", "page": "https://example.invalid/absent", "redistributable": False,
                   "files": [{"name": "absent.dll", "size": 5, "sha256": "0" * 64}]}}})
    files = sources.Files(sources.load_locks(lock), roots=[mods_dir])
    ref = files.ref("somemod", "mod.dll")
    assert ref.found and ref.where.endswith("SomeMod_as_downloaded.zip!bin/sub/mod.dll"), ref.where
    assert not files.ref("absent", "absent.dll").found

    work = os.path.join(tmp, "work")
    quiet = lambda *a: None  # noqa: E731
    ctx = plan.Ctx("toy", game, "game.exe", {}, files, plan.Record(work), FakeSystem(tmp), quiet)
    steps = [plan.CopyFile(ref, os.path.join(game, "old.dll")),               # replaces a file: backed up
             plan.CopyFile(ref, os.path.join(game, "plugins", "mod.dll")),    # new file in a new folder
             plan.WriteText(os.path.join(game, "flag.dev"), "", only_if_missing=True),
             plan.IniSet(os.path.join(game, "settings.ini"), "A", "Key", "new"),
             plan.IniSet(os.path.join(game, "settings.ini"), "C", "Added", "1"),
             plan.XmlSet(os.path.join(game, "settings.xml"), "vSync", "0"),
             plan.XmlSet(os.path.join(tmp, "no_such.xml"), "vSync", "0"),      # no settings file yet: skipped
             plan.JsonSet(os.path.join(game, "cfg", "Settings.json"), "autorun", True, default={"x": 1})]
    assert plan.run(ctx, steps, dry_run=True) == 7 and tree(game) == before, "a dry run must change nothing"
    try:
        plan.run(ctx, steps + [plan.CopyFile(files.ref("absent", "absent.dll"), os.path.join(game, "absent.dll"))])
        raise AssertionError("expected the missing file to stop the install")
    except plan.InstallError as e:
        assert "absent.dll" in str(e) and tree(game) == before, "a missing file must stop the install before any change"
    assert plan.run(ctx, steps) == 7
    ini = plan.Ini(os.path.join(game, "settings.ini"))
    assert (ini.get("A", "Key"), ini.get("A", "Keep"), ini.get("B", "Other"), ini.get("C", "Added")) == ("new", "1", "2", "1")
    assert 'vSync value="0"' in open(os.path.join(game, "settings.xml")).read()
    assert sha256_file(os.path.join(game, "old.dll")) == sha256_bytes(payload)
    assert plan.run(ctx, steps) == 0, "a second run has nothing to do"

    running = plan.Ctx("toy", game, "game.exe", {}, files, plan.Record(os.path.join(tmp, "work2")), FakeSystem(tmp, running=True), quiet)
    try:
        plan.run(running, [plan.CopyFile(ref, os.path.join(game, "another.dll"))])
        raise AssertionError("expected a refusal while the game runs")
    except plan.InstallError as e:
        assert "close the game" in str(e)

    open(os.path.join(game, "plugins", "mod.dll"), "ab").write(b"edited by the user after the install")
    plan.uninstall(plan.Record(work), quiet)
    after = tree(game)
    kept = os.path.join("plugins", "mod.dll")
    assert kept in after, "a file changed since the install is left alone"
    del after[kept]
    assert after == before, (sorted(set(after) ^ set(before)), [k for k in before if after.get(k) != before[k]])
    print("A ok: steps, dry run, missing-file stop, backups, record, second run, game-running refusal, uninstall")


def part_p(tmp):
    """A pack (a large mod installed from its archive, components/pack.py) and nested JSON settings,
    on made-up files: found by archive name and size, streamed and hashed, then removed again."""
    from capture.install.components import pack
    game = os.path.join(tmp, "game")
    os.makedirs(os.path.join(game, "keep"))
    open(os.path.join(game, "keep", "own.txt"), "wb").write(b"the game's own file")
    payloads = {"Big.asi": b"asi " * 5000, "loader/packs/one/dlc.rpf": b"rpf one " * 9000,
                "loader/packs/two/dlc.rpf": b"rpf two " * 9000, "loader/data.xml": b"<x/>"}
    mods_dir = os.path.join(tmp, "mods", "deep", "deeper", "deepest")
    os.makedirs(mods_dir)
    archive = os.path.join(mods_dir, "Toy Pack v2.zip")
    with zipfile.ZipFile(archive, "w") as z:
        for name, data in payloads.items():
            z.writestr("Main Package/" + name, data)
        z.writestr("Main Package/ReShade.ini", "[GENERAL]\r\n")       # in the archive, not pinned: never installed
        z.writestr("Optional/extra.fx", "// no")
    lock = os.path.join(tmp, "lock.json")
    write_json(lock, {"schema": "capture_mods_lock/v1", "mods": {"toypack": {
        "title": "Toy Pack v2", "page": "https://example.invalid/toypack", "pack": True, "redistributable": False,
        "archive": {"name": "Toy Pack v2.zip", "size": os.path.getsize(archive), "root": "Main Package/"},
        "files": [{"name": n, "size": len(d), "sha256": sha256_bytes(d)} for n, d in payloads.items()]}}})
    files = sources.Files(sources.load_locks(lock), roots=[os.path.join(tmp, "mods")])
    assert files.status() == [] and [m for m, _ in files.packs()] == ["toypack"], "packs stay out of the file search"
    quiet = lambda *a: None  # noqa: E731
    work = os.path.join(tmp, "work")
    ctx = plan.Ctx("toy", game, "game.exe", {}, files, plan.Record(work), FakeSystem(tmp), quiet)
    before = tree(game)
    cfg = os.path.join(tmp, "AppData", "Toy", "settings.json")
    steps = pack.steps(ctx, game, "toypack", "graphicsmod") + [
        plan.JsonSet(cfg, ["graphics", "lens"], False), plan.JsonSet(cfg, ["graphics", "fringe"], False)]
    assert plan.run(ctx, steps) == 3
    for name, data in payloads.items():
        assert open(os.path.join(game, *name.split("/")), "rb").read() == data, name
    assert not os.path.exists(os.path.join(game, "ReShade.ini")), "only the pinned files are installed"
    assert plan.read_json(cfg) == {"graphics": {"lens": False, "fringe": False}}
    assert plan.run(ctx, steps) == 0, "a second run has nothing to do"
    # a folder holding the files (the archive unpacked by hand) is a source too
    unpacked = os.path.join(tmp, "unpacked")
    for name, data in payloads.items():
        os.makedirs(os.path.dirname(os.path.join(unpacked, *name.split("/"))), exist_ok=True)
        open(os.path.join(unpacked, *name.split("/")), "wb").write(data)
    src = pack.find_source(files.mods["toypack"], [unpacked])
    assert src is not None and not src.is_archive and os.path.samefile(str(src), unpacked)
    # a wrong file in the archive stops the install, and nothing half-written stays
    os.remove(os.path.join(game, "Big.asi"))
    bad =dict(files.mods["toypack"], files=[dict(f, sha256="0" * 64) if f["name"] == "Big.asi" else f
                                            for f in files.mods["toypack"]["files"]])
    files.mods["toypack"] = bad
    try:
        plan.run(ctx, pack.steps(ctx, game, "toypack", "graphicsmod"))
        raise AssertionError("expected the hash mismatch to stop the install")
    except plan.InstallError as e:
        assert "sha256" in str(e) and not os.path.exists(os.path.join(game, "Big.asi.part")), e
    # turned off: its files and the folders it made go, the game's own stay
    assert plan.run(ctx, pack.not_installed(ctx, game, "toypack", "graphicsmod")) == 1
    assert tree(game) == before, sorted(set(tree(game)) ^ set(before))
    assert not os.path.exists(os.path.join(game, "loader")), "the pack's empty folders are removed"
    plan.uninstall(plan.Record(work), quiet)
    assert not os.path.exists(cfg) and tree(game) == before
    print("P ok: a pack from its archive (found by name and size, three folders down), nested JSON settings, a second "
          "run with nothing to do, an unpacked folder as a source, a hash mismatch stops it, removal, uninstall")


def sandbox(tmp, name, mods, monkey_no_tools=False):
    root = os.path.join(tmp, name)
    game = os.path.join(root, "game")
    os.makedirs(game)
    open(os.path.join(game, "RDR2.exe"), "wb").write(b"not the real game")
    xml = os.path.join(root, "system.xml")
    open(xml, "wb").write(b'<Settings>\r\n  <vSync value="1" />\r\n  <pauseOnFocusLoss value="true" />\r\n  <dlssIndex value="0" />\r\n  <dlssQuality value="5" />\r\n'
                          b'  <API>kSettingAPI_Vulkan</API>\r\n</Settings>\r\n')
    options = {"exchange_dir": os.path.join(root, "exchange"), "settings_xml": xml, "api": "vulkan",
               "optiscaler": False, "ray_tracing": False, "resolution": ""}  # the Vulkan setup, not the defaults
    system = FakeSystem(root)
    work = os.path.join(root, "work")
    return root, game, options, system, work


def part_b(tmp, mods):
    lines = []
    root, game, options, system, work = sandbox(tmp, "pc1", mods)
    before = tree(root)
    n = inst.install("rdr2", game, options, mods, system=system, work=work, log=lines.append)
    assert n > 20, n
    for rel in ("ScriptHookRDR2.dll", "dinput8.dll", "NativeTrainer.asi", "RedLua.asi", "lua51.dll", "ScriptHookRDR2.dev",
                "capture_mod.addon64", "ReShade.ini", "ReShadePreset.ini", os.path.join("RedLua", "natives.json"),
                os.path.join("reshade-shaders", "Shaders", "ReShade.fxh"),
                os.path.join("reshade-shaders", "Shaders", "SweetFX", "Vibrance.fx"),
                os.path.join("RedLua", "Settings.json"), os.path.join("RedLua", "Scripts", "capture_loader.lua"),
                os.path.join("RedLua", "Scripts", "scout_overlay.lua"), os.path.join("RedLua", "Langs", "en.lng")):
        assert os.path.exists(os.path.join(game, rel)), rel
    assert "_SET_PHOTO_MODE_EXPOSURE_LOCKED" in open(os.path.join(game, "RedLua", "natives.json"), encoding="utf-8").read()
    common = os.path.join(root, "ProgramData", "ReShade")
    assert os.path.exists(os.path.join(common, "ReShade64.dll")) and os.path.join(common, "ReShade64.json") in system.layers
    assert os.path.join(game, "RDR2.exe") in open(os.path.join(common, "ReShadeApps.ini")).read()
    ini = plan.Ini(os.path.join(game, "ReShade.ini"))
    assert ini.get("CAPTURE_MOD", "OutputDir") == options["exchange_dir"] and ini.get("GENERAL", "PresetPath") == r".\ReShadePreset.ini"
    assert ini.get("GENERAL", "EffectSearchPaths") == r".\reshade-shaders\Shaders\**"
    assert sha256_file(os.path.join(game, "ReShadePreset.ini")) == sha256_file(
        os.path.join(os.path.dirname(inst.installer("rdr2").__file__), "visual", "ReShadePreset.ini"))
    assert 'vSync value="0"' in open(options["settings_xml"]).read() and 'pauseOnFocusLoss value="false"' in open(options["settings_xml"]).read()
    assert inst.install("rdr2", game, options, mods, system=system, work=work, log=lines.append) == 0, "second run: nothing to do"
    print("B ok: RDR2 plan installed into a sandbox (%d steps), second run had nothing to do" % n)

    # a bundle from this install sets up a second machine that has neither the archives nor build tools
    ctx, mod = inst.context("rdr2", game, options, mods, system=system, work=work, log=lines.append)
    bundle = os.path.join(tmp, "bundle.zip")
    sources.bundle(ctx.files, bundle, with_supplied=True, log=lines.append,
                   extra=[("capture_addon/" + addon.NAME, addon.BUILT), ("capture_addon/" + addon.STAMP, addon.BUILT_STAMP)])
    root2, game2, options2, system2, work2 = sandbox(tmp, "pc2", [bundle])
    real = (addon.is_built, addon.find_cmake, sources.MODS_DIR)
    addon.is_built, addon.find_cmake, sources.MODS_DIR = (lambda: False), (lambda: None), os.path.join(tmp, "empty")
    try:
        n2 = inst.install("rdr2", game2, options2, [bundle], system=system2, work=work2, log=lines.append)
    finally:
        addon.is_built, addon.find_cmake, sources.MODS_DIR = real
    assert n2 == n and sha256_file(os.path.join(game2, "capture_mod.addon64")) == sha256_file(addon.BUILT)
    assert sha256_file(os.path.join(game2, "ScriptHookRDR2.dll")) == sha256_file(os.path.join(game, "ScriptHookRDR2.dll"))
    print("B ok: a bundle (%.1f MB) installed a second sandbox with no archives and no build tools" % (os.path.getsize(bundle) / 1e6))

    inst.uninstall("rdr2", work=work, log=lines.append)
    after = tree(root)
    after = {k: v for k, v in after.items() if not k.startswith("work")}
    left = sorted(set(after) ^ set(before))
    shared = [os.path.join("ProgramData", "ReShade", n) for n in ("ReShade64.dll", "ReShade64.json")]
    assert left == shared, left  # the machine-wide ReShade files stay: other games may use them
    assert 'vSync value="1"' in open(options["settings_xml"]).read()
    print("B ok: uninstall put the first sandbox back (game folder and settings; machine-wide ReShade files left)")

    opti = os.path.join(sources.MODS_DIR, "OptiScaler-DLSS5-1.3.0-win-x64.zip")
    if not os.path.exists(opti):
        print("B skipped OptiScaler: its release is not in out/mods")
        return
    root3, game3, options3, system3, work3 = sandbox(tmp, "pc3", mods)
    model = os.path.join(tmp, "model", "nvngx_dlssnr.dll")
    os.makedirs(os.path.dirname(model))
    open(model, "wb").write(b"stand-in for NVIDIA's model")
    with open(os.path.join(game3, "ReShade.ini"), "wb") as f:   # someone's own ReShade settings
        f.write(b"[GENERAL]\r\nEffectSearchPaths=C:\\Elsewhere\\Shaders\\**\r\n[INPUT]\r\nKeyOverlay=45,0,0,0\r\n")
    open(os.path.join(game3, "ReShadePreset.ini"), "wb").write(b"Techniques=Mine@Mine.fx\r\n")
    before3 = tree(game3)
    n3 = inst.install("rdr2", game3, dict(options3, optiscaler=True), mods + [model], system=system3, work=work3,
                      log=lines.append)
    for rel in ("OptiScaler.asi", "OptiScaler.ini", "nvngx.dll_dlssnr.dll", "nvngx_dlssnr.dll"):
        assert os.path.exists(os.path.join(game3, rel)), rel
    oi = plan.Ini(os.path.join(game3, "OptiScaler.ini"))
    got = {k: oi.get(sec, k2) for k, (sec, k2) in {"fg": ("FrameGen", "Enabled"), "nr": ("DlssNr", "Enabled"),
           "cache": ("DlssNr", "CacheEnabled"), "up": ("Upscalers", "VulkanUpscaler"), "f6": ("DlssNr", "CompareKey"),
           "menu": ("Menu", "ShortcutKey"), "dlss": ("DLSS", "Enabled")}.items()}
    assert got == {"fg": "false", "nr": "true", "cache": "false", "up": "dlss", "f6": "-1", "menu": "0x23", "dlss": "auto"}, got
    assert (oi.get("DlssNr", "SkinStructure"), oi.get("QualityOverrides", "QualityRatioOverrideEnabled"),
            oi.get("QualityOverrides", "QualityRatioQuality")) == ("2", "true", "1.0"), "skin structure 2, DLAA by default"
    ri = plan.Ini(os.path.join(game3, "ReShade.ini"))
    assert ri.get("GENERAL", "EffectSearchPaths") == r"C:\Elsewhere\Shaders\**,.\reshade-shaders\Shaders\**"
    assert ri.get("INPUT", "KeyOverlay") == "45,0,0,0", "ReShade's own menu key is left alone"
    # the user changes an OptiScaler setting and the preset in game; a reinstall keeps the first and backs up the second
    oi.set("DlssNr", "Style", "1"); oi.save()
    open(os.path.join(game3, "ReShadePreset.ini"), "ab").write(b"Tweaked=1\r\n")
    assert inst.install("rdr2", game3, dict(options3, optiscaler=True), mods + [model], system=system3, work=work3,
                        log=lines.append) == 1
    assert plan.Ini(os.path.join(game3, "OptiScaler.ini")).get("DlssNr", "Style") == "1"
    assert any("kept    your changed ReShadePreset.ini" in l for l in lines), "the tweaked preset is backed up"
    inst.uninstall("rdr2", work=work3, log=lines.append)
    after3 = tree(game3)
    assert after3 == before3, (sorted(set(after3) ^ set(before3)), [k for k in before3 if after3.get(k) != before3[k]])
    print("B ok: --optiscaler in a third sandbox (%d steps): files, capture settings, your ReShade key and search paths "
          "kept; a reinstall kept your OptiScaler setting and backed up your preset edits; uninstall put it all back" % n3)


def part_c(tmp, mods):
    """The default install (Direct3D 12, OptiScaler, ray tracing, 2560x1440) into a sandbox, again
    (nothing to do), then with both turned off, then uninstalled."""
    lines = []
    root = os.path.join(tmp, "pc4")
    game = os.path.join(root, "game")
    os.makedirs(game)
    open(os.path.join(game, "RDR2.exe"), "wb").write(b"not the real game")
    xml = os.path.join(root, "system.xml")
    open(xml, "wb").write(b'<Settings>\r\n  <vSync value="1" />\r\n  <pauseOnFocusLoss value="true" />\r\n'
                          b'  <dlssIndex value="0" />\r\n  <dlssQuality value="5" />\r\n  <windowed value="0" />\r\n'
                          b'  <screenWidthWindowed value="3840" />\r\n  <screenHeightWindowed value="2160" />\r\n'
                          b'  <API>kSettingAPI_Vulkan</API>\r\n</Settings>\r\n')
    model = os.path.join(root, "model", "nvngx_dlssnr.dll")
    os.makedirs(os.path.dirname(model))
    open(model, "wb").write(b"stand-in for NVIDIA's model")
    opts = {"exchange_dir": os.path.join(root, "exchange"), "settings_xml": xml}   # everything else: the defaults
    system, work = FakeSystem(root), os.path.join(root, "work")
    before = tree(game)
    xml_before = open(xml, "rb").read()
    n = inst.install("rdr2", game, opts, mods + [model], system=system, work=work, log=lines.append)
    for rel in ("ReShade.asi", "RealityFX.addon64", os.path.join("RealityFX", "passes", "rt_gi.ps.cso"),
                os.path.join("reshade-shaders", "Shaders", "RealityRedemption2.fx"), "ReShadePreset.rt_off.ini",
                "ReShadePreset.mod_off.ini", "OptiScaler.asi", "nvngx.dll_dlssnr.dll", "nvngx_dlssnr.dll"):
        assert os.path.exists(os.path.join(game, rel)), rel
    assert not os.path.exists(os.path.join(game, "dxgi.dll")), "ReShade loads as ReShade.asi, not dxgi.dll"
    assert "RealityRedemption2@RealityRedemption2.fx" in open(os.path.join(game, "ReShadePreset.ini")).read()
    ri = plan.Ini(os.path.join(game, "ReShade.ini"))
    assert ri.get("GENERAL", "PresetShortcutKeys") == "125,0,0,0,126,0,0,0,127,0,0,0"
    assert plan.Ini(os.path.join(game, "OptiScaler.ini")).get("Plugins", "LoadReshade") == "false"
    x = open(xml).read()
    for want in ("<API>kSettingAPI_DX12</API>", 'dlssIndex value="2"', 'dlssQuality value="2"', 'windowed value="1"',
                 'screenWidthWindowed value="2560"', 'screenHeightWindowed value="1440"'):
        assert want in x, want
    assert inst.install("rdr2", game, opts, mods + [model], system=system, work=work, log=lines.append) == 0
    print("C ok: the default install (DX12, OptiScaler, ray tracing, 2560x1440) in a sandbox: %d steps, then nothing to do" % n)

    off = dict(opts, optiscaler=False, ray_tracing=False)
    inst.install("rdr2", game, off, mods + [model], system=system, work=work, log=lines.append)
    assert not os.path.exists(os.path.join(game, "OptiScaler.asi")) and not os.path.exists(os.path.join(game, "RealityFX.addon64"))
    visual = os.path.join(os.path.dirname(inst.installer("rdr2").__file__), "visual", "ReShadePreset.ini")
    assert sha256_file(os.path.join(game, "ReShadePreset.ini")) == sha256_file(visual), "the plain visual set's preset is back"
    assert inst.install("rdr2", game, off, mods + [model], system=system, work=work, log=lines.append) == 0
    print("C ok: --no-optiscaler --no-ray-tracing: neither is loaded, the plain preset is back, then nothing to do")

    inst.uninstall("rdr2", work=work, log=lines.append)
    after = tree(game)
    assert after == before, (sorted(set(after) ^ set(before))[:10], [k for k in before if after.get(k) != before[k]])
    assert open(xml, "rb").read() == xml_before, "the game's settings are back"
    print("C ok: uninstall put the game folder and its settings back")


def part_d(tmp, mods):
    """The GTA V Legacy plan in a sandbox: install, again (nothing to do), uninstall."""
    lines = []
    root = os.path.join(tmp, "gtav")
    game = os.path.join(root, "game")
    os.makedirs(game)
    open(os.path.join(game, "GTA5.exe"), "wb").write(b"not the real game")
    xml = os.path.join(root, "settings.xml")
    open(xml, "wb").write(b'<Settings>\r\n  <DX_Version value="2" />\r\n  <ScreenWidth value="3072" />\r\n'
                          b'  <ScreenHeight value="1728" />\r\n  <Windowed value="0" />\r\n  <VSync value="1" />\r\n'
                          b'  <PauseOnFocusLoss value="1" />\r\n</Settings>\r\n')
    exchange = os.path.join(root, "exchange")
    opts = {"exchange_dir": exchange, "settings_xml": xml}
    system, work = FakeSystem(root), os.path.join(root, "work")
    before, xml_before = tree(game), open(xml, "rb").read()
    n = inst.install("gtav", game, opts, mods, system=system, work=work, log=lines.append)
    for rel in ("ScriptHookV.dll", "dinput8.dll", "NativeTrainer.asi", "ScriptHookV.dev", "RedLua.asi", "lua51.dll",
                os.path.join("RedLua", "natives.json"), os.path.join("RedLua", "Settings.json"),
                os.path.join("RedLua", "Scripts", "capture_loader.lua"), "ReShade.asi", "capture_mod.addon64",
                "ReShade.ini", "ReShadePreset.capture.ini"):
        assert os.path.exists(os.path.join(game, rel)), rel
    loader = open(os.path.join(game, "RedLua", "Scripts", "capture_loader.lua"), encoding="utf-8").read()
    assert "local OUT_DIR = '%s'" % exchange.replace("\\", "\\\\") in loader, "the loader watches GTA V's own exchange folder"
    assert open(os.path.join(game, "commandline.txt")).read().strip() == "-nobattleye"
    assert plan.Ini(os.path.join(game, "ReShade.ini")).get("CAPTURE_MOD", "OutputDir") == exchange
    x = open(xml).read()
    for want in ('VSync value="0"', 'PauseOnFocusLoss value="0"', 'Windowed value="1"', 'ScreenWidth value="2560"',
                 'ScreenHeight value="1440"'):
        assert want in x, want
    assert inst.install("gtav", game, opts, mods, system=system, work=work, log=lines.append) == 0
    inst.uninstall("gtav", work=work, log=lines.append)
    after = tree(game)
    assert after == before, (sorted(set(after) ^ set(before))[:10], [k for k in before if after.get(k) != before[k]])
    assert open(xml, "rb").read() == xml_before, "the game's settings are back"
    print("D ok: the GTA V plan in a sandbox: %d steps, then nothing to do; uninstall put it all back" % n)


def part_e(tmp, mods, shv_loader):
    """The GTA V Enhanced plan in a sandbox: Ultimate ASI Loader as xinput1_4.dll (Script Hook V's
    own dinput8.dll, as its readme installs it, goes), and ReShade's config outside the game folder
    (the game denies writes to its folder while it runs)."""
    lines = []
    root = os.path.join(tmp, "gtave")
    game = os.path.join(root, "game")
    os.makedirs(game)
    open(os.path.join(game, "GTA5_Enhanced.exe"), "wb").write(b"not the real game")
    open(os.path.join(game, "dinput8.dll"), "wb").write(shv_loader.read())   # a manual Script Hook V install
    xml = os.path.join(root, "settings.xml")
    open(xml, "wb").write(b'<Settings>\r\n  <ScreenWidth value="3072" />\r\n  <ScreenHeight value="1728" />\r\n'
                          b'  <Windowed value="0" />\r\n  <VSync value="1" />\r\n  <PauseOnFocusLoss value="1" />\r\n'
                          b'  <FrameGenType value="1" />\r\n  <ResScalingType value="0" />\r\n'
                          b'  <dlssQuality value="0" />\r\n  <dlssSharpen value="0.500000" />\r\n'
                          b'  <Raytracing_Enabled value="false" />\r\n  <MotionBlurStrength value="1.000000" />\r\n'
                          b'</Settings>\r\n')
    exchange = os.path.join(root, "exchange")
    base = os.path.join(exchange, "reshade")
    nve_json = os.path.join(root, "AppData", "NVE", "settings-gen9.json")
    # Enhanced's defaults include OptiScaler and NVE (6.5 GB); the plain plan first, OptiScaler and
    # the visual presets below, NVE as a dry run only
    opts = {"exchange_dir": exchange, "settings_xml": xml, "optiscaler": False, "preset": False, "graphics_mod": False,
            "graphics_mod_settings": nve_json}
    system, work = FakeSystem(root), os.path.join(root, "work")
    before, xml_before = tree(game), open(xml, "rb").read()
    n = inst.install("gtave", game, opts, mods, system=system, work=work, log=lines.append)
    for rel in ("ScriptHookV.dll", "xinput1_4.dll", "NativeTrainer.asi", "RedLua.asi", "ReShade.asi",
                "capture_mod.addon64", "ReShade.ini", os.path.join("RedLua", "Scripts", "capture_loader.lua")):
        assert os.path.exists(os.path.join(game, rel)), rel
    assert not os.path.exists(os.path.join(game, "dinput8.dll")), "Script Hook V's own loader is gone (a second loader)"
    assert not os.path.exists(os.path.join(game, "ReShadePreset.capture.ini")), "the preset lives in ReShade's base folder"
    gi = plan.Ini(os.path.join(game, "ReShade.ini"))
    assert gi.get("INSTALL", "BasePath") == base and gi.get("CAPTURE_MOD", "OutputDir") is None
    bi = plan.Ini(os.path.join(base, "ReShade.ini"))
    assert bi.get("CAPTURE_MOD", "OutputDir") == exchange
    assert bi.get("ADDON", "AddonPath") == game, "ReShade finds the add-on in the game folder"
    assert bi.get("GENERAL", "PresetPath") == ".\\ReShadePreset.capture.ini"
    assert os.path.exists(os.path.join(base, "ReShadePreset.capture.ini"))
    x = open(xml).read()
    assert "DX_Version" not in x, "Enhanced has no DX_Version setting"
    assert 'FrameGenType value="0"' in x and 'ResScalingType value="0"' in x, "no frame generation; upscaler left alone"
    assert 'Raytracing_Enabled value="true"' in x, "the game's ray tracing is on"
    assert 'MotionBlurStrength value="0.000000"' in x, "the game's motion blur is off"
    assert not os.path.exists(nve_json), "without the graphics mod its settings are left alone"
    assert inst.install("gtave", game, opts, mods, system=system, work=work, log=lines.append) == 0
    # NVE (the default): its files from the archive and its per-camera effects off, shown by a dry run
    dry, snapshot = [], tree(game)
    try:
        inst.install("gtave", game, dict(opts, graphics_mod=True), mods, dry_run=True, system=system, work=work,
                     log=dry.append)
        nve_seen = "found"
    except inst.InstallError as e:
        assert "NaturalVision Enhanced" in str(e), e
        nve_seen = "archive not on this machine"
    for want in ("[graphicsmod] nve: its files into the game folder", "graphics.enable_lens_effects=false",
                 "graphics.LateralChromaticAberration=false"):
        assert any(want in line for line in dry), want
    assert not os.path.exists(nve_json) and tree(game) == snapshot, "a dry run changes nothing"
    note = ", NVE planned (dry run; %s)" % nve_seen
    probe = sources.Files(sources.load_locks(sources.SHARED_LOCK, inst.installer("gtave").LOCK), roots=mods)
    if probe.ref("optiscaler_dlss5", "OptiScaler.dll").found and probe.ref("nvngx_dlssnr", "nvngx_dlssnr.dll").found:
        inst.install("gtave", game, dict(opts, optiscaler=True), mods, system=system, work=work, log=lines.append)
        assert os.path.exists(os.path.join(game, "OptiScaler.asi")), "OptiScaler loads through the ASI loader"
        x = open(xml).read()
        assert 'ResScalingType value="4"' in x, "the game's DLSS on, for OptiScaler to take over"
        mode = inst.installer("gtave").ENHANCED["dlss_mode"]
        assert 'dlssQuality value="%s"' % gtav_install.DLSS_MODES[mode] in x and 'dlssSharpen value="0.800000"' in x, \
            "the DLSS mode and sharpening are pinned"
        oi = plan.Ini(os.path.join(game, "OptiScaler.ini"))
        assert oi.get("DlssNr", "Enabled") == "true" and oi.get("Upscalers", "Dx12Upscaler") == "dlss"
        other = "quality" if mode == "dlaa" else "dlaa"
        inst.install("gtave", game, dict(opts, optiscaler=True, dlss_mode=other), mods, system=system, work=work,
                     log=lines.append)
        assert 'dlssQuality value="%s"' % gtav_install.DLSS_MODES[other] in open(xml).read(), "--dlss-mode"
        try:
            inst.install("gtave", game, dict(opts, optiscaler=True, dlss_mode="ultra_quality"), mods, dry_run=True,
                         system=system, work=work, log=lines.append)
            raise AssertionError("an unknown DLSS mode was taken")
        except ValueError:
            pass
        note += ", --optiscaler turns the game's DLSS on in mode %s (--dlss-mode %s too)" % (mode, other)
    else:
        note += " (--optiscaler not tried: OptiScaler or nvngx_dlssnr.dll not found)"
    if all(probe.ref(m, f).found for m, f in (("quint", "qUINT_lightroom.fx"), ("astrayfx", "Clarity.fx"),
                                              ("reshade_shaders", "DisplayDepth.fx"))):
        inst.install("gtave", game, dict(opts, preset=True), mods, system=system, work=work, log=lines.append)
        for rel in ("ReShadePreset.ini", "ReShadePreset.capture.ini", "ReShadePreset.grade_ss.ini", "ReShadePreset.depth.ini",
                    "ReShadePreset.grade.ini", os.path.join("reshade-shaders", "Shaders", "qUINT_lightroom.fx"),
                    os.path.join("reshade-shaders", "Shaders", "Clarity.fx")):
            assert os.path.exists(os.path.join(base, rel)), rel
        bi = plan.Ini(os.path.join(base, "ReShade.ini"))
        assert bi.get("GENERAL", "PresetPath") == ".\\ReShadePreset.ini", "the grade with Clarity is the capture preset"
        assert bi.get("GENERAL", "PresetShortcutKeys") == "125,0,0,0,126,0,0,0,127,0,0,0,128,0,0,0,129,0,0,0"
        cap = open(os.path.join(base, "ReShadePreset.ini")).read()
        assert "Techniques=Clarity@Clarity.fx,Lightroom@qUINT_lightroom.fx" in cap and "MXAO" not in cap
        inst.install("gtave", game, dict(opts, preset=False), mods, system=system, work=work, log=lines.append)
        assert plan.Ini(os.path.join(base, "ReShade.ini")).get("GENERAL", "PresetPath") == ".\\ReShadePreset.capture.ini"
        note += ", --preset installs the five presets on F14-F18 (grade + Clarity the capture preset)"
    inst.uninstall("gtave", work=work, log=lines.append)
    after = tree(game)
    assert after == before, (sorted(set(after) ^ set(before))[:10], [k for k in before if after.get(k) != before[k]])
    assert open(xml, "rb").read() == xml_before, "the game's settings are back"
    assert not os.path.exists(os.path.join(base, "ReShadePreset.capture.ini"))
    print("E ok: the GTA V Enhanced plan in a sandbox: %d steps (ASI loader as xinput1_4.dll, Script Hook V's loader "
          "removed, ReShade's config in %s), then nothing to do%s; uninstall put it all back"
          % (n, os.path.relpath(base, root), note))


def part_f(tmp, mods, system_class, label):
    """The Cyberpunk 2077 plan in a sandbox: install, again (nothing to do), uninstall."""
    import json
    from adapters.cyberpunk import paths as cp, settings as cs
    lines = []
    root = os.path.join(tmp, "cyberpunk_" + label)
    game = os.path.join(root, "game")
    os.makedirs(os.path.join(game, "bin", "x64"))
    open(os.path.join(game, cp.EXE), "wb").write(b"not the real game")
    # a settings file as the game writes it, on other settings than the capture profile
    wanted = cs.profile((2560, 1440), desktop=(3840, 2160))
    groups = {}
    for group, name, value in wanted:
        if (group, name) in cs.LISTS:
            values = cs.LISTS[(group, name)]
            other = next(v for v in values if v != value)
            option = {"name": name, "type": "string_list", "values": values, "value": other, "index": values.index(other)}
        elif value in ("true", "false"):
            option = {"name": name, "type": "bool", "value": value != "true"}
        else:
            option = {"name": name, "type": "float", "value": 0.5}
        groups.setdefault(group, []).append(option)
    user = os.path.join(root, "UserSettings.json")
    with open(user, "w", encoding="utf-8") as f:
        json.dump({"data": [{"group_name": g, "options": o} for g, o in groups.items()]}, f)
    opts = {"user_settings": user, "desktop": (3840, 2160)}
    system, work = system_class(root), os.path.join(root, "work")
    before, user_before = tree(game), open(user, "rb").read()
    n = inst.install("cyberpunk", game, opts, mods, system=system, work=work, log=lines.append)
    plugins = os.path.join(game, "bin", "x64", "plugins")
    exchange = cp.exchange(game)
    for rel in (os.path.join("bin", "x64", "version.dll"), os.path.join("bin", "x64", "winmm.dll"),
                os.path.join("red4ext", "RED4ext.dll"), os.path.join("red4ext", "plugins", "Codeware", "Codeware.dll"),
                os.path.join("engine", "tools", "scc.exe")):
        assert os.path.exists(os.path.join(game, rel)), rel
    for rel in ("cyber_engine_tweaks.asi", "ReShade.asi", "ReShade.ini", "ReShadePreset.capture.ini", addon.NAME, clock.NAME,
                clock.INI, os.path.join("cyber_engine_tweaks", "mods", cp.MOD_NAME, "init.lua")):
        assert os.path.exists(os.path.join(plugins, rel)), rel
    assert os.path.isdir(os.path.join(exchange, "jobs"))
    # what the game reads as a path is written as the game sees it; everything else as it is here
    assert plan.Ini(os.path.join(plugins, "ReShade.ini")).get("CAPTURE_MOD", "OutputDir") == system.game_path(exchange)
    ini = plan.Ini(os.path.join(plugins, clock.INI))
    assert ini.get("clock", "Control") == system.game_path(os.path.join(exchange, "clock.txt"))
    assert ini.get("clock", "Status") == system.game_path(os.path.join(exchange, "clock_status.txt"))
    assert ini.get("clock", "Modules") == "Cyberpunk2077.exe,bink2w64.dll"
    assert plan.Ini(os.path.join(plugins, "ReShade.ini")).get("GENERAL", "PresetPath") == ".\\ReShadePreset.capture.ini"
    assert not cs.file_changes(user, wanted), "the capture settings are in the game's settings file"
    assert inst.install("cyberpunk", game, opts, mods, system=system, work=work, log=lines.append) == 0
    inst.uninstall("cyberpunk", work=work, log=lines.append)
    after = tree(game)
    assert after == before, (sorted(set(after) ^ set(before))[:10], [k for k in before if after.get(k) != before[k]])
    assert open(user, "rb").read() == user_before, "the game's settings are back"
    print("F ok (%s): the Cyberpunk 2077 plan in a sandbox: %d steps, then nothing to do; uninstall put it all back" % (label, n))


def part_g(tmp, mods, system_class, label):
    """The Witcher 3 plan in a sandbox: install, again (nothing to do), uninstall."""
    from adapters.witcher3 import paths as wp, settings as ws
    lines = []
    root = os.path.join(tmp, "witcher3_" + label)
    game = os.path.join(root, "game")
    os.makedirs(os.path.join(game, os.path.dirname(wp.EXE)))
    open(os.path.join(game, wp.EXE), "wb").write(b"not the real game")
    base = os.path.join(game, "bin", "config", "base")
    os.makedirs(base)
    general = os.path.join(base, "general.ini")
    open(general, "w", newline="\r\n").write("[General]\nConfigVersion=7\n")
    # a settings file as the game writes it, on other settings than the capture profile
    wanted = ws.profile((2560, 1440))
    user = os.path.join(root, "user", "dx12user.settings")
    os.makedirs(os.path.dirname(user))
    ini = plan.Ini(user)
    for section, key, value, _ in wanted:
        ini.set(section, key, "false" if value == "true" else "true" if value == "false" else "1")
    ini.save()
    exchange = os.path.join(root, "user", "capture_mod")
    opts = {"user_settings": user, "exchange_dir": exchange}     # everything else: the defaults (DLSS 5 on)
    model = os.path.join(root, "model", "nvngx_dlssnr.dll")
    os.makedirs(os.path.dirname(model))
    open(model, "wb").write(b"stand-in for NVIDIA's model")
    mods = list(mods) + [model]
    system, work = system_class(root), os.path.join(root, "work")
    before, user_before = tree(game), open(user, "rb").read()
    assert ws.differences(user, wanted), "the sandbox starts on other settings"
    n = inst.install("witcher3", game, opts, mods, system=system, work=work, log=lines.append)
    b = wp.bin_dir(game)
    for rel in ("dxgi.dll", "ReShade.ini", addon.NAME, "winmm.dll", "OptiScaler.ini", "nvngx.dll_dlssnr.dll", "nvngx_dlssnr.dll"):
        assert os.path.exists(os.path.join(b, rel)), rel
    oi = plan.Ini(os.path.join(b, "OptiScaler.ini"))
    assert oi.get("DlssNr", "SkinStructure") == "2" and oi.get("Upscalers", "Dx12Upscaler") == "dlss"
    script = os.path.join(wp.scripts_dir(game), "capture_mod.ws")
    assert open(script, encoding="utf-8").read() == open(os.path.join(os.path.dirname(os.path.abspath(
        inst.installer("witcher3").__file__)), "ws", "capture_mod.ws"), encoding="utf-8").read()
    assert plan.Ini(general).get("General", "DBGConsoleOn") == "true"
    assert plan.Ini(general).get("General", "ConfigVersion") == "7", "the rest of the game's file is kept"
    assert os.path.isdir(exchange)
    # what the game reads as a path is written as the game sees it
    assert plan.Ini(os.path.join(b, "ReShade.ini")).get("CAPTURE_MOD", "OutputDir") == system.game_path(exchange)
    assert not ws.differences(user, wanted), "the capture settings are in the game's settings file"
    assert inst.install("witcher3", game, opts, mods, system=system, work=work, log=lines.append) == 0
    # --no-optiscaler: OptiScaler is no longer loaded (winmm.dll goes), the rest stays
    assert inst.install("witcher3", game, dict(opts, optiscaler=False), mods, system=system, work=work, log=lines.append) == 1
    assert not os.path.exists(os.path.join(b, "winmm.dll")) and os.path.exists(os.path.join(b, "dxgi.dll"))
    inst.uninstall("witcher3", work=work, log=lines.append)
    after = tree(game)
    assert after == before, (sorted(set(after) ^ set(before))[:10], [k for k in before if after.get(k) != before[k]])
    assert open(user, "rb").read() == user_before, "the game's settings are back"
    print("G ok (%s): the Witcher 3 plan in a sandbox: %d steps (DLSS 5 as winmm.dll), then nothing to do; "
          "--no-optiscaler unloads it; uninstall put it all back" % (label, n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", action="append", default=[])
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        part_a(os.path.join(tmp, "a"))
    with tempfile.TemporaryDirectory() as tmp:
        part_p(os.path.join(tmp, "p"))
    with tempfile.TemporaryDirectory() as tmp:
        probe = sources.Files(sources.load_locks(sources.SHARED_LOCK, inst.installer("rdr2").LOCK), roots=a.mods)
        need = [("scripthook_rdr2", "ScriptHookRDR2.dll"), ("redlua", "RedLua.asi"), ("reshade", "ReShade64.dll"),
                ("sweetfx", "Vibrance.fx"), ("reshade_shaders", "ReShade.fxh")]
        if all(probe.ref(m, f).found for m, f in need) and addon.is_built():
            part_b(tmp, a.mods)
            rt = [("reality_redemption2", "RealityFX.addon64"), ("optiscaler_dlss5", "OptiScaler.dll")]
            if all(probe.ref(m, f).found for m, f in rt):
                part_c(tmp, a.mods)
            else:
                print("C skipped: the OptiScaler and Reality Redemption 2 archives are not in out/mods")
        else:
            print("B skipped: the real mod files are not available (pass --mods <folder>) or the add-on is not built")
    with tempfile.TemporaryDirectory() as tmp:
        probe = sources.Files(sources.load_locks(sources.SHARED_LOCK, inst.installer("gtav").LOCK), roots=a.mods)
        need = [("scripthook_v", "ScriptHookV.dll"), ("redlua_v", "RedLua.asi"), ("reshade", "ReShade64.dll")]
        if all(probe.ref(m, f).found for m, f in need) and addon.is_built():
            part_d(tmp, a.mods)
            if probe.ref("ultimate_asi_loader", "dinput8.dll").found:
                part_e(tmp, a.mods, probe.ref("scripthook_v", "dinput8.dll"))
            else:
                print("E skipped: Ultimate ASI Loader is not in out/mods")
        else:
            print("D skipped: Script Hook V, RedLua for GTA V or ReShade is not in out/mods (or the add-on is not built)")
            print("E skipped: as D")
    with tempfile.TemporaryDirectory() as tmp:
        probe = sources.Files(sources.load_locks(sources.SHARED_LOCK, inst.installer("cyberpunk").LOCK), roots=a.mods,
                              extra_names=addon.EXTRA_NAMES + clock.EXTRA_NAMES)
        need = [("cyber_engine_tweaks", "bin/x64/version.dll"), ("red4ext", "bin/x64/winmm.dll"), ("reshade", "ReShade64.dll")]
        ours = all(part.is_built() or (probe.named(part.NAME) and probe.named(part.STAMP)) for part in (addon, clock))
        if all(probe.ref(m, f).found for m, f in need) and ours:
            part_f(tmp, a.mods, FakeSystem, "paths as they are")
            part_f(tmp, a.mods, FakeProton, "paths as under Proton")
        else:
            print("F skipped: Cyber Engine Tweaks, RED4ext or ReShade is not in out/mods, or our add-on and clock plug-in "
                  "are neither built nor in a bundle there")
    with tempfile.TemporaryDirectory() as tmp:
        probe = sources.Files(sources.load_locks(sources.SHARED_LOCK, inst.installer("witcher3").LOCK), roots=a.mods,
                              extra_names=addon.EXTRA_NAMES)
        ours = addon.is_built() or (probe.named(addon.NAME) and probe.named(addon.STAMP))
        if probe.ref("reshade", "ReShade64.dll").found and probe.ref("optiscaler_dlss5", "OptiScaler.dll").found and ours:
            part_g(tmp, a.mods, FakeSystem, "paths as they are")
            part_g(tmp, a.mods, FakeProton, "paths as under Proton")
        else:
            print("G skipped: ReShade or OptiScaler is not in out/mods, or our add-on is neither built nor in a bundle there")


if __name__ == "__main__":
    main()
