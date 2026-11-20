"""RDR2 story mode, through capture_loader.lua (RedLua), the ReShade add-on, and direct
writes to the engine's render camera while the photo-mode freeze holds the world.

World frame: metres, right-handed, +Z up. Heading (degrees) is counter-clockwise from +Y
(north): forward = (-sin h, cos h, 0).

Settings (job settings "adapter"):
    settle        ticks between a camera write and its capture (40; README: settle test)
    step_scale    time scale while stepping the frozen world (0.1)
    first_settle  ticks on the first shot before exposure is locked (90)
    clock_settle  ticks after setting the clock (240)
"""
import math
import os
import shutil
import subprocess
import time

import numpy as np

from capture.adapter import Adapter, AdapterError

from . import render_camera as rc
from . import window
from .mem import Process, find_pid
from .session import CamSession, heartbeat_age, vec

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_DIR = os.environ.get("RDR2_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2")

# camrig/v1 (x, y up, z) -> game (x, -z, y): rig +Y (up) to game +Z, rig +Z to game -Y.
A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

DEFAULTS = {"settle": 40, "step_scale": 0.1, "first_settle": 90, "clock_settle": 240}


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


def _reshade_preset():
    try:
        with open(os.path.join(GAME_DIR, "ReShade.ini"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip().startswith("PresetPath="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


class RDR2Adapter(Adapter):
    name = "rdr2"
    capabilities = frozenset()

    def __init__(self, settings=None):
        super().__init__(dict(DEFAULTS, **(settings or {})))
        self.sess = None
        self.proc = None
        self.frame = None
        self.hwnd = None
        self.subject_hidden = False
        self.frozen = False
        self.last_size = None

    # --- lifecycle -------------------------------------------------------------------------
    def _running(self):
        try:
            find_pid()
            return heartbeat_age() < 5
        except RuntimeError:
            return False

    def ensure_ready(self, restart=True):
        if self._running():
            return
        if not restart:
            raise AdapterError("RDR2 is not running with capture_loader.lua (no heartbeat)")
        script = os.path.join(HERE, "scripts", "restart_game.ps1")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not self._running():
            raise AdapterError("game restart failed: %s" % (r.stdout[-500:] + r.stderr[-500:]))

    def open(self):
        if self.sess is None:
            self.sess = CamSession(idle_s=900, timeout_s=12 * 3600)
        self.hwnd = window.find_game_window(find_pid())

    def close(self):
        if self.sess is not None:
            try:
                if self.frozen:
                    self.end_frozen()
            except Exception:
                pass
            self.sess.end()
            self.sess = None
        if self.proc is not None:
            self.proc.close()
            self.proc = None
        self.frame = None

    def render_settings(self):
        return {"window_client_size": window.client_size(self.hwnd), "frame_size": self.last_size,
                "reshade_preset": _reshade_preset(), "settle_ticks": self.settings["settle"]}

    # --- conventions -----------------------------------------------------------------------
    def rig_rotation(self, facing_deg):
        # Rig subject faces +Z, which A sends to game -Y; turn by facing + 180 so it faces
        # the game heading facing_deg.
        return _rz(facing_deg + 180.0) @ A

    def heading_basis(self, heading_deg):
        h = math.radians(heading_deg)
        return (-math.sin(h), math.cos(h), 0.0), (math.cos(h), math.sin(h), 0.0), (0.0, 0.0, 1.0)

    # --- the world ---------------------------------------------------------------------------
    def subject_state(self):
        st = self.sess.cmd("state")
        p = vec(st["player"])
        g = self.ground_point(p)
        return {"position": list(g), "facing_deg": float(st.get("player_heading", 0.0)), "clock": st.get("clock")}

    def go_to(self, position, facing_deg):
        r = self.sess.cmd("teleport", "%.4f %.4f %.4f %.4f" % (position[0], position[1], position[2], facing_deg),
                          timeout=180)
        if r.get("loaded") != "true":
            raise AdapterError("the scene did not load around %s" % (position,))
        self.sess.cmd("wait", 120)  # level of detail catches up

    def ground_point(self, position):
        g = self.sess.cmd("ground", "%.4f %.4f %.4f" % (position[0], position[1], position[2] + 2.0))
        z = float(g["ground_z"]) if g["ground_found"] == "true" else position[2]
        return [float(position[0]), float(position[1]), z]

    def set_clock(self, hhmm):
        hh, mm = (int(v) for v in hhmm.split(":"))
        clock = self.sess.cmd("clock", hh, mm)["clock"]
        self.sess.cmd("wait", self.settings["clock_settle"])
        return clock

    def hide_subject(self, hidden):
        self.sess.cmd("player_visible", 0 if hidden else 1)
        self.subject_hidden = hidden

    def view(self, pos, fwd, up, vfov_deg, path):
        pitch, yaw = rc.pitch_yaw(fwd)
        self.sess.pose(pos, pitch, yaw, vfov_deg)
        self.sess.cmd("wait", 45)
        r = self.sess.cmd("capture", "view")
        shutil.move(r["file"], path)

    # --- frozen capture ----------------------------------------------------------------------
    def begin_frozen(self, first_shot):
        self.proc = Process(write=True)
        player = vec(self.sess.cmd("state")["player"])
        found, _ = rc.calibrate(self.sess, self.proc, player)
        pitch, yaw = rc.pitch_yaw(first_shot["fwd"])
        self.sess.pose(first_shot["pos"], pitch, yaw, first_shot["vfov_deg"])
        self.sess.cmd("wait", 60)
        self.sess.cmd("freeze")
        self.frozen = True
        self.sess.cmd("wait", 20)
        chosen = rc.pick_render_frame(self.sess, self.proc, found)
        if len(chosen) != 1:
            raise AdapterError("render camera frame not found (%d candidates)" % len(chosen))
        self.frame = chosen[0]
        self.set_camera(first_shot)
        self.sess.cmd("wait", self.settings["first_settle"])
        self.sess.cmd("exposure", "lock")

    def set_camera(self, shot):
        rc.write_pose(self.proc, self.frame, shot["pos"], shot["right"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def capture(self, path, settle):
        r = self.sess.cmd("shoot", int(settle or self.settings["settle"]), "shot", timeout=60)
        shutil.move(r["file"], path)
        self.last_size = [int(r["width"]), int(r["height"])]
        return {"width": int(r["width"]), "height": int(r["height"]), "rendered_pos": r["rendered_pos"],
                "rendered_fov": r["rendered_fov"], "game_timer": int(r["game_timer"]),
                "health": {"problems": self._problems(r)}}

    def advance(self, seconds):
        r = self.sess.cmd("advance", "%.9f %.4f" % (seconds, self.settings["step_scale"]), timeout=120)
        return {"advanced_s": float(r["advanced_s"]), "ticks": int(r["ticks"]), "timer_ms": int(r["timer_ms"])}

    def instant(self):
        return int(self.sess.cmd("state")["game_timer"])

    def _problems(self, st):
        problems = []
        if self.hwnd and not window.is_foreground(self.hwnd):
            problems.append("game window lost focus")
        if st.get("pause_menu") == "1":
            problems.append("pause menu active")
        if self.subject_hidden and st.get("player_visible") == "1":
            problems.append("player visible")
        if self.frozen and st.get("frozen") != "1":
            problems.append("world not frozen")
        return problems

    def health(self):
        return {"problems": self._problems(self.sess.cmd("state"))}

    def recover(self):
        """Refocus the window, wait for the pause menu to close, hide the player again,
        and let the picture settle. The world stays frozen throughout."""
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.hwnd and not window.is_foreground(self.hwnd):
                window.focus(self.hwnd)
            st = self.sess.cmd("state")
            if self.subject_hidden and st.get("player_visible") == "1":
                self.sess.cmd("player_visible", 0)
            if not self._problems(self.sess.cmd("wait", 10)):
                self.sess.cmd("wait", self.settings["settle"])
                return True
            time.sleep(0.5)
        return False

    def end_frozen(self):
        try:
            self.sess.cmd("exposure", "unlock")
        finally:
            self.sess.cmd("unfreeze")
            self.frozen = False
