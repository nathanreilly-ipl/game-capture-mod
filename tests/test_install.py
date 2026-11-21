"""The installer without touching a real game.

    uv run --project . python tests/test_install.py [--mods <folder with the real mod archives>]

A. The framework on made-up files: steps, dry run, backups, the install record, uninstall,
   files found by hash inside archives, missing files stop the install before any change.
B. The RDR2 plan in a sandbox (a fake game folder, a fake ProgramData and registry), when the
   real mod files are available (--mods, or out/mods): install, install again (nothing to do),
   uninstall (everything back), then a bundle made from the sandbox installs into a second one
   on a "machine without build tools". With the OptiScaler release in out/mods, a third sandbox
   gets --optiscaler (a stand-in for NVIDIA's model), then its own preset edits survive a reinstall.
"""
import argparse
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture import install as inst  # noqa: E402
from capture.install import plan, sources  # noqa: E402
from capture.install.components import addon  # noqa: E402
from capture.util import sha256_bytes, sha256_file, write_json  # noqa: E402


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mods", action="append", default=[])
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        part_a(os.path.join(tmp, "a"))
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


if __name__ == "__main__":
    main()
