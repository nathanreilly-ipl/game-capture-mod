"""A session with a game script driven through the game's own debug console. Game-agnostic.

For games whose scripts cannot read files (The Witcher 3) or should not be trusted to (Kingdom
Come: Deliverance), a command goes in through the game's console and its answer comes out through
a log file the game writes:

    in    the console key, the command pasted from the clipboard (Ctrl+V), Enter, the console key
          again. Each game says how a command is written (command_text) and which key opens its
          console.
    out   lines holding "[CaptureMod] " in the game's log (anywhere in the line: some games put a
          time first): data lines "d|<seq>|...", a state line "s|<seq>|key=value ..." and a last
          line "e|<seq>|ok|text" or "e|<seq>|error|text".

Keys only reach the game while its window is in front, like every key this repository sends. The
clipboard is replaced by each command. A console is usually drawn in the frame and closes over a
moment, so nothing is captured sooner than CLEAR_S after a command (console_clear_in).

If no answer comes, a key was missed or the console was in the other state (open when it was
taken for closed), so the command was typed into the game instead. Then the console key is
pressed again after a pause and the command sent again, up to four times; a game that can tell
from a frame whether its console is open (console_open) toggles only when it is. An answer whose
state says "menu=1" after a resend means the typed Enter opened the game's menu: close_menu closes
it with Esc, which is only pressed while the state says a menu is open.
"""
import os
import time

from capture.adapter import AdapterError

from . import frames, mem, window

PREFIX = "[CaptureMod] "


class Reply:
    def __init__(self, seq, ok, text, state, data):
        self.seq, self.ok, self.text, self.state, self.data = seq, ok, text, state, data

    def __repr__(self):
        return "Reply(%s, %s, %r, %d data lines)" % (self.seq, "ok" if self.ok else "error", self.text, len(self.data))


def parse_kv(text):
    """"a=1 b=x,y,z" -> {"a": "1", "b": "x,y,z"}; a last key may hold spaces (name=...)."""
    out, key = {}, None
    for part in text.split(" "):
        if "=" in part and part.split("=", 1)[0].isidentifier():
            key, value = part.split("=", 1)
            out[key] = value
        elif key is not None:
            out[key] += " " + part
    return out


def vec(text):
    return [float(v) for v in text.split(",")]


