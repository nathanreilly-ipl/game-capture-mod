"""Talking to our script in the running game (ws/capture_mod.ws), through the game's debug console.

WitcherScript cannot read or write files, so there is no request and answer file as in the other
games: adapters/common/console.py types each command into the debug console and reads its answer
from the scripts log. What is The Witcher 3's own:

    in    `cm_<op>(seq, args...)`, an exec function of our script; the console key is the one left
          of 1. The console takes 30,000 characters in one paste (2026-11-23), so long lists
          (rays, points) go in one command.
    out   lines "[CaptureMod] ..." in Documents\\The Witcher 3\\scriptslog.txt, which the game
          writes at once when started with -debugscripts.
    the console slides shut over about 0.2 s after its key: still in frames up to 0.16 s after a
          command's answer and gone at 0.24 s (probes/console_probe.py, 2026-11-23, 68 frames/s),
          so no picture is taken sooner than CLEAR_S after a command.
    Enter typed into the game opens its hub menu (the world map), which pauses the world and
          covers the picture (2026-11-23); the state's "menu" says so and the adapter closes it.
    the console echoes each command in bright green, which nothing in the game's world is: a
          frame shows whether the console is open (console_open).
"""
import os

from ..common import frames
from ..common.console import ConsoleSession, Reply, fmt, pack, parse_kv, vec  # noqa: F401 (used by callers)
from . import paths

CLEAR_S = 0.45


class Session(ConsoleSession):
    GAME_TITLE = "The Witcher 3"
    CLEAR_S = CLEAR_S

    def __init__(self, log=print, key_hold=0.02, key_gap=0.02):
        super().__init__(paths.EXE_NAME, paths.WINDOW_CLASS, paths.scripts_log, paths.exchange, log, key_hold, key_gap)

    def command_text(self, op, seq, args):
        return "cm_%s(%s)" % (op, ", ".join([str(seq)] + [fmt(a) for a in args]))

    def missing_hint(self):
        return "is the game started with -debugscripts, the debug console on and our script installed? "

    def console_open(self):
        """Whether the debug console is in the picture now, or None if no frame came. It is drawn
        over the top quarter of the frame, left two thirds, and the commands it ran are echoed
        there in bright green (2026-11-23)."""
        try:
            a = frames.shoot(self.exchange(), "console_check", after=1, timeout=5.0)
        except frames.FrameError:
            return None
        try:
            from PIL import Image
            import numpy as np
            with Image.open(a["path"]) as im:
                w, h = im.size
                arr = np.asarray(im.convert("RGB").crop((0, 0, int(w * 0.66), int(h * 0.24))), dtype=np.int16)
        finally:
            try:
                os.remove(a["path"])
            except OSError:
                pass
        green = (arr[..., 1] > 170) & (arr[..., 0] < 100) & (arr[..., 2] < 100)
        return float(green.mean()) > 0.0004
