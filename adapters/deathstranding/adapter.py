"""Death Stranding Director's Cut (1.004, Steam): a camera rig in a held world.

The game has no script layer, so this adapter brings its own: capture_ds.asi (plugin/), loaded by
Ultimate ASI Loader as winhttp.dll, hooks the game's clocks and its render camera; Sam's physics
shape is moved through process memory (player.py); photo mode, driven by keys, hides Sam and the
HUD (photo.py). All found 2026-11-25 on the capture PC with the probes in probes/ (memory scans,
data breakpoints in the CPU's debug registers, disassembly of ds.exe), at the Distribution Center
West of Capital Knot City.

Method
------
Freeze. Every game clock gets its frame step in Timer::Tick (RVA 0x1DF57F0 in 1.004): step =
(int)(raw step x the game's scale), in 32.32 fixed point (2^32 ticks per second); the frame's
clocks are then advanced from it (Clock::Advance, RVA 0x2F3ACF0). The plug-in gives a raw step of 0
while it holds: measured exactly 0 ticks of game time over 240 frames, and Sam caught in the middle
of an idle animation stood still (mean picture change 0.089 levels between frames, renderer noise,
no pixel over 12 levels in 3.5 s; 1.087 and 3.6% with the world running). The game's own pause
(photo mode, menus) works the same way, a scale of 0, so a scale or step of exactly 0 is safe here.

Time steps. `step <ticks> <frames>` spreads an exact number of ticks evenly over frames (integer
shares, the last taking the remainder), then holds again. Timer::Tick takes the step through a
float, which rounds a share of 17.9 million ticks down by a tick or two; the plug-in reads back what
the game clock got and carries the difference into the next frames: 1/30 s (143,165,577 ticks)
over 8 frames lands within 1 tick (0.23 ns), over 30 frames exactly, in one frame within 7 ticks
(2026-11-25; before the carry, every 8-frame step came out 7 ticks short). Inside photo mode the game's scale is 0, so the plug-in sets it to 1 for the
step (`force`): 15 steps advanced the game clock by exactly 0.500000 s and the world moved
(particles, fog, light beams), held again it did not.

Camera. The render camera (an object with the position as three doubles at +0x20, the rotation
rows right, forward, up as nine floats at +0x38, the vertical FOV in degrees at +0x74) is filled
from the game's camera every frame, then turned into view matrices. The plug-in hooks the view
setup between the two (RVA 0x361AEE2, after the game's FOV multiplier) and writes our camera in:
everything rendered follows (0.5 m asked, 0.5 m rendered, the status file reporting the camera
the frame was rendered with). Photo mode's own camera, and its range around Sam, are replaced.
The FOV the game stores is vertical (photo mode's 29.6 mm read 44.096 degrees: 2 atan(12/29.6)).

The subject. Photo mode (photo.py) hides Sam (Show Sam off), the HUD, its own menu, and the game's
signs and scan markers; takes run in it from the first shot to the last. Sam is moved by writing
his physics shape's position (player.py): 3 m written, 3.17 m after he settled on a slope.

Unattended start (launch.py): through Steam, about 30 s from a closed game to a loaded save, Enter
answering the logos and the main menu's Continue (the latest save); with AutoLogin 0 the offline
notices do not appear.

Not yet done or measured (README, Death Stranding; BACKLOG):
- the projection check against known world points (within 1 px elsewhere); the FOV convention is
  confirmed (vertical), the rotation rows were checked by moving along them;
- the settle after a camera cut, exposure between poses in a held world, renderer noise;
- people (porters, MULEs, BTs) and whether they notice the hidden Sam; no `obstacles`;
- `raycast`: no line probes against the scene yet, so solved rigs (yiming_stdm) are not available;
  ring and fixed rigs are;
- plausibility: Show Signs and Show Odradek Scan off hide the game's signs and markers; the light
  beams over lost cargo and the chiral growths stay (AGENTS.md section 1).
"""
import math
import os
import shutil
import time

import numpy as np

from capture import host
from capture.adapter import Adapter, AdapterError

from ..common import frames, window
from . import launch, paths, photo
from .player import Player, PlayerError
from .plugin import Plugin, vec

A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
DEFAULTS = {"settle": 30, "first_settle": 90, "step_frames": 8, "populate_s": 8.0, "pose_tolerance_m": 0.002,
            "fov_tolerance_deg": 0.01}


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


def _rows(fwd, up):
    """The render camera's rotation rows (right, forward, up) for a camera looking along fwd."""
    f = np.asarray(fwd, float)
    f = f / np.linalg.norm(f)
    u = np.asarray(up, float)
    r = np.cross(f, u)
    if np.linalg.norm(r) < 1e-9:
        r = np.cross(f, [0.0, 1.0, 0.0])
    r = r / np.linalg.norm(r)
    u = np.cross(r, f)
    return [list(r), list(f), list(u)]


