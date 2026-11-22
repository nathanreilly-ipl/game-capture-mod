"""GTA V Legacy story mode, through the shared RedLua loader (adapters/common), the ReShade
capture add-on, and a script camera held while the world is frozen.

Freeze: GTA V has no photo-mode freeze. SET_GAME_PAUSED stops rendering (a moved camera gives
the same frame), and SET_TIME_SCALE(0) still runs the world at a minimum step of 1/3000 s per
frame. With that minimum lowered to 1e-7 s (timestep.py) time scale 0 holds the world exactly:
over 480 frames nobody moved and the same pose gave identical frames, while a moved script
camera still renders (2026-11-21, probes/freeze_probe.py). A step of exactly 0 crashes the game.

Unlike RDR2's photo-mode freeze, GTA V's own script camera renders while frozen, so each pose
is set with camera natives (no memory writes), roll included.

World frame: metres, right-handed, +Z up. Heading (degrees) is counter-clockwise from +Y
(north): forward = (-sin h, cos h, 0); the same RAGE conventions as RDR2.

Settings (job settings "adapter"):
    settle        frames between a camera move and its capture (40)
    step_frame_s  world time per frame while stepping the frozen world (0.0005 s: 67 frames per 1/30 s)
    first_settle  frames on the first shot (90)
    clock_settle  frames after setting the clock (240)
    park_height   metres to park the hidden player above the location during a take (10; 0 = stay)
    min_step      the engine's minimum time step while frozen, seconds (1e-7; the game's own is 1/3000)
    populate_s    seconds the world runs after a teleport, so people and traffic stream in (45)
    crowd         walkers of our own spawned around a location after the teleport (12; 0 = none)
    crowd_radius  metres they walk about in around the location (12)

While frozen the population multipliers are 0: with more people than its budget the game
despawns and spawns people even in a frozen world (7 gone and 9 new within 60 m over 3,000
frozen frames); with the multipliers at 0 nothing moved, appeared or went (2026-11-21).
"""
import math
import os
import shutil
import time

import numpy as np

from capture import config
from capture.adapter import Adapter, AdapterError

from ..common import mem, redlua, window
from . import launch, settings_menu, zones
from .timestep import MinStep

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = launch.EXE
WINDOW_CLASS = launch.WINDOW_CLASS
EXCHANGE = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "RDR2Modding", "captures_gtav")
EXCHANGE_ENHANCED = os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "RDR2Modding", "captures_gtave")
SESSION_JOB = os.path.join(HERE, "lua", "jobs", "cam_session.lua")
CLIENT = (2560, 1440)

# camrig/v1 (x, y up, z) -> game (x, -z, y): rig +Y (up) to game +Z, rig +Z to game -Y.
A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

DEFAULTS = {"settle": 40, "step_frame_s": 0.0005, "first_settle": 90, "clock_settle": 240, "park_height": 10.0,
            "min_step": 1e-7, "populate_s": 45, "crowd": 12, "crowd_radius": 12.0}


def game_dir():
    """The game folder: GTAV_DIR, then this machine's config (written by `capture install`), then Steam's default."""
    return (os.environ.get("GTAV_DIR") or config.game("gtav").get("game_dir")
            or r"C:\Program Files (x86)\Steam\steamapps\common\Grand Theft Auto V")


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


def euler_from_axes(right, fwd, up):
    """(pitch, roll, yaw) in degrees, RAGE rotation order 2 (R = Rz(yaw) Rx(pitch) Ry(roll), camera
    right = +X, forward = +Y, up = +Z), for a camera with these world axes."""
    f = np.asarray(fwd, float) / np.linalg.norm(fwd)
    r = np.asarray(right, float) / np.linalg.norm(right)
    p = math.asin(max(-1.0, min(1.0, f[2])))
    y = math.atan2(-f[0], f[1])
    r0 = np.array([math.cos(y), math.sin(y), 0.0])
    u0 = np.array([math.sin(y) * math.sin(p), -math.cos(y) * math.sin(p), math.cos(p)])
    roll = math.atan2(-float(r @ u0), float(r @ r0))
    return math.degrees(p), math.degrees(roll), math.degrees(y)


