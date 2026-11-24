"""Talking to our script in Kingdom Come: Deliverance through the game's console (-devmode).

The shared console client (adapters/common/console.py) types each command; what is the game's own:

    in    a Lua line, `#CaptureMod.cmd(<seq>, "<op>", args...)`; CryEngine's console runs a line
          that starts with # as Lua. raw() sends any Lua the same way, before our script exists.
    out   lines holding "[CaptureMod] " in kcd.log in the game folder (System.LogAlways), there at
          once (2026-11-23).

The console takes a line of at most about 250 characters (a 252-character line ran, a 332-character
one did not; 2026-11-23), so a longer command goes over in pieces: CaptureMod.chunk(seq, '<piece>')
appends each to a buffer and answers, CaptureMod.run(seq) then runs CaptureMod.cmd(seq, <buffer>).
Ctrl+V pastes into the console; the console key is the one left of 1.
"""
import os

from ..common import frames
from ..common.console import ConsoleSession, Reply, fmt, pack, parse_kv, vec  # noqa: F401 (used by callers)
from . import paths

MAX_LINE = 240      # characters in one console line, with a margin
PIECE = 150         # characters of a command per piece, before escaping


def lua_arg(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return fmt(value)
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def lua_quote(text):
    return "'%s'" % text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


class Session(ConsoleSession):
    GAME_TITLE = "Kingdom Come: Deliverance"

    def __init__(self, log=print, key_hold=0.02, key_gap=0.02):
        super().__init__(paths.EXE_NAME, paths.WINDOW_CLASS, paths.game_log, paths.exchange, log, key_hold, key_gap)

    def command_text(self, op, seq, args):
        if op == "raw":       # any Lua; it must log its own answer lines for seq
            return "#" + args[0].replace("{seq}", str(seq))
        if op == "_reset":
            return "#CaptureMod.reset(%d)" % seq
        if op == "_chunk":
            return "#CaptureMod.chunk(%d,%s)" % (seq, lua_quote(args[0]))
        if op == "_run":
            return "#CaptureMod.run(%d)" % seq
        return "#CaptureMod.cmd(%s)" % ", ".join([str(seq), lua_arg(op)] + [lua_arg(a) for a in args])

    def cmd(self, op, *args, **kw):
        if op.startswith("_") or op == "raw":
            return super().cmd(op, *args, **kw)
        body = ", ".join([lua_arg(op)] + [lua_arg(a) for a in args])
        if len("#CaptureMod.cmd(%d, %s)" % (self.seq + 1, body)) <= MAX_LINE:
            return super().cmd(op, *args, **kw)
        # too long for one console line: the arguments go over in pieces, then run
        super().cmd("_reset")
        for i in range(0, len(body), PIECE):
            r = super().cmd("_chunk", body[i:i + PIECE])
            if not r.ok:
                return r
        return super().cmd("_run", **kw)

    def console_open(self):
        """Whether the console is in the picture now, or None if no frame came. Open, it darkens the
        top half of the frame and ends in a solid black line right across it (a row of mean 0.0
        against 118.7 closed, 2026-11-23); a scene has no such row."""
        try:
            a = frames.shoot(self.exchange(), "console_check", after=1, timeout=5.0)
        except frames.FrameError:
            return None
        try:
            from PIL import Image
            import numpy as np
            with Image.open(a["path"]) as im:
                g = np.asarray(im.convert("L"), dtype=np.float32)
        finally:
            try:
                os.remove(a["path"])
            except OSError:
                pass
        h = g.shape[0]
        band = g[int(h * 0.05):int(h * 0.56)]
        return bool(((band.mean(axis=1) < 3.0) & (band.std(axis=1) < 3.0)).any())

    def missing_hint(self):
        return "is the game started with -devmode and our mod installed? "

    def raw(self, code, timeout=6.0):
        """Runs a short Lua expression in the game and returns its value as text, without our
        script (the line logs its own answer; no answer if it fails)."""
        wrapped = ('local r=tostring(%s) System.LogAlways("[CaptureMod] d|{seq}|"..r) '
                   'System.LogAlways("[CaptureMod] e|{seq}|ok|")' % code)
        r = self.cmd("raw", wrapped, timeout=timeout, check=False)
        return r.data[0] if r.data else None

    # --- long inputs as files (sys_PakPriority 0: Script.LoadScript reads loose files in Data) ----
    def put(self, name, lua_text):
        """Writes <game>\\Data\\capture_mod_in\\<name>.lua for our script to run (cm load)."""
        d = paths.inbox()
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(lua_text)
        os.replace(tmp, os.path.join(d, name + ".lua"))

    def send_numbers(self, name, values):
        """CaptureMod.inbox = {numbers...} through a file, then cm load."""
        body = ",".join("%.4f" % v for v in values)
        self.put(name, "CaptureMod.inbox = {%s}\n" % body)
        return self.cmd("load", name, timeout=20.0)

    def items(self, reply):
        """The items of a split answer ("<first>|a/b/c" data lines), in order."""
        out = {}
        for d in reply.data:
            first, _, body = d.partition("|")
            for k, item in enumerate(body.split("/") if body else []):
                out[int(first) + k] = item
        return [out[k] for k in sorted(out)]

    def reload_script(self, text):
        """Our script into the running game through a file (fast); falls back to console pieces."""
        self.put("capture_mod", text)
        r = self.cmd("raw", 'Script.LoadScript("capture_mod_in/capture_mod.lua",true,true) '
                     'System.LogAlways("[CaptureMod] e|{seq}|ok|")', check=False)
        if r.ok and self.hello():
            return r
        return self.load_lua(text, "capture_mod.lua")

    def load_lua(self, text, name="script"):
        """Loads Lua source into the running game without a restart: the text goes over in pieces
        into a buffer (each piece answered), then runs. Reloading our script this way replaces its
        commands; what it keeps in CaptureMod stays."""
        ack = 'System.LogAlways("[CaptureMod] e|{seq}|ok|")'
        self.cmd("raw", "CMB={} " + ack)
        i, size = 0, 110
        while i < len(text):
            piece = text[i:i + size]
            line = "CMB[#CMB+1]=%s %s" % (lua_quote(piece), ack)
            if len(line) > MAX_LINE - 1 and size > 20:
                size -= 20          # many characters to escape here: smaller pieces
                continue
            self.cmd("raw", line)
            i += len(piece)
            size = 110
        r = self.cmd("raw", 'local f,e=loadstring(table.concat(CMB),"%s") if f then f() end '
                     'System.LogAlways("[CaptureMod] e|{seq}|"..(f and "ok|" or "error|"..tostring(e)))' % name, check=False)
        return r

    def eval(self, code, timeout=10.0):
        """Any Lua (statements, or an expression) through our script, however long; its value as text."""
        r = self.cmd("eval", code, timeout=timeout)
        return r.data[0] if r.data else None
