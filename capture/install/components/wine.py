"""What a Windows game needs from Wine itself, where it runs under Proton (capture/host). On
Windows these give no steps.

DLL overrides: a script layer's loader is a DLL in the game folder with a system DLL's name
(dinput8.dll, xinput1_4.dll, version.dll); Wine loads its own built-in DLL of that name unless
told otherwise. The override is kept per exe in the prefix's registry, so it holds however the
game is started, by us or by a Steam client in the prefix.
"""
import os
import re
import time

from ..plan import Call


def _registry_has(prefix_dir, exe_name, dll, order):
    """Reads the prefix's user.reg (text, written when Wine's server ends or every few seconds)."""
    try:
        text = open(os.path.join(prefix_dir, "pfx", "user.reg"), encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    key = r"[Software\\Wine\\AppDefaults\\%s\\DllOverrides]" % exe_name
    i = text.lower().find(key.lower())
    if i < 0:
        return False
    block = text[i:].split("\n\n", 1)[0]
    return re.search(r'^"%s"="%s"\s*$' % (re.escape(dll), re.escape(order)), block, re.M | re.I) is not None


def dll_overrides(ctx, exe_name, dlls, order="native,builtin"):
    """Steps that make Wine load the game folder's own copy of each DLL in `dlls` for this exe."""
    if not getattr(ctx.system, "wine", False):
        return []
    from ... import host
    game = ctx.system.game

    def step(dll):
        def status(c):
            return ("ok", "set") if _registry_has(host.prefix(game), exe_name, dll, order) else ("todo", "set in the prefix's registry")

        def apply(c):
            host.app_overrides(game, exe_name, {dll: order})
            # a Wine server that keeps running (a Steam client in the prefix) writes the registry
            # to its file every half minute: wait for it, since status() reads the file
            t = time.time()
            while time.time() - t < 90 and not _registry_has(host.prefix(game), exe_name, dll, order):
                time.sleep(3)

        return Call("Wine: %s loads its own %s.dll (%s; the script layer's loader)" % (exe_name, dll, order), status, apply,
                    tag="mods", closed=False)

    return [step(d) for d in dlls]