class DeathStrandingAdapter(Adapter):
    name = "deathstranding"
    capabilities = frozenset()
    min_fps = 30

    def __init__(self, settings=None):
        super().__init__(dict(DEFAULTS, **(settings or {})))
        self.exchange = paths.exchange()
        self.plugin = Plugin()
        self.player = None
        self.hwnd = None
        self.subject_hidden = False
        self.frozen = False
        self.last_size = None
        self._pose_asked = None

    # --- lifecycle -------------------------------------------------------------------------
    def _running(self):
        return host.process_running(paths.EXE_NAME) and launch.in_world(self.plugin, frames=5, timeout=3.0)

    def ensure_ready(self, restart=True):
        if self._running():
            return
        if not restart:
            raise AdapterError("Death Stranding is not running in a loaded save with capture_ds.asi answering "
                               "(start it with: python -m adapters.deathstranding.launch)")
        try:
            launch.start()
        except RuntimeError as e:
            raise AdapterError("game restart failed: %s" % e)

    def open(self):
        window.keep_awake()
        self.hwnd = launch.hwnd()
        if not self.hwnd:
            raise AdapterError("no Death Stranding window")
        if not window.focus(self.hwnd):
            raise AdapterError("could not bring the game window to the front")
        st = self.plugin.status()
        if not self.plugin.alive() or "time" not in st.get("hooks", "") or "camera" not in st.get("hooks", ""):
            raise AdapterError("capture_ds.asi is not answering with its hooks (status %s); run capture install "
                               "deathstranding --only scripts with the game closed" % st.get("hooks"))
        self.plugin.cmd("cam off")
        self.plugin.run()
        if photo.game_paused(self.plugin):
            photo.close(self.hwnd, self.plugin)      # photo mode left open by a session that ended badly
        self.player = Player()

    def close(self):
        try:
            if self.subject_hidden or self.frozen:
                self.hide_subject(False)
            self.plugin.cmd("cam off")
            self.plugin.run()
        except Exception:
            pass
        self.frozen = self.subject_hidden = False

    def render_settings(self):
        st = self.plugin.status()
        return {"window_client_size": window.client_size(self.hwnd) if self.hwnd else None, "frame_size": self.last_size,
                "reshade_preset": None, "settle_frames": self.settings["settle"],
                "freeze": "capture_ds.asi: every game timer ticks a raw step of 0, inside photo mode's pause",
                "time_step": "exact ticks (2^-32 s) spread evenly over %d frames, at scale 1 through photo mode's pause"
                             % int(self.settings["step_frames"]),
                "camera": "capture_ds.asi writes the render camera before the view matrices (vertical FOV)",
                "photo_mode": "Show Sam off, Show Signs off, Show Odradek Scan off, menu hidden; DOF, vignette, "
                              "lens distortion, chromatic aberration, colour filter off (its defaults)",
                "plugin_hooks": st.get("hooks")}

    # --- conventions -------------------------------------------------------------------------
    def rig_rotation(self, facing_deg):
        return _rz(facing_deg + 180.0) @ A

    def heading_basis(self, heading_deg):
        h = math.radians(heading_deg)
        return (-math.sin(h), math.cos(h), 0.0), (math.cos(h), math.sin(h), 0.0), (0.0, 0.0, 1.0)

    # --- the world ---------------------------------------------------------------------------
    def _camera_near(self):
        return self.plugin.game_camera()[0]

    def subject_state(self):
        pos, rot, _ = self.plugin.game_camera()
        f = rot[1]
        facing = math.degrees(math.atan2(-f[0], f[1]))
        try:
            feet = self.player.position(pos)
        except PlayerError as e:
            raise AdapterError(str(e))
        return {"position": feet, "facing_deg": facing, "clock": None, "title": self.place_title(feet)}

    def go_to(self, position, facing_deg):
        if self.subject_hidden or self.frozen:
            self.hide_subject(False)
        self.plugin.run()
        try:
            self.player.teleport(position, self._camera_near())
        except PlayerError as e:
            raise AdapterError(str(e))
        time.sleep(float(self.settings.get("populate_s") or 0))     # the area streams in around him
        here = self.player.position(self._camera_near())
        off = float(np.linalg.norm(np.array(here[:2]) - np.array(position[:2])))
        # A saved location is where Sam stood, so he lands on it; a guessed height (scout --at) drops
        # him and he may slide down a slope (3.9 m from a 2 m drop on the valley side, 2026-11-25).
        if off > float(self.settings.get("arrive_tolerance_m", 10.0)):
            raise AdapterError("Sam is %.1f m from where he was put (fell, or was pushed back)" % off)
        self.arrived_off_m = off

    def ground_point(self, position):
        """No line probes yet: positions come from where Sam stood (scouting), so they are kept."""
        return [float(v) for v in position]

    def set_clock(self, hhmm):
        """The time of day is not driven yet; the world keeps its own."""
        return None

    def hide_subject(self, hidden):
        """Photo mode with Sam, the HUD and the game's signs hidden, and the world held; showing him
        again leaves photo mode, gives the camera back and lets the world run."""
        if hidden:
            self.plugin.run()
            photo.open_clean(self.hwnd, self.plugin)
            self.plugin.hold()
            self.plugin.wait_frames(3)
            self.frozen = True
        else:
            self.plugin.cmd("cam off")
            photo.close(self.hwnd, self.plugin)
            self.plugin.run()
            self.frozen = False
            self._pose_asked = None
        self.subject_hidden = hidden

    def _pose(self, pos, fwd, up, vfov):
        rows = _rows(fwd, up)
        self.plugin.camera(pos, rows, float(vfov))
        self._pose_asked = (np.asarray(pos, float), np.asarray(rows[1], float), float(vfov))
        self._last_pose = (pos, fwd, up, vfov)

    def _shoot(self, path, settle, stem="shot"):
        a = frames.shoot(self.exchange, stem, after=int(settle), timeout=60 + int(settle) / 5.0)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        shutil.move(a["path"], path)
        return a

    def view(self, pos, fwd, up, vfov_deg, path):
        was_hidden = self.subject_hidden
        if not was_hidden:
            self.hide_subject(True)
        try:
            self._pose(pos, fwd, up, vfov_deg)
            self._shoot(path, self.settings["first_settle"], "view")
        finally:
            if not was_hidden:
                self.hide_subject(False)

    # --- frozen capture ----------------------------------------------------------------------
    def begin_frozen(self, first_shot):
        if not self.subject_hidden:
            self.hide_subject(True)
        s = first_shot
        self._pose(s["pos"], s["fwd"], s["up"], s["vfov_deg"])
        self.plugin.wait_frames(int(self.settings["first_settle"]))
        st = self.plugin.status()
        if st.get("state") != "hold":
            raise AdapterError("the world is not held (capture_ds state %s)" % st.get("state"))
        self.frozen = True

    def set_camera(self, shot):
        self._pose(shot["pos"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def capture(self, path, settle):
        a = self._shoot(path, int(settle or self.settings["settle"]))
        st = self.plugin.status()
        self.last_size = [a["width"], a["height"]]
        return {"width": a["width"], "height": a["height"], "health": {"problems": self._problems(st)},
                "rendered_pos": st.get("render_pos"), "rendered_rot": st.get("render_rot"),
                "rendered_fov": st.get("render_fov"), "sim_time": st.get("timer0"), "render_frame": a["frame"]}

    def advance(self, seconds):
        """Exactly `seconds` of game time (to 2^-32 s), spread over step_frames frames, through photo
        mode's pause; then held again."""
        t0 = int(self.plugin.status().get("timer0", "0,0").split(",")[0])
        given = self.plugin.step(float(seconds), frames=int(self.settings["step_frames"]), force=True)
        self.plugin.wait_frames(2)
        st = self.plugin.status()
        t1 = int(st.get("timer0", "0,0").split(",")[0])
        if st.get("state") != "hold":
            raise AdapterError("the world is not held after a time step")
        return {"advanced_s": (t1 - t0) / 2.0 ** 32, "ticks": t1 - t0, "asked_ticks": given, "sim_time": st.get("timer0")}

    def instant(self):
        """The game clock in ticks (2^-32 s); it stands still exactly while the world is held."""
        return self.plugin.status().get("timer0", "0,0").split(",")[0]

    def wait_frames(self, n):
        self.plugin.wait_frames(int(n))

    def screen_grab(self):
        return window.grab(self.hwnd) if self.hwnd else None

    def _problems(self, st):
        problems = []
        if self.hwnd and not window.is_foreground(self.hwnd):
            problems.append("game window lost focus")
        if not self.plugin.alive():
            problems.append("capture_ds.asi is not writing its status (the game closed?)")
        if self.frozen and st.get("state") != "hold":
            problems.append("world not held (capture_ds state %s)" % st.get("state"))
        if self.subject_hidden and st.get("scale0") not in (None, "0.0000"):
            problems.append("photo mode is not open (the game's scale is %s): Sam and the HUD may show" % st.get("scale0"))
        if self._pose_asked is not None:
            if st.get("cam") != "on":
                problems.append("our camera is not in force")
            else:
                pos = np.array(vec(st["render_pos"]))
                r = vec(st["render_rot"])
                fwd = np.array(r[3:6])
                d = float(np.linalg.norm(pos - self._pose_asked[0]))
                ang = math.degrees(math.acos(float(np.clip(fwd @ self._pose_asked[1], -1.0, 1.0))))
                if d > float(self.settings["pose_tolerance_m"]) or ang > 0.05:
                    problems.append("camera %.1f mm and %.3f degrees off its pose" % (d * 1000, ang))
                if abs(float(st["render_fov"]) - self._pose_asked[2]) > float(self.settings["fov_tolerance_deg"]):
                    problems.append("field of view %s, not %.4f" % (st["render_fov"], self._pose_asked[2]))
        return problems

    def health(self):
        return {"problems": self._problems(self.plugin.status())}

    def recover(self):
        """Refocus the window and set the pose again; the held world is not let go."""
        if self.hwnd and not window.is_foreground(self.hwnd):
            window.focus(self.hwnd)
        if self.frozen:
            self.plugin.hold()
        if getattr(self, "_last_pose", None):
            self._pose(*self._last_pose)
        self.plugin.wait_frames(int(self.settings["settle"]))
        return not self._problems(self.plugin.status())

    def end_frozen(self):
        """The take is over; the world stays held until the subject is shown again."""
