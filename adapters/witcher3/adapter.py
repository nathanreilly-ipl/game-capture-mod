"""The Witcher 3 behind the capture adapter contract (capture/adapter.py).

The game: "The Witcher 3: Wild Hunt - Remastered" 5.01c (exe 5.0.0.1090142, Steam app 292030),
Direct3D 12 only, started from its exe. Everything below was found and measured on 2026-11-23 on
the Windows PC (RTX 5090), at a farm in Velen unless a place is named; the probes are in probes/.

Script layer. The game's own WitcherScript, as a loose script mod (ws/capture_mod.ws) that the
game compiles at start: no script extender, no ASI loader. Scripts cannot read or write files, so
commands go in through the debug console (pasted) and answers come out through the scripts log
(session.py). There is no eval and no reload: a script change needs a restart of the game (40 to
60 s to a loaded save), or, when it failed to compile, the Retry button of the game's own error
window. One command takes 0.29 s (keys held 20 ms; 0 of the last few hundred sent again). The
console is drawn in the frame and slides shut over about 0.2 s after a command (still in frames
0.16 s after the answer, gone at 0.24 s; probes/console_probe.py), so no picture is taken sooner
than 0.45 s after one. A key typed into the game instead of the console (Enter) opens its menu,
which covers the picture and pauses the world: the state's "menu" says so and it is closed with
Esc; while the world is held the game's keys are taken away (the input context EMPTY_CONTEXT).

Freeze. A pause of our own (theGame.Pause) holds the world: engine time and game time stand still
while frames keep rendering. The camera is the photo mode's camera made the rendered one WITHOUT
the photo mode (see Camera). The game's photo mode was used until 2026-11-23 and is not any more:
switched off and on in a held world (as the first time steps did), it threw people into their
arms-out reference pose and dropped what they held, and cloth started over (Hierarch Square,
probes/cloth_step_probe.py). The wind that moves trees, grass and clouds follows engine time
(SetWindSpeedTreeTimeScale and SetWindCloudsTimeScale are multiples of it): it stands still in the
held world and moves with each time step, as it should. Measured: engine time 0.0000000 s over 9
real seconds and 480 held frames (Hierarch Square, 2026-11-23, probes/freeze_probe.py); one frame
against frames 30 to 480 later 1.45-1.63 levels of 255 mean, flat, which is the renderer's own
noise (see Noise below); 60 people, none moved over 2 s held (probes/people_step_probe.py). With
the photo mode, at Mulbrydale (2026-11-23): the same 0.0000000 s over 480 frames.

Camera. theGame.GetPhotomodeCamera(), activated as the topmost camera with the photo mode off
(cm_freeze: CmCamOn; the state's "pcam"): SetCameraWorldPosition, SetCameraWorldRotation(pitch,
yaw, roll), SetFov, SetTilt, UpdateWithoutInput, all usable in the held world. The rendered pose
read back from the camera director equals the pose asked to the 4 decimals it prints, at once and
150 frames later, and through time steps. The game's own camera (cm_gpose) is no use: it adds its
offset from the player (3.4 m here) and drifts in a held world. Conventions
(probes/geometry_probe.py): Z up; forward = (-sin yaw cos pitch, cos yaw cos pitch, sin pitch),
yaw counter-clockwise from +Y like the other games; the roll in the rotation is ignored and
SetTilt(t) turns the picture t degrees counter-clockwise (10.00 measured for 10), i.e. the
camera's up vector towards its right; the field of view is the vertical one: a 2 degree turn
moved the picture by 69.15, 43.84 and 25.23 px at 40, 60 and 90 degrees on 2560x1440, which is a
pinhole camera of 39.96, 59.64 and 89.88 degrees (within 0.6% of the number set; the method reads
a perspective shift as a translation, so this is its accuracy, not the game's); the same with the
photo mode on. The field of view changes in a held world, so each shot is rendered at its own.

Time step. Our pause off, the world run over step_frames frames (16) that each cover the same game
time, the pause on again (cm_stepe; the per-frame hook is the game's own CR4Game.OnTick, wrapped
with the script compiler's @wrapMethod). An even step lands within a share of a frame's time, so
advance() adds what a step missed by to the next one: at Hierarch Square 29 steps of 32.77 to
33.59 ms (mean 33.3324) for 33.3333 asked, 0.028 ms short over all of them (2026-11-23,
probes/cloth_clip_probe.py). On CoreWeave, where frame times jitter more, 8 frames gave steps of 29.4
to 37.4 ms, alternating long and short (QC round 1, witcher3-001/002, Mulbrydale): a step's error is
about its last frame's share, so steps are spread over 16 frames since 2026-11-25. Two methods were dropped:
- the photo mode's own tick (SetPhotomodeTickTime, cm_step) advances engine time, wind and grass
  exactly, but not people: 57 people did not move over 30 steps of 1/30 s while in a second of
  play 10 moved up to 1.6 m; they only animated in place (probes/people_step_probe.py);
- steps whose every frame covers a quarter of what is left (cm_stepw) land exactly, but their last
  frames shrink to microseconds and the next step starts at milliseconds, a jump in time step that
  the cloth solver turned into a kick at every step: an awning moved 9-12 levels of 255 per 1/30 s
  step, and more with every step, the energy staying in the cloth (Nathan saw it reset and "fall
  into" a new position; probes/cloth_rate_probe.py). The kick does not depend on how many frames a
  step takes (1 to 181) or on its length, and grows with how long the world was held before it
  (5 after about 4 s, 10-12 after 10 s or more).
Measured with even steps (2026-11-23, Hierarch Square): the awning moved 1.5-3.7 per step (mean
2.3) over 30 steps, not growing; the world running unbroken at a time scale of 0.1, sampled every
44.6 ms of game time, 1.5 (probes/cloth_clip_probe.py, side_by_side.mp4). So a little of a kick
is left at each resume (the world let run at one constant scale between two holds: about 3 for 6
and for 30 ms alike). People: 11 of 60 moved during 30 steps (up to 1.17 m), as 10 of 60 in a
second of play, none while held. Holding with a tiny time scale instead of the pause does not
help: at 1e-6 engine time stands still (0.0 ms over 30 s) but cloth keeps moving (an awning 18-19
levels between frames 1 s apart).

Player. Hidden (his items and a horse he rides with him) and, for a take, parked where he stands
as a ghost: not seen by people (SetGameplayVisibility) and without character collisions, his
horse the same (cm_park; setting ghost). He cannot be parked out of reach as in RDR2: the game puts
a teleported player on the ground whatever his physics, with all his collisions off he fell
through the world, and parked 80 m away he took the crowd with him (people within 15 m of the
spot: 59 to 7 and 22 to 1 within seconds). Measured at Hierarch Square (2026-11-23,
probes/npc_watch_probe.py, the walker followed by handle inside the game): a walker, the world
held, the player put 3 m ahead of them on their way, then 3 s of even steps. Hidden only (as takes
were before), no walker came within 1.05 m of him (1.05, 1.20, 1.74 m; two walked around him,
1.25 m to the side), and in a looser probe four of four stopped dead 2 m short. As a ghost, one
walked straight through his spot (0.13 m) and on, one turned off and one stopped; with him away,
the walkers wandered as much (strays up to 3 m: a market crowd). Few trials (8); people's own
wandering hides small effects.

Frames. ReShade (dxgi.dll beside the exe) and our capture add-on; since the script cannot write
the add-on's request file, the adapter asks for each frame itself (adapters/common/frames.py),
with the settle given to the add-on as a number of frames to let pass. 70 to 80 frames/s at
2560x1440 with path tracing, DLAA and Ray Reconstruction on (RTX 5090).

Settle. After a 90 degree camera cut in the held world (probes/settle_probe.py, three runs): the
mean difference to the settled picture is 13-14 levels of 255 two frames after the cut, 1.55 at
12, 1.27 at 35 and 1.1-1.16 from 67 frames on, where it stays (the renderer's noise between frames
far apart). 60 frames per shot (settle), 120 for the first.

Noise. Path tracing with Ray Reconstruction varies from frame to frame in a held world, evenly
over the picture, most in grass and foliage: one frame against another 2 s later 1.0-2.0 levels
of 255 mean, 16% of pixels with a standard deviation over 4 across 16 frames, 1.8% over 12.
Averaging falls slowly (the average of 16 against another of 16: 1.06): the denoiser carries noise
over many frames. Without Ray Reconstruction (the game's own denoiser) the same numbers are 1.05,
6.4%, 0.35% and 0.61; with ray tracing instead of path tracing, 1.64, 12.9%, 1.2% and 0.96
(probes/settings_sweep.py, Mulbrydale, 2026-11-23; each a fresh start of the game, so the people
differ). Which gives steadier sweeps is measured with tools/sweep_flicker.py.

Exposure. Does not re-adapt between views of the held world (tools/exposure_check.py, Novigrad
docks, noon, 2026-11-23): one view reads 54.44 of 255 after itself, 54.02 just after the bright
sky and 54.35 after the dark ground, and 54.36-54.39 later. No lock.

DLSS 5. The install default: OptiScaler's DLSS 5 fork as winmm.dll beside the exe, hooked into the
game's Streamline 2.14 and DLSS 4.5 (OptiScaler.log: "DLSS-NR composition ... model 2560x1440").
At Electors' Square, noon (tools/upscaler_ab.py, 2026-11-23): mean change 6.8-9.8 levels of 255
per view, more contrast and material detail; the same pose twice after a cut 2.2 with it, 1.8
without. Its white point is held per take as in the other games (lock_white_point).

Menus. A key that misses the console can open the game's hub menu (Enter: the world map), which
pauses the world. A teleport made under it left the new spot without grass until about 200 s into
the held world (a Mulbrydale near sweep, 2026-11-23); opened and closed in a held world it takes
nothing away (probes/menu_grass_probe.py). So go_to closes any menu first, lets the world run
populate_s with none open (again if one turned up), and begin_frozen does the same if a menu was
seen since. Every answer's state says whether a menu is open. The session looks at a frame to see
whether the console is open (its echoed commands are bright green) before a new process's first
command and after a command gets no answer, instead of toggling it blindly.

NOT measured or built yet (see BACKLOG): real-time animations (none seen yet), the time of day
and weather over a long take, hiding the player's horse, a scouting overlay.

Settings (job settings "adapter"):
    settle          frames between a camera move and its capture (60, measured above)
    first_settle    frames on the first shot of a take and for a preview (120)
    clock_settle    frames after setting the clock (120)
    populate_s      seconds the world runs after a teleport, so people arrive (10)
    render_size     the window's client size, which is the frame size ([2560, 1440])
    check_settings  refuse to capture unless the game's settings file has the capture settings (True)
    pose_tolerance_m    how far the rendered camera may be from the pose asked for (0.005)
    weather         the weather set at a location (WT_Clear; "free" leaves the game's own)
    accumulate      frames averaged into each shot (1), accumulate_gap frames apart (4)
    lock_white_point    with DLSS 5 installed, hold OptiScaler's white point for a take (True)
    ghost           while the subject is hidden, the player stays where he is but is not seen by
                    people and has no collisions (cm_park in place; True). `submit --park-height` has
                    no effect here: the game puts a teleported player on the ground.
    step_frames     frames each time step is spread over, each covering the same game time (16)

Places. The game loads one world at a time (Velen and Novigrad, Skellige, Kaer Morhen, White
Orchard, Vizima, Toussaint); a scouted location carries its world ("place") and a take loads it
first (enter_place). Place titles are the nearest fast-travel point's name within 400 m and the
region ("Mulbrydale · Velen and Novigrad"); probes/scout_fast_travel.py scouts beside them.
Saving is locked while a session is open.
"""
import math
import os
import shutil
import time

