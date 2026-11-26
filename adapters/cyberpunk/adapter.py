"""Cyberpunk 2077 (patch 2.5, Steam), through Cyber Engine Tweaks (our loader mod, lua/capture_mod),
the ReShade capture add-on, and the session job lua/jobs/cam_session.lua.

How a take is captured (found in the running game, 2026-11-21, probes/):

Freeze: the game's own time dilation, set near zero (the engine reports 1e-6). The simulation
clock stands still (0 s over 60 frames) while frames render, scripts run, a moved camera is
followed and a teleport still takes effect. Photo mode is not used: it has its own camera and
(per the Ultra Plus notes) switches the denoiser.

Camera: the player's first-person camera component. It hangs on the player's head and takes a
position and rotation relative to it, in the head's own frame (right, forward, up). The session
measures the head's world transform with the offset zeroed (anchor) and then places the camera
at world poses relative to that. Every answer carries the pose the engine actually rendered,
which capture() checks against the pose asked for.

Player: its body cannot be hidden from scripts (SetInvisible only hides it from characters), so
while the world is held it is moved straight down under the ground (park_depth), out of every
camera; the camera offset makes up for it. Hiding the subject therefore also holds the world,
and view() holds it for the moment of a preview.

Field of view: the camera eases towards a new field of view in world time (about a second), so
in a held world a new value never arrives (SetFOV, the fov property, zoom, re-activating the
component and a time dilation of the player's own were all tried; a memory write of the eased
value did not take either: fov.py). A rig has cameras of more than one field of view at the same
instant, so the camera stays at one field of view for a whole take: the widest any of its
cameras has (prepare_take sets it before the world is held). A camera of that field of view is
the rendered frame as it is; a narrower one is cut out of the middle and resampled to the
output size. With the render size at the output size (2560x1440, the default) that enlarges
the narrower cameras: in a rig of 54.7 and 75.9 degree cameras the 54.7 degree ones are made
from 66% of the frame. Rendering at 3840x2160 (adapter setting render_size, and
`capture install cyberpunk --resolution 3840x2160`) keeps them one to one.

Exposure: auto-exposure adapts to every view, so along a sweep the brightness of the whole frame
went up and down (Nathan, first near sweep). The engine option Rendering/ForcedExposureAvgLum
fixes it: two poses that auto-exposure both brought to about 48 of 255 read 39.9 and 24.7 at
one forced value. A take is locked to the value that reproduces its first shot's brightness,
found by bisection (_lock_exposure), and auto-exposure comes back when the subject is shown.

Settle: path tracing gathers light over many frames. After a cut, captures 40 frames apart
differed by 3.7 levels of 255 (frames 5 to 40), 1.9 (40 to 80), 1.5 (80 to 120), 1.2 (120 to 160)
and then stayed at 1.0 to 1.3 up to 640 frames: what is left is noise that does not settle, and
screens and holograms that keep playing in real time (probes/converge_probe.py, Cherry Blossom
Market at noon, 3840x2160, 13 frames/s). Hence 120 frames per shot, where RDR2 and GTA V take 40.
Auto-exposure is not the cause: with the engine's eye adaptation off the drift was the same.

Real-time clock: video ads, holograms and blinking lights run on the clock the game's own code
reads (the real time), not on the simulation's, so a held world does not hold them: one pose
captured ten times showed them changing (Cherry Blossom Market, 2026-11-22). Our clock plug-in
(addons/clock, capture_clock.asi, installed by `capture install cyberpunk`) slows that clock in
the game's exe and in Bink, its video player, while a take is captured (hold_clock). Stopped
outright the game quits at once (clean shutdown, twice); at 1/10,000 it runs on, and pixels
varying by more than 12 of 255 across ten captures went from 0.13% to 0.008% (frame rate
unchanged; probes/clock_probe.py). The default 1/5,000 leaves a margin: the game seems to need
the clock to move about a microsecond per frame (at 1/100,000 it quit), and a 17-minute take
then plays about 0.2 s of an ad. Bink held alone changed nothing: the screens follow the exe's
clock. A near sweep at the market with it: the billboard shows one frame across all 345 poses
(it played before) and the brightness jitter along the sweep fell from 0.59 to 0.045 levels of
255 (tools/sweep_flicker.py). The clock runs again when the subject is shown, and after a hold the
game's clocks run behind real time by as long as they were held.

Time steps: the game's frame time follows that clock (the world running with the clock at 0.1:
0.355 s of simulation while the clock moved 0.397 s and real time 3.5 s; Kabuki Market,
2026-11-23, probes/step_clock_probe.py). Until 2026-11-23 a step slowed only the simulation (time
dilation up to 0.1) and released the clock for the step, so what runs on it moved 1.67 s per 1/30 s
step (the same probe): ads changed picture every clip frame, foliage and people's small motions
ran 50 times too fast (Kabuki and Badlands takes, BACKLOG). A step now keeps the dilation at 1 and
slows the clock alone (session command step), so both move by the step; the clock never goes below
clock_scale, and the last microseconds are taken by the dilation.

HUD: the UI's "Empty" game context removes all of it (minimap, quest tracker, calls, hints).

Saving is locked by the loader mod whenever a save is loaded, so nothing the adapter does (moving
the player, the clock) reaches the player's own save slots.

Scripts: Cyber Engine Tweaks gives Lua mods no coroutines and no files outside the mod's own
folder, so the loader is a mod of ours with the exchange folder inside it (paths.py) and session
commands that take several frames answer later (cam_session.lua).

World frame (checked in game): metres, right-handed, +Z up, yaw counter-clockwise from +Y
(north), so forward = (-sin h, cos h, 0), the same as RDR2 and GTA V.

Linux: the same game under Proton on a headless display (capture/host; nothing in this file
knows). Measured on a CoreWeave node, 2026-11-23 (RTX PRO 6000, driver 580.105.08, GE-Proton11-12,
Xvfb 2560x1440, no DLSS 5), at the Cherry Blossom Market at noon unless said:
- held world: 0.000000000 s of simulation time over 480 frames (Badlands); one simulation time
  over the 345 shots of a near sweep that took 43.2 min;
- camera: rendered pose 0.02 mm and 0.000 degrees off the asked one; the sweep's poses 0, 172 and
  344 within 0.1 mm of the Windows take's, from the same solved rig (the scene's 66,000 rays
  answer alike: 38,587 hits, the same room grid);
- time steps: 29 steps of a 30-clip-frame take within 0.0017 ms of 1/30 s, every clip frame's
  shots at one simulation time;
- colours: the add-on's frame and a grab of the X display at one held instant differ by 0.19
  levels of 255 (11.22 with red and blue swapped);
- clock plug-in: both modules hooked under Wine; one pose captured five times, 4 frames apart,
  had 4.01% of pixels differing by more than 12 with the clock running and 0.24% with it held
  (Badlands at night, one frame per capture);
- near sweep: roughness 5.14, brightness jitter 0.069, 10.6% of pixels over 12
  (tools/sweep_flicker.py; Windows, same rig and settings: 4.38 and 0.045), no hot spot in the
  map; exposure lock 0.621 / 49.52 / 49.47 (Windows 0.642 / 51.19 / 51.02); no health problem
  and no recapture in 345 and in 89 shots;
- speed: 7.28 s per shot (Windows 2.50), 17 to 18 frames/s running and 25 to 26 held, with the
  game on 4 CPU cores (a Slurm job of 8 CPUs, which were 4 cores' threads); 5.59 s per shot, 28
  running and 36 to 38 held on 8 cores (the same job with --hint=nomultithread; BACKLOG).

Settings (job settings "adapter"):
    settle          frames between a camera move and its capture (120: see Settle below)
    first_settle    frames on the first shot (240)
    clock_settle    frames after setting the clock (240)
    park_depth      metres the hidden player is parked under the ground (12)
    populate_s      seconds the world runs after a teleport, so people and traffic arrive (15)
    step_dilation   the largest time dilation during a time step when the clock is not held (0.1; it
                    shrinks as the target nears). With hold_clock the clock alone sets the pace (Time steps)
    check_settings  refuse to capture unless the game is on the capture settings (settings.py;
                    the installer writes them into the game's settings file) (True)
    pose_tolerance_m    how far the rendered camera may be from the pose asked for (0.005)
    render_size     the size the game renders at ([2560, 1440]; [3840, 2160] keeps a rig's narrower
                    cameras at full detail when it also has wider ones, at 2.25 times the pixels)
    output_size     the size of a captured frame ([2560, 1440])
    render_vfov     the vertical field of view everything is rendered at, degrees. A take sets it
                    to its widest camera (prepare_take) and a preview to its own; 76 otherwise
    lock_exposure   hold the exposure of a take at what auto-exposure gave its first shot (True)
    accumulate      frames averaged into each shot (8), accumulate_gap frames apart (4): the path
                    tracer's noise differs from frame to frame, so a shot of one frame flickers
                    against its neighbours in a sweep, most in reflections. 8 instead of 4 (2026-11-24,
                    tools/hold_step_check.py at Badlands, 10 steps): roughness between clip frames
                    0.54/0.44 to 0.46/0.30, brightness jitter 0.05 to 0.02, 12% more frames per shot
    engine_options  engine options set while a session runs, {"Category/Path Key": value} (the names
                    GameOptions.Dump lists), given back when it ends (none)
    devices_off_m   devices within this many metres are switched off while the subject is hidden
                    (60; 0 leaves them on): their screens, holograms and blinking lights run on
                    real time and would differ from shot to shot
    lock_white_point    with DLSS 5 installed (`capture install cyberpunk --optiscaler`), hold its white
                    point for the take at what its meter settled on for the first shot (True). Left
                    on Automatic it meters every view, as an auto-exposure would: 1.10x to 2.00x
                    across 8 views of one frozen instant at the Cherry Blossom Market, the game's
                    exposure locked; held, it stayed at one value for every shot
                    (adapters/common/optiscaler_live.py)
    hold_clock      hold the real-time clock while a take is captured (True; see Real-time clock)
    clock_scale     how fast the held clock runs (0.0002; 0 makes the game quit)
    weather         the weather set and held at a location (24h_weather_sunny; "free" or "" leaves
                    the game's own, which may be a sandstorm)
"""
import math
import os
import shutil
import time

