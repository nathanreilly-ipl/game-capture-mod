"""OptiScaler's DLSS 5 fork in a running game, for any game: its live settings file and its log.

dlssnr-set.txt beside OptiScaler takes [DlssNr] settings as Key=Value lines; OptiScaler applies
them within a second, deletes the file and logs "live setting <key> = <value>" (checked in
Cyberpunk 2077, 2026-11-22, for WhitePointSource and WhitePointScale).

The white point is what the frame is divided by before the model sees it. The capture install
leaves it on Automatic (WhitePointSource=3): measured from each frame and eased toward it over
seconds, unless the game hands its exposure to the upscaler. Cyberpunk 2077 hands none, so two
cameras of one frozen instant were composed with different white points (Cherry Blossom Market,
2026-11-22: 1.10x to 2.00x across 8 views, the game's exposure locked): the per-view drift an
auto-exposure gives. lock_white_point() waits until the meter has settled on the current view
and holds that value as a fixed paper white (WhitePointSource=0, WhitePointScale) for a take;
unlock_white_point() puts the ini's source back. The menu's modes, in order: 0 paper white
only, 1 the game's own exposure, 2 a buffer the exposure scan found, 3 automatic.
"""
import os
import re
import time

COMPOSITION = re.compile(rb"DLSS-NR composition: paper white ([\d.]+)x")
TAIL = 4 << 20   # bytes of the log searched for the last composition line


class OptiScalerLive:
    def __init__(self, folder):
        """folder: where OptiScaler is (its log, ini and live settings file are beside it)."""
        self.folder = folder
        self.log = os.path.join(folder, "OptiScaler.log")
        self.ini = os.path.join(folder, "OptiScaler.ini")
        self.live = os.path.join(folder, "dlssnr-set.txt")

    def white_point(self):
        """The last white point OptiScaler composed a frame with (it logs one when it changes),
        or None if DLSS 5 has not run since the game started (the log starts empty each start)."""
        try:
            with open(self.log, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - TAIL))
                found = COMPOSITION.findall(f.read())
        except OSError:
            return None
        return float(found[-1]) if found else None

    def settled_white_point(self, quiet_s=3.0, timeout_s=30.0):
        """The white point once it has not changed for quiet_s (the meter eases over seconds)."""
        last, since, t0 = None, time.time(), time.time()
        while time.time() - t0 < timeout_s:
            v = self.white_point()
            if v != last:
                last, since = v, time.time()
            elif v is not None and time.time() - since >= quiet_s:
                return v
            time.sleep(0.5)
        return last

    def apply(self, values, timeout_s=8.0):
        """Live [DlssNr] settings; returns once OptiScaler has taken the file."""
        with open(self.live, "w", encoding="ascii", newline="\n") as f:
            f.write("".join("%s=%s\n" % kv for kv in values.items()))
        t = time.time()
        while os.path.exists(self.live):
            if time.time() - t > timeout_s:
                os.remove(self.live)
                raise RuntimeError("OptiScaler did not take %s within %.0f s" % (self.live, timeout_s))
            time.sleep(0.1)

    def ini_value(self, section, key, default=None):
        try:
            text = open(self.ini, encoding="utf-8-sig", errors="replace").read()
        except OSError:
            return default
        m = re.search(r"^\[%s\][^\[]*?^%s=([^\r\n]*)" % (re.escape(section), re.escape(key)), text, re.M | re.S)
        v = m.group(1).strip() if m else None
        return default if v in (None, "", "auto") else v

    def lock_white_point(self, quiet_s=3.0, timeout_s=30.0):
        """Holds the white point the meter settled on as a fixed paper white. Returns it, or None
        if DLSS 5 is not running."""
        if self.white_point() is None:
            return None
        self.unlock_white_point()   # the meter, even if an earlier session ended holding a value
        time.sleep(1.0)
        v = self.settled_white_point(quiet_s, timeout_s)
        if v is None:
            return None
        self.apply({"WhitePointSource": "0", "WhitePointScale": "%.4f" % v})
        return v

    def unlock_white_point(self):
        self.apply({"WhitePointSource": self.ini_value("DlssNr", "WhitePointSource", "3")})