import numpy as np

from capture import host
from capture.adapter import Adapter, AdapterError

from ..common import frames, window
from ..common.optiscaler_live import OptiScalerLive
from . import launch, paths, settings as game_settings
from .session import Session, console_in, pack, parse_kv, vec

# camrig/v1 (x, y up, z) -> game (x, -z, y): rig +Y (up) to game +Z, rig +Z to game -Y.
A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

DEFAULTS = {"settle": 60, "first_settle": 120, "clock_settle": 120, "populate_s": 10, "render_size": [2560, 1440],
            "check_settings": True, "pose_tolerance_m": 0.005, "weather": "WT_Clear", "accumulate": 1, "accumulate_gap": 4,
            "lock_white_point": True, "ghost": True, "step_frames": 16}

AREAS = {"AN_NMLandNovigrad": "Velen and Novigrad", "AN_Skellige_ArdSkellig": "Skellige", "AN_Kaer_Morhen": "Kaer Morhen",
         "AN_Prologue_Village": "White Orchard", "AN_Wyzima": "Vizima", "AN_Island_of_Myst": "Isle of Mists",
         "AN_Spiral": "the spiral worlds", "AN_Prologue_Village_Winter": "White Orchard (winter)",
         "AN_Velen": "Velen", "AN_CombatTestLevel": "test level", "AN_Dlc_Bob": "Toussaint"}