import numpy as np

from capture.adapter import Adapter, AdapterError

from ..common import mem, redlua, window
from ..common.optiscaler_live import OptiScalerLive
from . import launch, paths, settings as game_settings

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_JOB = os.path.join(HERE, "lua", "jobs", "cam_session.lua")

# camrig/v1 (x, y up, z) -> game (x, -z, y): rig +Y (up) to game +Z, rig +Z to game -Y.
A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

DEFAULTS = {"settle": 120, "first_settle": 240, "clock_settle": 240, "park_depth": 12.0, "populate_s": 15,
            "step_dilation": 0.1, "check_settings": True, "pose_tolerance_m": 0.005,
            "render_size": [2560, 1440], "output_size": [2560, 1440], "render_vfov": 76.0,
            "weather": "24h_weather_sunny", "devices_off_m": 60.0,
            "lock_exposure": True, "accumulate": 8, "accumulate_gap": 4, "hold_clock": True, "clock_scale": 0.0002, "lock_white_point": True}


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


class CyberpunkAdapter(Adapter):
    name = "cyberpunk"
    capabilities = frozenset({"obstacles", "raycast"})
    min_fps = 15   # path tracing at 3840x2160: about 45 frames/s on an RTX 5090; a shot waits 40 frames
    # The light settles on a take's first steps (QC round 1, cyberpunk-005: Cherry Blossom Market's camera
    # 16 changed 3.98x as much from clip frame 1 to 2 as later; with 3 pre-roll steps Badlands' camera 00
    # still +0.65 levels at the first step, QC round 2), and a banner's texture and a shadow arrived at
    # clip frame 14 at Kabuki (round 2, cyberpunk-013/016): the take loop steps this many times before
    # clip frame 1, showing the take's cameras in turn during them (preroll_views; capture/runner.py)
    # One change to every camera mid-clip (QC rounds 2-3; Kabuki: a plain banner gets its full pattern, the
    # puddle's and cars' reflections of it change; Badlands: grass tufts re-posed, bush shadows redrawn)
    # came 0.57 to 1.23 s of game time after the world was first held (17 to 37 steps; 2026-11-26). Not
    # real time: 30 s held at the first pose inside the pre-roll (preroll_wait_s 30) only moved it
    # (Kabuki 15 -> 9, Badlands 26 -> 23). Being tried: 60 pre-roll steps (2 s of game time at the rig).
    preroll_steps = 60
    preroll_views = True
    # At the start of a take, people standing within 1.5 m in front of a camera, inside its view, are
    # deleted too (capture/runner.py; QC round 3, cyberpunk-021: a walker 1.0-1.5 m in front of two
    # Kabuki cameras for half the clip)
    obstacle_front_m = 1.5

    def __init__(self, settings=None):
        super().__init__(dict(DEFAULTS, **(settings or {})))
        self.exchange = paths.exchange()
        self.sess = None
        self.hwnd = None
        self.subject_hidden = False
        self.frozen = False
        self.last_size = None
        self.applied = None        # what settings.apply answered when the session opened
        self._pose_asked = None    # (pos, right, fwd, up, vfov) of the last pose set
        self._stood = None         # where the player stood before it was parked
        self._last_scale = None    # the crop scale of the last frame finished
        self.devices = None        # what the last "devices off" answered
        self.exposure = None       # the exposure lock of the take, if any
        self.engine_options = {}   # engine options set for the session (setting engine_options), as the game reads them back
        self._pose_fix = np.zeros(3)   # a steady offset of the rendered camera, made up for (recover)
        self.clock_held = False    # the real-time clock held by our clock plug-in
        self.clock = None          # what the clock plug-in last answered
        self.dlss5 = OptiScalerLive(os.path.join(paths.bin_dir(), "plugins"))   # DLSS 5, if installed
        self.white_point = None    # DLSS 5's white point held for the take, if any

    # --- lifecycle -------------------------------------------------------------------------
    def _heartbeat(self):
        """The loader's heartbeat if it is fresh, else None. ingame=1 once a save is loaded and
        the world is running."""
        if redlua.heartbeat_age(self.exchange) > 5:
            return None
        return redlua.read_kv(os.path.join(self.exchange, "heartbeat.txt"))

    def _running(self):
        try:
            mem.find_pid(paths.EXE_NAME)
        except RuntimeError:
            return False
        hb = self._heartbeat()
        return bool(hb) and hb.get("ingame") == "1"

    def ensure_ready(self, restart=True):
        if self._running():
            return
        if not restart:
            raise AdapterError("Cyberpunk 2077 is not running with a save loaded and our loader mod "
                               "(no heartbeat with ingame=1 in %s)" % self.exchange)
        try:
            launch.start(self.exchange, tuple(self.settings["render_size"]))
        except RuntimeError as e:
            raise AdapterError("game restart failed: %s" % e)

    def _window(self):
        self.hwnd = window.find_game_window(mem.find_pid(paths.EXE_NAME), paths.WINDOW_CLASS)
        for _ in range(120):
            if not self.hwnd or window.focus(self.hwnd):
                return
            time.sleep(1.0)
        raise AdapterError("could not bring the game window to the front")

    def open(self):
        window.keep_awake()
        self._window()
        render = tuple(int(v) for v in self.settings["render_size"])
        if self.sess is None:
            self.sess = redlua.Session(self.exchange, SESSION_JOB, idle_s=900, timeout_s=12 * 3600, staged=True)
            if self.sess.state.get("saving_locked") != "1":
                self.close()
                raise AdapterError("saving is not locked in the game; not touching the world "
                                   "(see lock_saves in adapters/cyberpunk/lua/capture_mod/init.lua)")
            if self.settings.get("check_settings"):
                self.applied = game_settings.check(self.sess, self.exchange, game_settings.profile(render))
                if self.applied["different"]:
                    self.close()
                    raise AdapterError("the game is not on the capture settings (%s); close it and run: capture install "
                                       "cyberpunk --only settings" % ", ".join(
                                           "%s is %s, not %s" % (n, has, want) for _, n, want, has in self.applied["different"]))
            # engine options for this session (setting engine_options, "Category/Path Key": value), given back
            # when the session ends (the session job's option command)
            self.engine_options = {}
            for name, value in (self.settings.get("engine_options") or {}).items():
                cat, key = name.split(" ", 1)
                self.engine_options[name] = self.sess.cmd("option", "set %s %s %s" % (cat, key, value)).get("option")
        if self.hwnd and not window.set_client_size(self.hwnd, *render):
            raise AdapterError("the game window is %s, not %s" % (window.client_size(self.hwnd), render))
        self._close_menus()
        self._set_render_fov()

    @staticmethod
    def _menu_open(st):
        if st.get("menu") == "1" or st.get("paused") == "1":
            return True
        # the inventory held the world (time dilation 1e-6) without saying it is a menu (2026-11-22)
        return st.get("frozen") != "1" and float(st.get("dilation", 1)) < 0.5

    def _close_menus(self):
        """A game menu (pause, inventory, map...) holds the world and shows its own camera; it was
        found open after a start and after the window lost focus. Esc closes one level of it."""
        st = self.sess.cmd("state")
        for _ in range(4):
            if not self._menu_open(st):
                return
            if self.hwnd:
                window.focus(self.hwnd)
                window.press(self.hwnd, "Esc")
            time.sleep(1.5)
            st = self.sess.cmd("wait", 10)
        raise AdapterError("a game menu stays open (paused=%s menu=%s dilation=%s)"
                           % (st.get("paused"), st.get("menu"), st.get("dilation")))

    def prepare_take(self, shots):
        """Called by the take loop before the subject is hidden: the camera goes to the widest
        field of view of the take's shots while the world still runs."""
        widest = max(float(s["vfov_deg"]) for st in shots["steps"] for s in st["shots"])
        self.settings["render_vfov"] = widest
        self._set_render_fov()

    def _set_render_fov(self):
        """The one field of view everything is rendered at; it only arrives while the world runs."""
        want = float(self.settings["render_vfov"])
        st = self.sess.cmd("state")
        if abs(float(st["rendered_fov"]) - want) < 1e-3:
            return
        if st.get("frozen") == "1":
            raise AdapterError("the field of view is %s, not %s, and cannot change in a held world" % (st["rendered_fov"], want))
        self.sess.cmd("fov", "%.6f" % want)
        for _ in range(60):
            if abs(float(self.sess.cmd("wait", 20)["rendered_fov"]) - want) < 1e-3:
                return
        raise AdapterError("the field of view did not arrive at %s (it is %s)" % (want, self.sess.state["rendered_fov"]))

    def _finish(self, src, dst, vfov_deg):
        """Cuts a shot of vfov_deg out of the middle of a rendered frame and writes it at the
        output size. Returns (crop scale, rendered frame size)."""
        from PIL import Image
        scale = math.tan(math.radians(float(vfov_deg)) / 2) / math.tan(math.radians(float(self.settings["render_vfov"])) / 2)
        if scale > 1.0005:
            raise AdapterError("a shot asks for %.2f degrees, wider than the %.2f the game renders (adapter setting render_vfov)"
                               % (vfov_deg, self.settings["render_vfov"]))
        scale = min(scale, 1.0)
        with Image.open(src) as img:
            w, h = img.size
            box = (w * (1 - scale) / 2, h * (1 - scale) / 2, w * (1 + scale) / 2, h * (1 + scale) / 2)
            out = img.convert("RGB").resize(tuple(int(v) for v in self.settings["output_size"]), Image.LANCZOS, box=box)
        out.save(dst, format="BMP")
        os.remove(src)
        self._last_scale = scale
        return scale, [w, h]

    def close(self):
        if self.sess is not None:
            try:
                if self.frozen or self.subject_hidden:
                    self.hide_subject(False)
            except Exception:
                pass
            self.sess.end()
            self.sess = None
            self.frozen = self.subject_hidden = False

    def render_settings(self):
        out = {"window_client_size": window.client_size(self.hwnd), "frame_size": self.last_size,
               "render_vfov_deg": float(self.settings["render_vfov"]),
               "reshade_preset": None, "settle_frames": self.settings["settle"],
               "freeze": "time dilation near zero (the engine reports 1e-6)",
               "park_depth_m": float(self.settings.get("park_depth") or 0)}
        if self.devices:
            out["devices_switched_off"] = int(self.devices.get("devices_off", 0))
        if self.exposure:
            out["exposure_lock"] = dict(self.exposure)
        if self.engine_options:
            out["engine_options"] = dict(self.engine_options)
        out["frames_per_shot"] = int(self.settings.get("accumulate") or 1)
        if self.clock_held and self.clock:
            out["realtime_clock"] = {"held_by": "capture_clock.asi", "scale": float(self.clock.get("scale", 0)),
                                     "modules": [self.clock[k] for k in sorted(self.clock) if k.startswith("module")]}
        if self.white_point is not None:
            out["dlss5"] = {"white_point_held": self.white_point, "by": "OptiScaler DLSS 5 fork, WhitePointSource=0"}
        if np.any(self._pose_fix):
            out["camera_offset_made_up_m"] = [round(float(v), 4) for v in self._pose_fix]
        if self.applied:
            out["game_settings"] = {"%s %s" % k: v for k, v in self.applied["values"].items()}
        return out

    # --- conventions -------------------------------------------------------------------------
    def rig_rotation(self, facing_deg):
        # Rig subject faces +Z, which A sends to game -Y; turn by facing + 180 so it faces
        # the game heading facing_deg.
        return _rz(facing_deg + 180.0) @ A

    def heading_basis(self, heading_deg):
        h = math.radians(heading_deg)
        return (-math.sin(h), math.cos(h), 0.0), (math.cos(h), math.sin(h), 0.0), (0.0, 0.0, 1.0)

    # --- development -------------------------------------------------------------------------
    def eval(self, code, timeout=60):
        """Runs Lua in the game (the session job's eval command); returns its output text."""
        with open(os.path.join(self.exchange, "eval_in.lua"), "w", encoding="utf-8", newline="\n") as f:
            f.write(code)
        self.sess.cmd("eval", timeout=timeout)
        with open(os.path.join(self.exchange, "eval_out.txt"), encoding="utf-8", errors="replace") as f:
            return f.read()

    # --- the world ---------------------------------------------------------------------------
    def subject_state(self):
        st = self.sess.cmd("state")
        p = list(self._stood) if self._stood else list(redlua.vec(st["player"]))
        return {"position": self.ground_point(p), "facing_deg": float(st.get("player_heading", 0.0)),
                "clock": st.get("clock"), "title": self.place_title(p)}

    def go_to(self, position, facing_deg):
        if self.subject_hidden or self.frozen:
            self.hide_subject(False)
        r = self.sess.cmd("teleport", "%.4f %.4f %.4f %.4f" % (position[0], position[1], position[2] + 0.1, facing_deg),
                          timeout=300)
        if r.get("loaded") != "true":
            raise AdapterError("the scene did not load around %s" % (position,))
        self.sess.cmd("wait", 120)
        if self.settings.get("weather") and self.settings["weather"] != "free":
            self.set_weather(self.settings["weather"])
        # people and traffic stream in around a new spot over the next seconds
        time.sleep(float(self.settings.get("populate_s") or 0))

    def set_weather(self, name):
        """Changes to a weather type at once and holds it (24h_weather_sunny, _light_clouds,
        _cloudy, _heavy_clouds, _fog, _rain, _toxic_rain, _pollution, _sandstorm; the prefix may be
        left out); "free" lets the game choose again. Through Codeware."""
        if name.lower() == "free":
            return self.sess.cmd("weather", "free")["weather"]
        full = name if name.startswith("24h_weather_") else "24h_weather_" + name.lower()
        got = self.sess.cmd("weather", full)["weather"]
        for _ in range(20):
            if got == full:
                break
            got = self.sess.cmd("wait", 30) and self.sess.cmd("weather", "state")["weather"]
        if got != full:
            raise AdapterError("the weather did not change to %s (the game has %s)" % (full, got))
        if not self.frozen:
            self.sess.cmd("wait", 120)   # the sky and the light follow
        return got

    def ground_point(self, position):
        g = self.sess.cmd("ground", "%.4f %.4f %.4f" % (position[0], position[1], position[2]))
        z = float(g["ground_z"]) if g["ground_found"] == "true" else float(position[2])
        return [float(position[0]), float(position[1]), z]

    def set_clock(self, hhmm):
        hh, mm = (int(v) for v in hhmm.split(":"))
        clock = self.sess.cmd("clock", hh, mm)["clock"]
        if not self.frozen:
            self.sess.cmd("wait", self.settings["clock_settle"], timeout=120)
        return clock

    def hide_subject(self, hidden):
        """Takes the player (and the HUD) out of the pictures: the world is held and the player
        parked under the ground, which only a held world allows (a running one lets it fall).
        Showing it again puts it back and lets the world run."""
        self._pose_fix = np.zeros(3)
        if hidden:
            st = self.sess.cmd("state")
            if st.get("parked") != "1":
                self._stood = redlua.vec(st["player"])
            self.sess.cmd("hud", 0)
            if float(self.settings.get("devices_off_m") or 0) > 0:
                # before the hold: a device goes dark over a moment of world time
                self.devices = self.sess.cmd("devices", "off %.1f" % float(self.settings["devices_off_m"]))
                self.sess.cmd("wait", 30)
            self.sess.cmd("freeze")
            self.sess.cmd("wait", 5)
            self._park()
            self.frozen = True
        else:
            self._hold_clock(False)
            self._unlock_exposure()
            if self.white_point is not None:
                self.dlss5.unlock_white_point()
                self.white_point = None
            self.sess.cmd("unpark")
            self.sess.cmd("unfreeze")
            if float(self.settings.get("devices_off_m") or 0) > 0:
                self.sess.cmd("devices", "on")
            self.sess.cmd("hud", 1)
            self._stood = None
            self.frozen = False
        self.subject_hidden = hidden

    def _park(self):
        self.sess.cmd("park", "%.3f" % float(self.settings.get("park_depth") or 12.0))
        self.sess.cmd("anchor")

    def _pose(self, pos, right, fwd, up, vfov):
        vals = [float(v) for v in list(np.asarray(pos, float) - self._pose_fix) + list(right) + list(fwd) + list(up)] + [float(vfov)]
        vals[-1] = float(self.settings["render_vfov"])   # the camera stays wide; _finish cuts the shot out
        self.sess.cmd("pose", " ".join("%.7f" % v for v in vals))
        self._pose_asked = (np.asarray(pos, float), np.asarray(right, float), np.asarray(fwd, float), np.asarray(up, float),
                            float(vfov))

    def view(self, pos, fwd, up, vfov_deg, path):
        """One picture from a pose. The world is held for it (see the module notes) unless the
        subject is already hidden, and let go again afterwards."""
        was_hidden = self.subject_hidden
        if not was_hidden:
            self.settings["render_vfov"] = float(vfov_deg)   # the world runs: the preview's own
            self._set_render_fov()
            self.hide_subject(True)
        try:
            right = np.cross(np.asarray(fwd, float), np.asarray(up, float))
            self._pose(pos, right, fwd, up, vfov_deg)
            r = self.sess.cmd("shoot", int(self.settings["first_settle"]), "view", timeout=120)
            self._finish(self._file(r["file"]), path, vfov_deg)
        finally:
            if not was_hidden:
                self.hide_subject(False)

    # --- frozen capture ----------------------------------------------------------------------
    def begin_frozen(self, first_shot):
        if not self.subject_hidden:
            self.hide_subject(True)
        s = first_shot
        self._pose(s["pos"], s["right"], s["fwd"], s["up"], s["vfov_deg"])
        st = self.sess.cmd("wait", self.settings["first_settle"], timeout=60)
        self.frozen = True
        if st.get("frozen") != "1" or float(st.get("dilation", 1)) > 1e-5:
            raise AdapterError("the world is not held: time dilation %s" % st.get("dilation"))
        if self.settings.get("lock_exposure"):
            self._lock_exposure()
        if self.settings.get("lock_white_point") and os.path.exists(os.path.join(self.dlss5.folder, "OptiScaler.asi")):
            # DLSS 5's automatic white point follows each view like an auto-exposure: hold what it
            # settled on for this first shot (adapters/common/optiscaler_live.py)
            self.white_point = self.dlss5.lock_white_point()
        self._hold_clock(True)

    def _hold_clock(self, hold):
        """The real-time clock, held by our clock plug-in (rtclock in the session) while a take is
        captured, so video ads, holograms and blinking lights stand still with the world. Held
        after the exposure lock: auto-exposure adapts over real time."""
        if hold == self.clock_held or not self.settings.get("hold_clock"):
            return
        r = self.sess.cmd("rtclock", "hold %.9g" % float(self.settings.get("clock_scale") or 0.0) if hold else "run")
        self.clock_held = hold
        self.clock = {k[len("clock_"):]: v for k, v in r.items() if k.startswith("clock_")}
        if hold:
            self.sess.cmd("wait", 10)

    def _brightness(self, settle):
        """Mean brightness (0..255) of the rendered frame at the current pose."""
        from PIL import Image
        r = self.sess.cmd("shoot", int(settle), "exposure", timeout=120)
        p = self._file(r["file"])
        with Image.open(p) as img:
            v = float(np.asarray(img.convert("L").resize((320, 180)), dtype=np.float32).mean())
        os.remove(p)
        return v

    def _lock_exposure(self):
        """Fixes the exposure at what auto-exposure has settled on for the current view: the
        forced average luminance that gives the same frame brightness, by bisection (a larger
        value gives a darker frame)."""
        target = self._brightness(1)
        self.sess.cmd("option", "set Rendering ForcedInstantAutoExposure true")

        # log10 of the forced average luminance. The frame hardly darkens past a value of about 10
        # (Kabuki at noon, one view, 2026-11-23: 161.7 at 1, 66.2 at 10, 64.4 at 100, 61.0 at 1e6,
        # where auto-exposure gave 72; probes/exposure_range.py), so a first shot that auto-exposure
        # made darker than that floor is not reached: the search ends at its upper end and the take
        # is held a little brighter (Kabuki 71.6 for 63.2). A wider range does not help (tried).
        lo, hi = -3.0, 2.0
        got = mid = None
        for _ in range(10):
            mid = (lo + hi) / 2
            self.sess.cmd("option", "set Rendering ForcedExposureAvgLum %.6f" % (10 ** mid))
            got = self._brightness(12)
            if abs(got - target) < 0.004 * max(target, 1.0):
                break
            if got > target:
                lo = mid
            else:
                hi = mid
        self.exposure = {"forced_avg_lum": round(10 ** mid, 6), "brightness_auto": round(target, 2),
                         "brightness_locked": round(got, 2)}
        self.sess.cmd("wait", int(self.settings["settle"]), timeout=120)

    def _unlock_exposure(self):
        if self.exposure:
            self.sess.cmd("option", "set Rendering ForcedExposureAvgLum -1.0")
            self.sess.cmd("option", "set Rendering ForcedInstantAutoExposure false")
            self.exposure = None

    def set_camera(self, shot):
        self._pose(shot["pos"], shot["right"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def _file(self, rel):
        return os.path.join(self.exchange, *rel.split("/"))

    def capture(self, path, settle):
        r = self.sess.cmd("shoot", int(settle or self.settings["settle"]), "shot", timeout=120)
        more = []
        for i in range(max(1, int(self.settings.get("accumulate") or 1)) - 1):
            x = self.sess.cmd("shoot", int(self.settings.get("accumulate_gap") or 4), "shot%d" % (i + 2), timeout=120)
            more.append(self._file(x["file"]))
        if more:
            self._average(self._file(r["file"]), more)
        scale, rendered = self._finish(self._file(r["file"]), path, self._pose_asked[4])
        self.last_size = [int(v) for v in self.settings["output_size"]]
        info = {"width": self.last_size[0], "height": self.last_size[1], "rendered_size": rendered,
                "crop_scale": round(scale, 6), "health": {"problems": self._problems(r)}}
        for k in ("rendered_pos", "rendered_fwd", "rendered_up", "rendered_fov", "sim_time", "player"):
            if k in r:
                info[k] = r[k]
        return info

    def _average(self, first, more):
        """Replaces the frame `first` with the average of it and the frames in `more` (removed)."""
        from PIL import Image
        acc = np.asarray(Image.open(first).convert("RGB"), dtype=np.float32)
        for p in more:
            acc += np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
            os.remove(p)
        Image.fromarray(np.clip(acc / (len(more) + 1) + 0.5, 0, 255).astype(np.uint8)).save(first, format="BMP")

    def advance(self, seconds):
        """Exactly `seconds` of world time: the world runs at a reduced time dilation, in stages
        ten times slower each as the target comes near, and is held again. The parked player fell
        a little meanwhile, so it is parked again and the camera's anchor measured again."""
        if self.clock_held:
            # the clock our plug-in holds drives the game's frame time: slowing it alone, with no
            # time dilation, moves the simulation and everything on that clock (screens, foliage)
            # by the same step (session command step; see Time steps above)
            r = self.sess.cmd("step", "%.9f %.9g" % (seconds, float(self.settings["clock_scale"])), timeout=300)
        else:
            r = self.sess.cmd("advance", "%.9f %.6f" % (seconds, float(self.settings["step_dilation"])), timeout=300)
        if self.subject_hidden:
            self._park()
        return {"advanced_s": float(r["advanced_s"]), "ticks": int(r["frames"]), "sim_time": float(r["sim_time"])}

    def instant(self):
        """The simulation clock, to 0.1 ms: it stands still while the world is held."""
        return round(float(self.sess.cmd("state")["sim_time"]), 4)

    def wait_frames(self, n):
        self.sess.cmd("wait", int(n), timeout=30 + int(n) / 20.0)

    def screen_grab(self):
        """The window as it is on screen, cut to the field of view of the last shot or view, so
        it shows what that frame shows."""
        img = window.grab(self.hwnd) if self.hwnd else None
        if img is not None and self._last_scale:
            w, h = img.size
            s = self._last_scale
            img = img.crop((int(w * (1 - s) / 2), int(h * (1 - s) / 2), int(w * (1 + s) / 2), int(h * (1 + s) / 2)))
        return img

    KEYS = {"F13": (0x7C, 0x64), "F14": (0x7D, 0x65), "F15": (0x7E, 0x66), "F16": (0x7F, 0x67)}

    def press_key(self, key):
        vk, scan = self.KEYS[key]
        if not window.press_vk(self.hwnd, vk, scan):
            raise AdapterError("the game window is not in front; %s not sent" % key)

    def _pose_error(self, st):
        """(metres, degrees) between the pose asked for and the one the engine rendered, or None."""
        if not self._pose_asked or "rendered_pos" not in st:
            return None
        pos, _, fwd, _, _ = self._pose_asked
        d = float(np.linalg.norm(np.array(redlua.vec(st["rendered_pos"])) - pos))
        f = np.array(redlua.vec(st["rendered_fwd"]))
        cosang = float(np.clip(f @ fwd / (np.linalg.norm(f) * np.linalg.norm(fwd)), -1.0, 1.0))
        return d, math.degrees(math.acos(cosang))

    def _problems(self, st):
        problems = []
        if self.hwnd and not window.is_foreground(self.hwnd):
            problems.append("game window lost focus")
        if st.get("paused") == "1" or st.get("menu") == "1":
            problems.append("game paused (a menu is open)")
        if self.frozen and (st.get("frozen") != "1" or float(st.get("dilation", 1)) > 1e-5):
            problems.append("world not frozen")
        if self.subject_hidden and (st.get("parked") != "1" or st.get("hud_hidden") != "1"):
            problems.append("player or HUD visible")
        if self.clock_held and st.get("rtclock_held") != "1":
            problems.append("real-time clock not held")
        err = self._pose_error(st)
        if err and (err[0] > float(self.settings["pose_tolerance_m"]) or err[1] > 0.05):
            problems.append("camera %.1f mm and %.3f degrees off its pose" % (err[0] * 1000, err[1]))
        if "rendered_fov" in st and abs(float(st["rendered_fov"]) - float(self.settings["render_vfov"])) > 1e-3:
            problems.append("field of view %s, not %s" % (st["rendered_fov"], self.settings["render_vfov"]))
        return problems

    def health(self):
        return {"problems": self._problems(self.sess.cmd("state"))}

    def recover(self):
        """Refocus the window, close a pause, park and anchor again, set the pose again; the held
        world is not let go."""
        # a camera that rendered off its pose by a steady offset (Northside docks, 2026-11-22: 8.7 mm
        # on every try, the player parked under water) is asked that much the other way next time
        last = self.sess.state or {}
        if self._pose_asked and "rendered_pos" in last:
            err = np.array(redlua.vec(last["rendered_pos"])) - self._pose_asked[0]
            if np.linalg.norm(err) > float(self.settings["pose_tolerance_m"]):
                self._pose_fix = self._pose_fix + err
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.hwnd and not window.is_foreground(self.hwnd):
                window.focus(self.hwnd)
            st = self.sess.state or {}
            if st.get("paused") == "1" or st.get("menu") == "1":
                window.press(self.hwnd, "Esc")   # a menu opened (the window lost focus, a key)
                time.sleep(1.5)
            if self.subject_hidden:
                self.sess.cmd("hud", 0)
                self._park()
            if self._pose_asked:
                self._pose(*self._pose_asked)
            if not self._problems(self.sess.cmd("wait", 10)):
                self.sess.cmd("wait", self.settings["settle"])
                return True
            time.sleep(0.5)
        return False

    # --- the scene ------------------------------------------------------------------------------
    def raycast(self, starts, ends):
        """Line probes against built things and open land (not characters or vehicles).
        Returns (hit bool N, points N x 3, normals N x 3)."""
        starts, ends = np.asarray(starts, float), np.asarray(ends, float)
        inp, outp = os.path.join(self.exchange, "rays_in.txt"), os.path.join(self.exchange, "rays_out.txt")
        with open(inp, "w", encoding="utf-8", newline="\n") as f:
            for s, e in zip(starts, ends):
                f.write("%.3f %.3f %.3f %.3f %.3f %.3f\n" % (s[0], s[1], s[2], e[0], e[1], e[2]))
        self.sess.cmd("raycast", timeout=120 + len(starts) / 500.0)
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
        """Characters and vehicles within radius, as oriented boxes of stock sizes around each
        entity's position and axes (capture/obstacles.py); quest characters count as owned."""
        st = self.sess.cmd("obstacles", "%.3f %.3f %.3f %.3f" % (center[0], center[1], center[2], radius), timeout=60)
        out = []
        for n in range(1, int(st.get("obstacle_count", 0)) + 1):
            kind, owned, c, r, f, u, half = st["o%d" % n].split("|")
            v = lambda s: [float(x) for x in s.split()]  # noqa: E731
            out.append({"id": n, "kind": kind, "owned": owned == "1", "center": v(c), "axes": [v(r), v(f), v(u)],
                        "half": v(half), "approx": "stock size"})
        return out

    def remove_obstacles(self, ids):
        if not ids:
            return {"removed": 0, "skipped": []}
        r = self.sess.cmd("remove", " ".join(str(i) for i in ids))
        return {"removed": int(r.get("removed", 0)), "skipped": [int(v) for v in r.get("skipped", "").split(",") if v]}

    def end_frozen(self):
        """The take is over; the world stays held until the subject is shown again."""
        if not self.subject_hidden and self.frozen:
            self._hold_clock(False)
            self.sess.cmd("unfreeze")
            self.frozen = False