def fmt(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return ("%.6f" % value).rstrip("0").rstrip(".") or "0"
    return str(value)


def pack(numbers, digits=3):
    """Numbers for a script's list argument: underscores between them (consoles split on commas)."""
    f = "%%.%df" % digits
    return "_".join((f % n).rstrip("0").rstrip(".") or "0" for n in numbers)


class ConsoleSession:
    GAME_TITLE = "the game"
    CONSOLE_KEY = "Grave"      # the key left of 1
    CLEAR_S = 0.45             # no picture sooner than this after a command's last key
    FOCUS_WAIT_S = 20.0
    LONG_TEXT = 2000           # a command longer than this holds up its frame: wait before the closing key

    def __init__(self, exe_name, window_class, log_path, exchange, log=print, key_hold=0.02, key_gap=0.02):
        """log_path, exchange: functions giving the game's log file and the capture add-on's folder."""
        self.exe_name, self.window_class = exe_name, window_class
        self.log_path, self.exchange = log_path, exchange
        self.log = log
        # seconds a key is held and between keys; lengthened after a miss, and to 1.5 frames at the
        # game's frame rate when the session starts (_pace_keys)
        self.key_hold, self.key_gap = key_hold, key_gap
        self._hwnd = None
        self._closing = False
        self.last_keys = 0.0
        self.menu_seen = 0.0     # when an answer last said a game menu was open
        self.fps = None          # the frame rate the key timing was set from
        self.seq = int(time.time()) % 90000 * 10
        self.last_state = {}
        self.sent = 0
        self.resent = 0

    # --- what a game says about itself -------------------------------------------------------------
    def command_text(self, op, seq, args):
        """The console line that runs our script's command op with its sequence number and args."""
        raise NotImplementedError

    def console_open(self):
        """Whether the console is in the picture now (True/False), or None if the game cannot tell."""
        return None

    def missing_hint(self):
        """What to check when the script does not answer at all."""
        return ""

    # --- the game's window and its log -------------------------------------------------------------
    def hwnd(self):
        """The game's window; looked up once (finding the process takes 0.3 s) and again when it is gone."""
        if self._hwnd and window.client_size(self._hwnd):
            return self._hwnd
        try:
            pid = mem.find_pid(self.exe_name)
        except RuntimeError:
            self._hwnd = None
            return None
        self._hwnd = window.find_game_window(pid, self.window_class)
        return self._hwnd

    def log_size(self):
        try:
            return os.path.getsize(self.log_path())
        except OSError:
            return 0

    def _lines_from(self, pos):
        try:
            with open(self.log_path(), "rb") as f:
                f.seek(pos)
                return f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return []

    def _answer(self, seq, mark):
        """The Reply for seq if its last line is in the log, else None."""
        tag = "|%d|" % seq
        data, state, end = [], {}, None
        for line in self._lines_from(mark):
            i = line.find(PREFIX)
            if i < 0:
                continue
            body = line[i + len(PREFIX):]
            if body.startswith("d" + tag):
                data.append(body[1 + len(tag):])
            elif body.startswith("s" + tag):
                state = parse_kv(body[1 + len(tag):])
            elif body.startswith("e" + tag):
                end = body[1 + len(tag):]
        if end is None:
            return None
        status, _, text = end.partition("|")
        return Reply(seq, status == "ok", text, state, data)

    # --- keys --------------------------------------------------------------------------------------
    def _pace_keys(self):
        """Holds each key at least 1.5 frames: a game reads the keyboard once per frame, so a key
        pressed and released within one frame can be lost. 20 ms was enough at 60-80 frames/s
        (The Witcher 3, 2026-11-23); a slower setting or machine (the Linux nodes: 17-28 frames/s
        in Cyberpunk) gets longer keys from the start instead of after misses."""
        try:
            fps = frames.frame_rate(self.exchange(), 0.5)
        except frames.FrameError:
            fps = 0.0
        need = 1.5 / fps if fps > 1 else 0.06
        self.fps = fps
        self.key_hold = max(self.key_hold, min(0.1, need))
        self.key_gap = max(self.key_gap, min(0.1, need))

    def _settle_console(self, h):
        """Closes the console if a frame shows it open (left so by an earlier process or a missed
        key). True if it was open."""
        if self.console_open():
            window.focus(h)
            window.press(h, self.CONSOLE_KEY, hold_s=0.05)
            time.sleep(0.5)
            return True
        return False

    def _type(self, h, text):
        g, hold = self.key_gap, self.key_hold
        t0 = time.time()
        while not window.focus(h):       # Windows may refuse the first tries (another window was just used)
            if time.time() - t0 > self.FOCUS_WAIT_S:
                raise AdapterError("the game window is not in front, so the command cannot be typed")
            time.sleep(0.5)
        window.press(h, self.CONSOLE_KEY, hold_s=hold)
        time.sleep(g)
        if not window.paste(h, text, hold_s=hold):
            raise AdapterError("the game window lost the keyboard while a command was typed")
        time.sleep(g)
        window.press(h, "Enter", hold_s=hold)
        # a long command (The Witcher 3's ray probes: 25,000 characters, 400 traces) holds up the
        # frame it runs in, and a console key pressed into that frame was lost now and then,
        # leaving the console open for the next command (2026-11-23)
        time.sleep(g + (0.25 if len(text) > self.LONG_TEXT else 0.0))
        window.press(h, self.CONSOLE_KEY, hold_s=hold)
        self.last_keys = time.time()

    def console_clear_in(self):
        """Seconds until the console a command opened has gone from the picture (CLEAR_S after
        its last key; 0 when it already has)."""
        return max(0.0, self.CLEAR_S - (time.time() - self.last_keys))

    # --- commands ----------------------------------------------------------------------------------
    def cmd(self, op, *args, timeout=6.0, attempts=4, check=True):
        """Runs our script's command op with args in the game and returns its Reply. check: an
        "error" answer raises AdapterError."""
        h = self.hwnd()
        if not h:
            raise AdapterError("%s is not running" % self.GAME_TITLE)
        self.seq += 1
        seq = self.seq
        text = self.command_text(op, seq, args)
        if self.sent == 0:
            self._pace_keys()
            self._settle_console(h)      # a new process: the console may have been left open
        for attempt in range(attempts):
            mark = self.log_size()
            self._type(h, text)
            self.sent += 1
            t0 = time.time()
            wait = timeout if attempt == attempts - 1 else min(timeout, 1.5 + 0.00005 * len(text))
            while time.time() - t0 < wait:
                r = self._answer(seq, mark)
                if r is not None:
                    if r.state:
                        self.last_state = r.state
                        if r.state.get("menu") == "1":
                            self.menu_seen = time.time()
                    if attempt and r.state.get("menu") == "1" and not self._closing:
                        self.close_menu()      # the command typed into the game opened its menu (Enter does)
                    if check and not r.ok:
                        raise AdapterError("%s: %s" % (op, r.text))
                    return r
                time.sleep(0.01)
            # No answer: a key was missed, or the console was in the other state. Enter typed into
            # the game can open its menu, whose opening eats the next key (two attempts were not
            # enough, 2026-11-23), so the console key once more after a pause, up to four attempts.
            # Esc is not pressed blindly: at a main menu it asks to quit.
            self.resent += 1
            self.key_hold, self.key_gap = min(0.1, self.key_hold * 1.5), min(0.1, self.key_gap * 1.5)
            time.sleep(0.8)
            window.focus(h)
            # open: close it; closed: send again as it is, but toggle on every second miss all the
            # same (a game may not be able to tell); unknown: toggle
            open_now = self.console_open()
            if open_now is None or open_now or attempt % 2 == 1:
                window.press(h, self.CONSOLE_KEY, hold_s=0.05)
            time.sleep(0.5)
        raise AdapterError("no answer from the game's script to %s (%s%s)" % (text[:60], self.missing_hint(), self.log_path()))

    def wait_line(self, kind, seq, mark, timeout=30.0):
        """The body of the first log line "<kind>|<seq>|..." after mark (for a command that
        answers at once and logs its result later, from a timer), or None after timeout."""
        tag = "%s|%d|" % (kind, seq)
        t0 = time.time()
        while time.time() - t0 < timeout:
            for line in self._lines_from(mark):
                i = line.find(PREFIX + tag)
                if i >= 0:
                    return line[i + len(PREFIX) + len(tag):]
            time.sleep(0.02)
        return None

    def state(self):
        return self.cmd("state").state

    def close_menu(self, tries=4):
        """Closes the game's menu if the script says one is open. Escape is only pressed while one
        is: with none open it would open the pause menu. Returns the state; its "menu" is "1" if
        the menu would not close."""
        self._closing = True
        try:
            st = self.state()
            for _ in range(tries):
                if st.get("menu") != "1":
                    break
                h = self.hwnd()
                window.focus(h)
                window.press(h, "Esc", hold_s=0.05)
                time.sleep(0.8)
                st = self.state()
            return st
        finally:
            self._closing = False

    def hello(self, timeout=3.0):
        """The script's state, or None if it does not answer (main menu not up yet, game loading)."""
        try:
            return self.cmd("hello", timeout=timeout, attempts=4).state
        except AdapterError:
            return None