# The game's worlds are loaded one at a time; a location is saved with the key of its own
# ("place": {"world": key}), which cm_world takes. Paths as the state's "world" gives them.
WORLDS = {"levels\\novigrad\\novigrad.w2w": "novigrad", "levels\\skellige\\skellige.w2w": "skellige",
          "levels\\kaer_morhen\\kaer_morhen.w2w": "kaer_morhen", "levels\\prolog_village\\prolog_village.w2w": "prolog_village",
          "levels\\wyzima_castle\\wyzima_castle.w2w": "wyzima_castle", "dlc\\bob\\data\\levels\\bob\\bob.w2w": "bob"}
RAYS_PER_COMMAND = 400       # about 25,000 characters; the console took 30,000 at once
# stock half sizes (right, forward, up) in metres where the game gives no capsule
STOCK = {"human": (0.35, 0.35, 0.95), "horse": (0.45, 1.30, 0.95), "animal": (0.40, 0.70, 0.50),
         "monster": (0.80, 0.80, 1.10)}


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


def angles(fwd, up):
    """(pitch, yaw, tilt) in degrees for a camera looking along fwd with up vector up, as the
    photo-mode camera takes them (see the module notes)."""
    f = np.asarray(fwd, float)
    f = f / np.linalg.norm(f)
    u = np.asarray(up, float)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, float(f[2])))))
    yaw = math.degrees(math.atan2(-f[0], f[1]))
    right0 = np.cross(f, [0.0, 0.0, 1.0])
    n = np.linalg.norm(right0)
    right0 = right0 / n if n > 1e-9 else np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0.0])
    up0 = np.cross(right0, f)
    tilt = math.degrees(math.atan2(float(u @ right0), float(u @ up0)))
    return pitch, yaw, tilt