class GTAVAdapter(Adapter):
    name = "gtav"
    capabilities = frozenset({"obstacles", "raycast"})
    edition = launch.LEGACY
    exchange = EXCHANGE

    def __init__(self, settings=None):
        super().__init__(dict(DEFAULTS, **(settings or {})))
        self.sess = None
        self.hwnd = None
        self.subject_hidden = False
        self.frozen = False
        self.last_size = None
        self._parked_from = None
        self.min_step = MinStep(self.edition.exe)

    # --- lifecycle -------------------------------------------------------------------------
    def _running(self):
        try:
            mem.find_pid(self.edition.exe)
        except RuntimeError:
            return False
        return redlua.heartbeat_age(self.exchange) < 5

    def ensure_ready(self, restart=True):
        if self._running():
            return
        if not restart:
            raise AdapterError("%s is not running with capture_loader.lua (no heartbeat in %s)" % (self.edition.name, self.exchange))
        try:
            launch.start(self.exchange, CLIENT, ed=self.edition)
        except RuntimeError as e:
            raise AdapterError("game restart failed: %s" % e)

    def open(self):
        window.keep_awake()
        redlua.minimize_console()
        self.hwnd = window.find_game_window(mem.find_pid(self.edition.exe), self.edition.window_class)
        for _ in range(120):
            if not self.hwnd or window.focus(self.hwnd):
                break
            time.sleep(1.0)
        else:
            raise AdapterError("could not bring the game window to the front")
        if not window.set_client_size(self.hwnd, *CLIENT):
            raise AdapterError("the game window is %s, not %s" % (window.client_size(self.hwnd), CLIENT))
        if self.sess is None:
            self.sess = redlua.Session(self.exchange, SESSION_JOB, idle_s=900, timeout_s=12 * 3600)

    def close(self):
        if self.sess is not None:
            try:
                if self.frozen:
                    self.end_frozen()
            except Exception:
                pass
            self.sess.end()
            self.sess = None
        self.min_step.close()

    def render_settings(self):
        return {"window_client_size": window.client_size(self.hwnd), "frame_size": self.last_size,
                "reshade_preset": None, "settle_frames": self.settings["settle"],
                "freeze": "time scale 0, minimum step %g s" % self.settings["min_step"],
                "park_height_m": float(self.settings.get("park_height") or 0)}

    # --- conventions -----------------------------------------------------------------------
    def rig_rotation(self, facing_deg):
        # Rig subject faces +Z, which A sends to game -Y; turn by facing + 180 so it faces
        # the game heading facing_deg.
        return _rz(facing_deg + 180.0) @ A

    def heading_basis(self, heading_deg):
        h = math.radians(heading_deg)
        return (-math.sin(h), math.cos(h), 0.0), (math.cos(h), math.sin(h), 0.0), (0.0, 0.0, 1.0)

    # --- the world ---------------------------------------------------------------------------
    def place_title(self, position):
        """The map zone's name at a point (zones.py: the hash of the zone's code), or None."""
        r = self.sess.cmd("place", "%.4f %.4f %.4f" % tuple(position[:3]))
        return zones.title(r.get("place_zone_hash"))

    def subject_state(self):
        st = self.sess.cmd("state")
        p = redlua.vec(st["player"])
        g = self.ground_point(p)
        return {"position": list(g), "facing_deg": float(st.get("player_heading", 0.0)), "clock": st.get("clock"),
                "title": self.place_title(g)}

    def go_to(self, position, facing_deg):
        r = self.sess.cmd("teleport", "%.4f %.4f %.4f %.4f 900 1" % (position[0], position[1], position[2], facing_deg),
                          timeout=180)
        if r.get("loaded") != "true":
            raise AdapterError("the scene did not load around %s" % (position,))
        self.sess.cmd("wait", 120)  # level of detail catches up
        # People and traffic stream in around a new spot over about 50 s (Vinewood Blvd, 2026-11-21:
        # 0 people within 15 m after 10 s, 5-6 after 50 s), even at the game's maximum density.
        # A crowd of walkers of our own adds people (12 within 12 m: 2 -> 14 within 15 m); the world
        # runs on so they spread out and the game's population settles before anything is frozen.
        self.sess.cmd("populate")
        n = int(self.settings.get("crowd") or 0)
        if n:
            self.sess.cmd("crowd", "%d %.3f %.3f %.3f %.1f" % (n, position[0], position[1], position[2],
                                                               float(self.settings.get("crowd_radius") or 12)), timeout=60)
        time.sleep(float(self.settings.get("populate_s") or 0))

    def ground_point(self, position):
        g = self.sess.cmd("ground", "%.4f %.4f %.4f" % (position[0], position[1], position[2] + 2.0))
        z = float(g["ground_z"]) if g["ground_found"] == "true" else position[2] - 1.0
        return [float(position[0]), float(position[1]), z]

    def set_clock(self, hhmm):
        hh, mm = (int(v) for v in hhmm.split(":"))
        clock = self.sess.cmd("clock", hh, mm)["clock"]
        self.sess.cmd("wait", self.settings["clock_settle"])
        return clock

    def set_weather(self, name):
        """Changes to a weather type at once and keeps it (EXTRASUNNY, CLEAR, CLOUDS, OVERCAST, RAIN,
        THUNDER, FOGGY, SMOG, ...); "free" lets it change again."""
        if name.lower() == "free":
            return self.sess.cmd("weather", "free")["weather"]
        r = self.sess.cmd("weather", name)
        self.sess.cmd("wait", 30)
        st = self.sess.cmd("weather", "state")
        if st["weather_next"] != r["weather_hash"]:
            raise AdapterError("the weather did not change to %s (the game has %s)" % (name, st["weather_next"]))
        return r["weather"]

    def hide_subject(self, hidden):
        """Takes the player out of the scene: invisible, ignored by everyone and the police, no
        collision; with park_height > 0 also parked that high above, streaming kept at the spot."""
        self.sess.cmd("player_visible", 0 if hidden else 1)
        self.sess.cmd("ghost", 1 if hidden else 0)
        h = float(self.settings.get("park_height") or 0)
        if hidden and h > 0:
            x, y, z = redlua.vec(self.sess.cmd("state")["player"])
            gz = self.ground_point((x, y, z))[2]
            self._parked_from = (x, y, gz)
            self.sess.cmd("park", "%.3f %.3f %.3f" % (x, y, gz + 1.0 + h))
            self.sess.cmd("focus", "%.3f %.3f %.3f" % (x, y, gz))
        elif not hidden and self._parked_from:
            x, y, gz = self._parked_from
            self.sess.cmd("focus", "clear")
            self.sess.cmd("teleport", "%.3f %.3f %.3f 0 900 1" % (x, y, gz), timeout=180)
            self._parked_from = None
        self.subject_hidden = hidden

    def _pose(self, pos, right, fwd, up, vfov):
        pitch, roll, yaw = euler_from_axes(right, fwd, up)
        self.sess.cmd("pose", "%.6f %.6f %.6f %.6f %.6f %.6f %.6f" % (pos[0], pos[1], pos[2], pitch, roll, yaw, vfov))

    def view(self, pos, fwd, up, vfov_deg, path):
        right = np.cross(np.asarray(fwd, float), np.asarray(up, float))
        self._pose(pos, right, fwd, up, vfov_deg)
        self.sess.cmd("wait", 45)
        r = self.sess.cmd("capture", "view")
        shutil.move(r["file"], path)

    # --- frozen capture ----------------------------------------------------------------------
    def begin_frozen(self, first_shot):
        s = first_shot
        self._pose(s["pos"], s["right"], s["fwd"], s["up"], s["vfov_deg"])
        self.sess.cmd("wait", 60)
        self.sess.cmd("density", "0 0")   # no spawning or culling while frozen (see the module notes)
        self.sess.cmd("wait", 10)
        self.min_step.set(float(self.settings["min_step"]))
        self.sess.cmd("freeze", "timescale")
        self.frozen = True
        st = self.sess.cmd("wait", self.settings["first_settle"])
        if float(st["frame_time"]) > 10 * float(self.settings["min_step"]):
            raise AdapterError("the world is not frozen: frame time %s s at time scale 0" % st["frame_time"])

    def set_camera(self, shot):
        self._pose(shot["pos"], shot["right"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def capture(self, path, settle):
        r = self.sess.cmd("shoot", int(settle or self.settings["settle"]), "shot", timeout=60)
        shutil.move(r["file"], path)
        self.last_size = [int(r["width"]), int(r["height"])]
        return {"width": int(r["width"]), "height": int(r["height"]), "rendered_pos": r["rendered_pos"],
                "rendered_rot": r["rendered_rot"], "rendered_fov": r["rendered_fov"], "game_timer": int(r["game_timer"]),
                "player_pos": r["player"], "health": {"problems": self._problems(r)}}

    def advance(self, seconds):
        """Exactly `seconds` of world time: n frames of seconds / n each (about 0.5 ms), at time
        scale 0 with the minimum step set to that, between two pauses (no frame runs while the step
        size is being changed). The real frame rate and its hitches do not enter."""
        n = max(1, int(round(seconds / float(self.settings["step_frame_s"]))))
        self.sess.cmd("pause", 1)
        try:
            self.min_step.set(seconds / n)
            r = self.sess.cmd("frames", n, timeout=120)
        finally:
            self.min_step.set(float(self.settings["min_step"]))
            self.sess.cmd("pause", 0)
        if int(r["frames_run"]) != n:
            raise AdapterError("a time step ran %s frames instead of %d" % (r["frames_run"], n))
        return {"advanced_s": float(r["advanced_s"]), "ticks": n, "timer_ms": int(r["timer_ms"])}

    def instant(self):
        """The game timer. It does not count the frozen world's steps (they run at time scale 0), so
        frozen frames are checked by their frame time instead (_problems: world not frozen)."""
        return int(self.sess.cmd("state")["game_timer"])

    def screen_grab(self):
        return window.grab(self.hwnd) if self.hwnd else None

    KEYS = {"F13": (0x7C, 0x64), "F14": (0x7D, 0x65), "F15": (0x7E, 0x66), "F16": (0x7F, 0x67), "F17": (0x80, 0x68),
            "F18": (0x81, 0x69)}

    def press_key(self, key):
        vk, scan = self.KEYS[key]
        if self.hwnd and not window.is_foreground(self.hwnd):
            window.focus(self.hwnd)   # another window took the front (a dialog, another session's tool)
        if not window.press_vk(self.hwnd, vk, scan):
            raise AdapterError("the game window is not in front; %s not sent" % key)

    def wait_frames(self, n):
        self.sess.cmd("wait", int(n))

    def _problems(self, st):
        problems = []
        if self.hwnd and not window.is_foreground(self.hwnd):
            problems.append("game window lost focus")
        if st.get("pause_menu") == "1":
            problems.append("pause menu active")
        if self.subject_hidden and st.get("player_visible") == "1":
            problems.append("player visible")
        if self.frozen and (st.get("frozen") != "1" or float(st.get("frame_time", 0)) > 100 * float(self.settings["min_step"])):
            problems.append("world not frozen")
        return problems

    def health(self):
        return {"problems": self._problems(self.sess.cmd("state"))}

    def recover(self):
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

    # --- the scene ------------------------------------------------------------------------------
    def raycast(self, starts, ends):
        """Line probes against terrain, buildings, objects and foliage (not people or vehicles).
        Returns (hit bool N, points N x 3, normals N x 3)."""
        starts, ends = np.asarray(starts, float), np.asarray(ends, float)
        inp, outp = os.path.join(self.exchange, "rays_in.txt"), os.path.join(self.exchange, "rays_out.txt")
        with open(inp, "w", encoding="utf-8") as f:
            for s, e in zip(starts, ends):
                f.write("%.3f %.3f %.3f %.3f %.3f %.3f\n" % (s[0], s[1], s[2], e[0], e[1], e[2]))
        self.sess.cmd("raycast", timeout=60 + len(starts) / 2000.0)
        hit = np.zeros(len(starts), bool)
        pts, nrm = np.zeros((len(starts), 3)), np.zeros((len(starts), 3))
        with open(outp, encoding="utf-8") as f:
            for i, line in enumerate(f):
                v = line.split()
                if v and v[0] == "1":
                    hit[i] = True
                    pts[i] = [float(x) for x in v[1:4]]
                    nrm[i] = [float(x) for x in v[4:7]]
        return hit, pts, nrm

    # --- moving things near the rig ------------------------------------------------------------
    def obstacles(self, center, radius):
        """People, animals and vehicles within radius, as oriented boxes from their models'
        dimensions (capture/obstacles.py)."""
        st = self.sess.cmd("obstacles", "%.3f %.3f %.3f %.3f" % (center[0], center[1], center[2], radius), timeout=60)
        out = []
        for n in range(1, int(st.get("obstacle_count", 0)) + 1):
            kind, owned, c, r, f, u, half = st["o%d" % n].split("|")
            v = lambda s: [float(x) for x in s.split()]  # noqa: E731
            out.append({"id": n, "kind": kind, "owned": owned == "1", "center": v(c), "axes": [v(r), v(f), v(u)],
                        "half": v(half), "approx": "model"})
        return out

    def remove_obstacles(self, ids):
        if not ids:
            return {"removed": 0, "skipped": []}
        r = self.sess.cmd("remove", " ".join(str(i) for i in ids))
        return {"removed": int(r.get("removed", 0)), "skipped": [int(v) for v in r.get("skipped", "").split(",") if v]}

    def end_frozen(self):
        try:
            self.sess.cmd("unfreeze")
            self.sess.cmd("density", "off")
        finally:
            self.frozen = False
            self.min_step.restore()


class GTAVEnhancedAdapter(GTAVAdapter):
    """GTA V Enhanced (Direct3D 12, DLSS, ray tracing): the same natives through Script Hook V, its
    own exe, Steam app and exchange folder. Its install puts Ultimate ASI Loader in as
    xinput1_4.dll (GTA5_Enhanced.exe does not load dinput8.dll at start, so Script Hook V's own
    loader never runs) and keeps ReShade's config outside the game folder, which Enhanced locks."""
    name = "gtave"
    edition = launch.ENHANCED
    exchange = EXCHANGE_ENHANCED
    capabilities = GTAVAdapter.capabilities | {"ray_tracing_switch"}

    def set_ray_tracing(self, on, log=print):
        """The game's ray tracing on or off, live, through its settings menu (settings_menu.py),
        also while frozen; True if it changed."""
        changed = settings_menu.set_ray_tracing(self.hwnd, on, log=log)
        if changed and self.frozen:
            # the pause menu paused and resumed the game: hold the world again and check it is held
            self.sess.cmd("freeze", "timescale")
            st = self.sess.cmd("wait", 60)
            if float(st["frame_time"]) > 10 * float(self.settings["min_step"]):
                raise AdapterError("the world is not frozen after the settings menu: frame time %s s" % st["frame_time"])
        return changed