class Witcher3Adapter(Adapter):
    name = "witcher3"
    capabilities = frozenset({"obstacles", "raycast"})
    # path tracing, DLAA and DLSS 5 at 2560x1440 on an RTX 5090: 54 frames/s at a Velen farm, 29 in
    # Novigrad's Hierarch Square (2026-11-23); the frame rate only sets the time a shot takes
    min_fps = 20

    def __init__(self, settings=None):
        super().__init__(dict(DEFAULTS, **(settings or {})))
        self.exchange = paths.exchange()
        self.sess = None
        self.hwnd = None
        self.subject_hidden = False
        self.frozen = False
        self.last_size = None
        self._pose_asked = None    # (pos, fwd, up, vfov) of the last pose set
        self._ents = []            # the last obstacles() answer: positions by id
        self.game_values = None    # the capture settings as the game's file has them
        self._arrived = 0.0        # when the subject was last moved (go_to)
        self._parked_from = None   # (position, heading) the player was parked from, while parked
        self.dlss5 = OptiScalerLive(paths.bin_dir(paths.game_dir()))
        self.white_point = None    # DLSS 5's white point held for the take, if any
        self._step_debt = 0.0      # game time the time steps so far fell short of what was asked
        self._frame_s = None       # the real time of one frame, as the last time step measured it

    def _dlss5_installed(self):
        return os.path.exists(os.path.join(self.dlss5.folder, "winmm.dll")) and os.path.exists(self.dlss5.ini)

    def _lock_white_point(self):
        """With DLSS 5 installed, holds the white point OptiScaler's meter settled on for the first
        shot for the whole take (adapters/common/optiscaler_live.py). Nothing without it."""
        if self.settings.get("lock_white_point") and self._dlss5_installed():
            self.white_point = self.dlss5.lock_white_point()

    def _unlock_white_point(self):
        if self.white_point is not None:
            self.white_point = None
            self.dlss5.unlock_white_point()

    # --- lifecycle -------------------------------------------------------------------------
    def _running(self):
        if not host.process_running(paths.EXE_NAME):
            return False
        st = (self.sess or Session(log=lambda *a: None)).hello()
        return bool(st) and st.get("ingame") == "1"

    def ensure_ready(self, restart=True):
        if self._running():
            return
        if not restart:
            raise AdapterError("The Witcher 3 is not running in a world with our script answering "
                               "(start it with: python -m adapters.witcher3.launch)")
        try:
            launch.start(tuple(self.settings["render_size"]))
        except RuntimeError as e:
            raise AdapterError("game restart failed: %s" % e)

    def _window(self):
        self.hwnd = self.sess.hwnd()
        for _ in range(120):
            if not self.hwnd or window.focus(self.hwnd):
                return
            time.sleep(1.0)
        raise AdapterError("could not bring the game window to the front")

    def open(self):
        window.keep_awake()
        if self.sess is None:
            self.sess = Session()
        self._window()
        render = tuple(int(v) for v in self.settings["render_size"])
        if self.settings.get("check_settings"):
            path = paths.user_settings()
            wrong = game_settings.differences(path, game_settings.profile(render))
            if wrong:
                raise AdapterError("the game is not on the capture settings (%s); close it and run: capture install "
                                   "witcher3 --only settings" % ", ".join("%s %s is %s, not %s" % w for w in wrong))
            self.game_values = game_settings.read(path, game_settings.RECORDED)
        if self.hwnd and not window.set_client_size(self.hwnd, *render):
            raise AdapterError("the game window is %s, not %s" % (window.client_size(self.hwnd), render))
        st = self.sess.state()
        if st.get("ingame") != "1":
            raise AdapterError("no world is loaded in the game")
        if st.get("held") != "1":      # a welcome panel or a menu left open pauses the world
            launch.settle(self.sess, self.hwnd, log=lambda *a: None)
        self.sess.cmd("savelock", 1)   # a session moves the player about: nothing of it into the saves

    def close(self):
        if self.sess is not None:
            try:
                if self.frozen or self.subject_hidden:
                    self.hide_subject(False)
                self.sess.cmd("savelock", 0)
            except Exception:
                pass
            self.sess = None
            self.frozen = self.subject_hidden = False

    def render_settings(self):
        out = {"window_client_size": window.client_size(self.hwnd) if self.hwnd else None, "frame_size": self.last_size,
               "reshade_preset": None, "settle_frames": self.settings["settle"],
               "freeze": "a pause of our own, the photo mode's camera without the photo mode",
               "time_step": "even steps over %d frames" % int(self.settings["step_frames"]),
               "frames_per_shot": int(self.settings.get("accumulate") or 1)}
        if self.game_values:
            out["game_settings"] = dict(self.game_values)
        if self._dlss5_installed():
            out["dlss5"] = {"installed": True, "white_point_held": self.white_point,
                            "by": "OptiScaler DLSS 5 fork as winmm.dll" + (", WhitePointSource=0" if self.white_point else "")}
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
    def console(self, op, *args):
        """Runs one command of our script (cm_<op>) and returns its Reply: the nearest thing to
        an eval this game has (probes/repl.py does the same from the command line)."""
        return self.sess.cmd(op, *args, check=False)

    # --- the world ---------------------------------------------------------------------------
    @staticmethod
    def _clock(st):
        t = int(st.get("gt", 0))
        return "%02d:%02d" % (t // 3600 % 24, t // 60 % 60)

    @staticmethod
    def _engine(st):
        return float(st["engine_base"]) + float(st["engine_rel"])

    def subject_state(self):
        st = self.sess.state()
        p = vec(st["player"])
        out = {"position": self.ground_point(p), "facing_deg": float(st.get("heading", 0.0)),
               "clock": self._clock(st), "title": self.place_title(p, st)}
        world = self._world(st)
        if world:
            out["place"] = {"world": world}
        return out

    @staticmethod
    def _world(st):
        return WORLDS.get((st.get("world") or "").lower())

    def enter_place(self, place):
        """Loads the world a location was scouted in when another one is loaded (a loading screen
        of a minute or so); go_to then moves the player within it."""
        want = (place or {}).get("world")
        if not want or self._world(self.sess.state()) == want:
            return
        if want not in WORLDS.values():
            raise AdapterError("no world named %s in The Witcher 3" % want)
        if self.subject_hidden or self.frozen:
            self.hide_subject(False)
        self.sess.cmd("savelock", 0)        # a world change is refused while saving is locked
        self.sess.cmd("world", want, check=False)
        t0 = time.time()
        while time.time() - t0 < 600:
            time.sleep(3.0)
            st = self.sess.hello(timeout=4.0)
            if st and st.get("ingame") == "1" and self._world(st) == want and st.get("black") == "0" and st.get("streaming") == "0":
                launch.settle(self.sess, self.hwnd, log=lambda *a: None)
                self.sess.cmd("savelock", 1)
                return
        raise AdapterError("the world %s did not load in 600 s" % want)

    def place_title(self, position, st=None):
        """The nearest place a player can travel to (a road sign or harbour, which carry the map's
        names) when it is within 400 m, and the region: "Mulbrydale · Velen and Novigrad"."""
        r = self.sess.cmd("place", float(position[0]), float(position[1]), float(position[2]), check=False)
        st = r.state or st or self.sess.last_state or {}
        region = AREAS.get(st.get("area"), st.get("area") or None)
        near = None
        if r.ok and r.data:
            head, _, title = r.data[0].partition(" title=")
            got = dict(kv.split("=", 1) for kv in head.split())
            if title.strip() and float(got.get("distance", 1e9)) <= 400.0:
                near = title.strip()
        return " · ".join(v for v in (near, region) if v) or None

    def _wait_loaded(self, timeout=180):
        """Until the game reports no streaming and no black screen for a second."""
        t0, quiet = time.time(), 0
        while time.time() - t0 < timeout:
            st = self.sess.state()
            quiet = quiet + 1 if st.get("streaming") == "0" and st.get("black") == "0" else 0
            if quiet >= 2:
                return st
            time.sleep(0.5)
        raise AdapterError("the scene did not finish loading in %d s" % timeout)

    def _menu_closed(self):
        if self.sess.close_menu().get("menu") == "1":
            raise AdapterError("a game menu is open and does not close with Esc")

    def go_to(self, position, facing_deg):
        if self.subject_hidden or self.frozen:
            self.hide_subject(False)
        # A menu pauses the world; a teleport made under one left the new spot without its grass
        # until long after (a Mulbrydale near sweep, 2026-11-23: no grass in its first 72 poses).
        self._menu_closed()
        self.sess.cmd("teleport", float(position[0]), float(position[1]), float(position[2]) + 0.1, float(facing_deg))
        self._arrived = time.time()
        frames.wait(self.exchange, 30)
        self._wait_loaded()
        if self.settings.get("weather") and self.settings["weather"] != "free":
            self.set_weather(self.settings["weather"])
        # people (and grass) stream in around a new spot over the next seconds, with no menu open
        self._populate()

    def _populate(self):
        """Lets the world run populate_s seconds with no menu open; again if a menu turned up meanwhile."""
        for _ in range(3):
            self._menu_closed()
            t0 = time.time()
            time.sleep(float(self.settings.get("populate_s") or 0))
            self.sess.state()
            if self.sess.menu_seen < t0:
                return
        raise AdapterError("a game menu kept opening while the world was let run")

    def set_weather(self, name):
        """Changes to a weather type at once (WT_Clear, WT_Light_Clouds, WT_Mid_Clouds,
        WT_Heavy_Clouds, WT_Rain_Storm, WT_Fog, ...; the prefix may be left out). "free" leaves the
        game's own."""
        if name.lower() == "free":
            return (self.sess.last_state or {}).get("weather")
        full = name if name.startswith("WT_") else "WT_" + "_".join(w.capitalize() for w in name.split("_"))
        self.sess.cmd("weather", full, 0.0)
        if not self.frozen:
            frames.wait(self.exchange, int(self.settings["clock_settle"]))
        return self.sess.state().get("weather")

    def ground_point(self, position):
        r = self.sess.cmd("ground", float(position[0]), float(position[1]), float(position[2]) + 1.0)
        g = dict(kv.split("=") for kv in r.data[0].split()) if r.data else {}
        z = float(g["z"]) if g.get("ok") == "1" else float(position[2])
        return [float(position[0]), float(position[1]), z]

    def set_clock(self, hhmm):
        hh, mm = (int(v) for v in hhmm.split(":"))
        self.sess.cmd("clock", hh, mm)
        if not self.frozen:
            frames.wait(self.exchange, int(self.settings["clock_settle"]))
        return self._clock(self.sess.state())

    def hide_subject(self, hidden):
        """Takes the player (with the horse it rides) and the HUD out of the pictures and holds the
        world; showing it again lets the world run."""
        if hidden:
            self.sess.cmd("hud", 0)
            self.sess.cmd("hide", 1)
            if self.settings.get("ghost") and self._parked_from is None:
                # where he stands, but out of the scene for people: not seen by them, no collisions
                # (see Player); the game cannot park him in the air (it puts him on the ground)
                st = self.sess.state()
                p = vec(st["player"])
                self._parked_from = (p, float(st.get("heading", 0.0)))
                self.sess.cmd("park", p[0], p[1], p[2])
            self.sess.cmd("freeze")
            frames.wait(self.exchange, 5)
            self.frozen = True
        else:
            self._unlock_white_point()
            self.sess.cmd("tilt", 0.0)
            self.sess.cmd("unfreeze")
            if self._parked_from is not None:
                p, heading = self._parked_from
                self.sess.cmd("unpark", p[0], p[1], p[2], heading)
                self._parked_from = None
            self.sess.cmd("hide", 0)
            self.sess.cmd("hud", 1)
            self.frozen = False
        self.subject_hidden = hidden

    def _pose(self, pos, fwd, up, vfov):
        pitch, yaw, tilt = angles(fwd, up)
        self.sess.cmd("pose", float(pos[0]), float(pos[1]), float(pos[2]), pitch, yaw, 0.0, float(vfov))
        if abs(tilt) > 1e-4 or (self._pose_asked and abs(self._pose_asked[4]) > 1e-4):
            self.sess.cmd("tilt", tilt)
        self._pose_asked = (np.asarray(pos, float), np.asarray(fwd, float), np.asarray(up, float), float(vfov), tilt)

    def _shoot(self, path, settle, stem="shot"):
        a = frames.shoot(self.exchange, stem, after=int(settle), timeout=60 + int(settle) / 5.0)
        if self.sess.console_clear_in() > 0:
            # the settle passed faster than the console slides shut (a very high frame rate): the
            # console may be in that frame, so it is taken again once the console is gone
            time.sleep(self.sess.console_clear_in())
            os.remove(a["path"])
            a = frames.shoot(self.exchange, stem, after=2)
        more = []
        for i in range(max(1, int(self.settings.get("accumulate") or 1)) - 1):
            more.append(frames.shoot(self.exchange, "%s%d" % (stem, i + 2), after=int(self.settings.get("accumulate_gap") or 4))["path"])
        if more:
            self._average(a["path"], more)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        shutil.move(a["path"], path)
        return a

    @staticmethod
    def _average(first, more):
        """Replaces the frame `first` with the average of it and the frames in `more` (removed)."""
        from PIL import Image
        acc = np.asarray(Image.open(first).convert("RGB"), dtype=np.float32)
        for p in more:
            acc += np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
            os.remove(p)
        Image.fromarray(np.clip(acc / (len(more) + 1) + 0.5, 0, 255).astype(np.uint8)).save(first, format="BMP")

    def view(self, pos, fwd, up, vfov_deg, path):
        """One picture from a pose. The world is held for it unless the subject is already hidden,
        and let go again afterwards."""
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
        if self.sess.menu_seen > self._arrived:
            # a menu was open since the world was last let run at this spot: run it again first
            if self.subject_hidden or self.frozen:
                self.hide_subject(False)
            self._populate()
        if not self.subject_hidden:
            self._menu_closed()
            self.hide_subject(True)
        s = first_shot
        self._pose(s["pos"], s["fwd"], s["up"], s["vfov_deg"])
        frames.wait(self.exchange, int(self.settings["first_settle"]))
        st = self.sess.state()
        if st.get("menu") == "1":      # closed in the held world it takes nothing away (probes/menu_grass_probe.py)
            st = self.sess.close_menu()
        self.frozen = True
        self._step_debt = 0.0
        if st.get("pcam") != "1" or st.get("held") != "1":
            raise AdapterError("the world is not held (our camera %s, our pause %s)" % (st.get("pcam"), st.get("held")))
        self._lock_white_point()

    def set_camera(self, shot):
        self._pose(shot["pos"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def capture(self, path, settle):
        a = self._shoot(path, int(settle or self.settings["settle"]))
        st = self.sess.state()
        self.last_size = [a["width"], a["height"]]
        problems = self._problems(st)
        if console_in(path):     # a closing key lost: the shot is taken again after recover()
            problems.append("the debug console is in the picture")
        info = {"width": a["width"], "height": a["height"], "health": {"problems": problems},
                "rendered_pos": st.get("cam"), "rendered_fwd": st.get("fwd"), "rendered_up": st.get("up"),
                "rendered_fov": st.get("fov"), "sim_time": "%.6f" % self._engine(st), "player": st.get("player"),
                "render_frame": a["frame"]}
        return info

    def advance(self, seconds):
        """`seconds` of world time with everything in it moving: cm_stepe lets the world run over
        step_frames frames that each cover the same game time, and holds it again (see Time step).
        An even step lands within a share of one frame's time; what it missed by is added to the
        next step, so the clip frames stay on the 1/fps grid instead of drifting off it."""
        before = self._engine(self.sess.state())
        want = float(seconds) + self._step_debt
        if want <= 0:
            want = float(seconds)
        if not self._frame_s:
            self._frame_s = 1.0 / max(1.0, frames.frame_rate(self.exchange, 0.5))
        mark = self.sess.log_size()
        r = self.sess.cmd("stepe", want, int(self.settings["step_frames"]), round(self._frame_s, 5))
        done = self.sess.wait_line("t", r.seq, mark, timeout=30.0)
        if done is None:
            raise AdapterError("a time step did not end within 30 s")
        got = parse_kv(done)
        if float(got.get("frame_s", 0) or 0) > 0.001:
            self._frame_s = float(got["frame_s"])
        frames.wait(self.exchange, 3)
        st = self.sess.state()
        if st.get("held") != "1":
            raise AdapterError("the world is not held after a time step")
        after = self._engine(st)
        self._step_debt = want - (after - before)
        return {"advanced_s": after - before, "ticks": int(got.get("frames", 0)), "sim_time": after,
                "asked_s": want, "behind_s": self._step_debt}

    def instant(self):
        """Engine time, to 0.1 ms: it stands still while the world is held."""
        return round(self._engine(self.sess.state()), 4)

    def wait_frames(self, n):
        frames.wait(self.exchange, int(n), timeout=30 + int(n) / 10.0)

    def screen_grab(self):
        return window.grab(self.hwnd) if self.hwnd else None

    KEYS = {"F13": (0x7C, 0x64), "F14": (0x7D, 0x65), "F15": (0x7E, 0x66), "F16": (0x7F, 0x67)}

    def press_key(self, key):
        vk, scan = self.KEYS[key]
        if not window.press_vk(self.hwnd, vk, scan):
            raise AdapterError("the game window is not in front; %s not sent" % key)

    def _pose_error(self, st):
        """(metres, degrees) between the pose asked for and the one the engine rendered, or None."""
        if not self._pose_asked or "cam" not in st:
            return None
        pos, fwd = self._pose_asked[0], self._pose_asked[1]
        d = float(np.linalg.norm(np.array(vec(st["cam"])) - pos))
        f = np.array(vec(st["fwd"]))
        cosang = float(np.clip(f @ fwd / (np.linalg.norm(f) * np.linalg.norm(fwd)), -1.0, 1.0))
        return d, math.degrees(math.acos(cosang))

    def _problems(self, st):
        problems = []
        if self.hwnd and not window.is_foreground(self.hwnd):
            problems.append("game window lost focus")
        if st.get("menu") == "1":
            problems.append("a game menu is open")
        if st.get("dialog") == "1":
            problems.append("a dialogue or cutscene is playing")
        if self.frozen and (st.get("pcam") != "1" or st.get("held") != "1"):
            problems.append("world not frozen")
        if not self.frozen and st.get("paused") == "1":
            problems.append("game paused")
        err = self._pose_error(st)
        if err and (err[0] > float(self.settings["pose_tolerance_m"]) or err[1] > 0.05):
            problems.append("camera %.1f mm and %.3f degrees off its pose" % (err[0] * 1000, err[1]))
        if self._pose_asked and "fov" in st and abs(float(st["fov"]) - self._pose_asked[3]) > 1e-2:
            problems.append("field of view %s, not %.4f" % (st["fov"], self._pose_asked[3]))
        return problems

    def health(self):
        return {"problems": self._problems(self.sess.state())}

    def recover(self):
        """Refocus the window, close a menu, hold the world again, set the pose again; the held
        world is not let go."""
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.hwnd and not window.is_foreground(self.hwnd):
                window.focus(self.hwnd)
            st = self.sess.last_state or {}
            if st.get("menu") == "1":
                window.press(self.hwnd, "Esc")
                time.sleep(1.5)
            if self.sess.console_open():
                window.press(self.hwnd, self.sess.CONSOLE_KEY, hold_s=0.08)
                time.sleep(self.sess.CLEAR_S + 0.2)
            if self.subject_hidden:
                self.sess.cmd("hud", 0)
                self.sess.cmd("freeze")
            if self._pose_asked:
                self._pose(*self._pose_asked[:4])
            frames.wait(self.exchange, 10)
            if not self._problems(self.sess.state()):
                frames.wait(self.exchange, int(self.settings["settle"]))
                return True
            time.sleep(0.5)
        return False

    # --- the scene ------------------------------------------------------------------------------
    def raycast(self, starts, ends):
        """Line probes against the static scene (the game's StaticTrace: terrain, buildings,
        objects; not people or animals). Returns (hit bool N, points N x 3, normals N x 3)."""
        starts, ends = np.asarray(starts, float), np.asarray(ends, float)
        n = len(starts)
        hit = np.zeros(n, bool)
        pts, nrm = np.zeros((n, 3)), np.zeros((n, 3))
        for i0 in range(0, n, RAYS_PER_COMMAND):
            i1 = min(n, i0 + RAYS_PER_COMMAND)
            answers = self._rays(np.hstack([starts[i0:i1], ends[i0:i1]]))
            for k, a in enumerate(answers):
                v = a.split("_")
                if v[0] == "1":
                    hit[i0 + k] = True
                    pts[i0 + k] = [float(x) for x in v[1:4]]
                    nrm[i0 + k] = [float(x) for x in v[4:7]]
        return hit, pts, nrm

    def _rays(self, seg):
        """The game's answers for rays seg (N x 6: start, end), one command; a command the game does
        not run in four tries is split in two and sent again (on Linux about one 400-ray command in
        50 got no answer in four tries, 2026-11-24, before Ctrl+V was fixed in window_x11.paste;
        a take's 165 such commands then failed it)."""
        try:
            r = self.sess.cmd("rays", pack(seg.ravel()), timeout=30)
        except AdapterError as e:
            if len(seg) < 50 or "no answer" not in str(e):
                raise
            half = len(seg) // 2
            self.sess.log("%d rays got no answer (%s); sent again as %d and %d" % (len(seg), str(e)[:160], half, len(seg) - half))
            return self._rays(seg[:half]) + self._rays(seg[half:])
        count, _, body = r.data[0].partition("|")
        answers = body.split("/")
        if int(count) != len(seg) or len(answers) != len(seg):
            raise AdapterError("the game answered %s of %d rays" % (count, len(seg)))
        return answers

    # --- moving things near the rig ------------------------------------------------------------
    def obstacles(self, center, radius):
        """People, animals and monsters within radius as oriented boxes around each one's position
        and heading: the game's capsule where it has one, else a stock size
        (capture/obstacles.py). Anything with tags counts as owned by a quest or a scene."""
        r = self.sess.cmd("ents", float(center[0]), float(center[1]), float(center[2]), float(radius), timeout=20)
        out, self._ents = [], []
        for line in r.data:
            head, _, name = line.partition(" name=")
            head, _, tags = head.partition(" tags=")
            e = dict(kv.split("=", 1) for kv in head.split())
            if e["kind"] in ("player", "playerhorse") or e.get("alive") == "0":
                continue
            kind = ("horse" if e.get("horse") == "1" else "human" if e.get("human") == "1" else
                    "animal" if e.get("animal") == "1" else "monster" if e.get("monster") == "1" else "human")
            half = list(STOCK[kind])
            if "r" in e and float(e["r"]) > 0.05 and kind == "human":
                half = [float(e["r"]), float(e["r"]), max(float(e["h"]) / 2, 0.5)]
            pos = vec(e["pos"])
            fwd, right, up = self.heading_basis(float(e["yaw"]))
            self._ents.append(pos)
            out.append({"id": len(self._ents), "kind": "human" if kind == "human" else "animal", "owned": bool(tags.strip()),
                        "center": [pos[0], pos[1], pos[2] + half[2]], "axes": [list(right), list(fwd), list(up)],
                        "half": half, "approx": "capsule" if kind == "human" and "r" in e else "stock size",
                        "name": name.strip()})
        return out

    def remove_obstacles(self, ids):
        if not ids:
            return {"removed": 0, "skipped": []}
        pts = [self._ents[i - 1] for i in ids]
        r = self.sess.cmd("remove", pack([v for p in pts for v in p], digits=4))
        got = dict(kv.split("=") for kv in r.text.split())
        removed = int(got.get("removed", 0))
        return {"removed": removed, "skipped": [] if removed == len(ids) else list(ids)[removed:]}

    def end_frozen(self):
        """The take is over; the world stays held until the subject is shown again."""
        if not self.subject_hidden and self.frozen:
            self.sess.cmd("unfreeze")
            self.frozen = False
