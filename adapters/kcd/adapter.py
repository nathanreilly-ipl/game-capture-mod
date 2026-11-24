"""Kingdom Come: Deliverance behind the capture adapter contract (capture/adapter.py).

The game: Kingdom Come: Deliverance (Warhorse, 2018), Steam app 379430; the exe calls itself
1.9.7.0, the main menu 1.9.8-404. CryEngine, Direct3D 11, started from its exe with -devmode
(Steam picks it up on its own). Found and measured on 2026-11-23 on the Windows PC (RTX 5090) in
and around Rattay unless a place is named; the probes are in probes/.

Script layer. CryEngine's Lua. Our script (lua/capture_mod.lua) is a mod (Mods\\capture_mod, its
pak holding Scripts\\Startup\\capture_mod.lua), which the game runs at the main menu. Commands go in
through the console (-devmode; the key left of 1; Ctrl+V pastes; a line of `#` runs as Lua) as
`#CaptureMod.cmd(seq, op, args...)`; answers come out through kcd.log in the game folder
(System.LogAlways, there at once). A console line takes at most about 250 characters (a 252-character
line ran, 332 did not), so longer commands go over in pieces, and long inputs (rays) go as Lua files
written into <game>\\Data\\capture_mod_in that our script runs: Script.ReloadScript reads loose files
there once sys_PakPriority is 0 (user.cfg). Log lines are cut at about 3,900 characters, so long
answers come in several. Lua has no io here. There is an eval (cm eval; probes/repl.py "+<lua>") and a
reload without a restart (repl.py --reload: the script through the file route in 1.5 s). 2,000 rays
in 0.68 s.

Freeze. CryEngine's time scale at 0 (t_Scale): over 6.6 s held, none of 11 people moved, the game's
timer and the world clock stood still, frames kept rendering (probes/freeze_probe.py; the same
with t_Scale 1e-6 and with CryAction.PauseGame; Calendar.SetWorldTimePaused alone holds only the
clock: a person walked 10.5 m). Held through 60 shots taken as a take takes them, none of 21
people moved 0.1 mm; one pose held 420 s gave the same frame at both ends (0.0038 levels of 255)
and none of 17 people moved 0.1 mm, while the game's own timer (System.GetCurrTime, a float) crept
5.9 ms (probes/creep_probe.py). The first takes logged that timer and saw it change by one float
step (1.95 ms) within a clip frame; the take log now has the world's time as our script counts it
(the exact sum of the steps, the timer only while the world runs free).

Time step. t_FixedStep set to dt/n makes every frame advance exactly dt/n of game time; the world
runs (t_Scale 1) for n frames, counted by a script timer that fires once per frame (script timers
follow game time: none fires while held), and is held again after the n-th. CryEngine smooths
frame times (t_Smoothing 1), so coming out of a hold the first frames ramped up from 0 (a step of
1/30 s advanced 3.8-9.5 ms); with t_Smoothing 0 every step of 1/30 s in 8 frames advanced 33.3330
ms, each frame 4.1666 ms (probes/step_probe.py, 10 steps). Even frames, which cloth needs (see The
Witcher 3). advance() carries what a step missed into the next.

Camera. CryAction.SetViewCameraByAngles(pos, angles) in DEGREES, CryEngine's Ang3: x pitch, y roll,
z yaw, the rotation Rz(yaw) Ry(roll) Rx(pitch) of a camera looking along +Y (read back: forward
(-0.5185, 0.8378, -0.1710) for pitch -10, roll 10, yaw 30); System.SetViewCameraFov in radians,
vertical. The pose read back (System.GetViewCameraPos) equals the pose asked to the 4 decimals it
prints. Held until CryAction.ResetToNormalCamera.

Player and HUD. For a take the player is a ghost where he stands (cm ghost): his body hidden
(player:Hide), perceived by nobody (the developers' invisibility command, a behaviour tree that
disables his perceptibility, run through the game's Haste with its stale state cleared first) and
without physics (people walk through him). g_showHUD 0 and wh_ui_ShowHud 0 take the HUD away.
Measured in a Rattay street (probes/npc_watch_probe.py, a walker followed by entity id, the
player put 3 m ahead of them, then 3 s of steps; 2026-11-23): as a ghost both walkers went
straight through his spot (0.28 and 0.19 m from it, 0.51 and 0.27 m sideways); hidden only, one of
four strayed 2.29 m around him; with him away, as the baseline, walkers passed 0.07-1.96 m from
the spot. Ten trials: a direction, not a fine measurement. Holding does not change people: the
same view 20 and 300 frames into a hold differs by 0.003 levels of 255 (probes/hold_pose_probe.py).
Saving is locked while a session is open (Game.AddSaveLock).

Settle. Without temporal anti-aliasing a settled frame matches the reference to 0.003 levels of
255 and the first frame after a 90 degree cut to 0.18. With SMAA 2TX (the capture set) frames
alternate between two sub-pixel offsets (0.2-0.75 against the average of four), with no trend over
1 to 35 frames after a cut; so 20 frames per shot and two frames in a row averaged
(probes/settle_probe.py, Rattay pillory).

Exposure. Does not re-adapt between views (tools/exposure_check.py, Rattay pillory, noon): one view
reads 80.21 of 255 after itself, 80.33 just after the sky (242) and 80.01 after the darkest view.

The look. The game's own top settings: Ultra High (4) on every category, SMAA 2TX, object detail and
view distances at the menu's maximum, no VSync; applied through the console when a session opens
(the game's attributes.xml sets them at start over user.cfg) and read back. Against the game's High
at one held instant in Rattay: softer, fuller shading, more grass and rocks, a mean change of
2.5-7.0 levels of 255 per view, the same frame rate (probes/visual_probe.py). No upscaler exists in
the game, so OptiScaler (DLSS 5) has nothing to hook; the free HD texture pack (a Steam DLC) is not
installed on this PC.

Places. The main menu is a view of the real Rattay level with a player in it (sv_map "rataje"
there too), so a loaded save is told by the player standing away from the menu's spot. Place names
are the developers' named teleports read from the game's Scripts.pak (places.py): the nearest
within 400 m; probes/scout_places.py scouts at them.

NOT measured yet: cloth through steps against the world running unbroken (the steps are even by
construction, which is what cloth needed in The Witcher 3).

Settings (job settings "adapter"):
    settle          frames between a camera move and its capture (20; see Settle)
    first_settle    frames on the first shot of a take and for a preview (60)
    clock_settle    frames after setting the clock (60)
    populate_s      seconds the world runs after a teleport, so people arrive (10)
    render_size     the window's client size, which is the frame size ([2560, 1440])
    pose_tolerance_m    how far the rendered camera may be from the pose asked for (0.005)
    weather         a weather preset set at a location ("free" leaves the game's own)
    accumulate      frames averaged into each shot (2), accumulate_gap frames apart (1): SMAA 2TX alternates
                    between two sub-pixel offsets, so two frames in a row average it out
    step_frames     frames each time step is spread over, each the same game time (8)
    visual          set the capture look (VISUAL) through the console when a session opens (True)
"""
import math
import os
import shutil
import time

import numpy as np

from capture import host
from capture.adapter import Adapter, AdapterError

from ..common import frames, window
from . import launch, paths, places
from .session import Session, pack, parse_kv, vec  # noqa: F401

# camrig/v1 (x, y up, z) -> game (x, -z, y): rig +Y (up) to game +Z, rig +Z to game -Y.
A = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

DEFAULTS = {"settle": 20, "first_settle": 60, "clock_settle": 60, "populate_s": 10, "render_size": [2560, 1440],
            "pose_tolerance_m": 0.005, "weather": "free", "accumulate": 2, "accumulate_gap": 1, "step_frames": 8,
            "visual": True}
# The capture look: the game's own top settings (Ultra High, the menu's maximum, on every category),
# SMAA 2TX, object detail and view distances at their menu maximum, no VSync (it capped the game at
# 60 frames/s). attributes.xml, which the game writes, sets these at start over user.cfg, so the
# session sets them through the console (they apply live) and reads them back.
SPEC = ["sys_spec_GameEffects", "sys_spec_ObjectDetail", "sys_spec_Particles", "sys_spec_Physics", "sys_spec_PostProcessing",
        "sys_spec_Shading", "sys_spec_Shadows", "sys_spec_Texture", "sys_spec_Vegetation", "sys_spec_VolumetricEffects",
        "sys_spec_Water", "sys_spec_light"]
VISUAL = dict({k: 4 for k in SPEC}, r_AntialiasingMode=3, e_LodRatio=100, e_ViewDistRatio=100,
              e_MergedMeshesViewDistRatio=100, e_ViewDistRatioVegetation=100, r_VSync=0,
              r_MotionBlur=0, r_DepthOfField=0, r_HDRVignetting=0, r_HDRGrainAmount=0, r_ChromaticAberration=0)
RAYS_PER_CALL = 20000
ANIMALS = {"Horse", "Dog", "Boar", "Deer", "Hare", "Sheep", "Pig", "Cow", "Chicken", "Hen", "Rooster", "Wolf"}


def _rz(deg):
    h = math.radians(deg)
    return np.array([[math.cos(h), -math.sin(h), 0.0], [math.sin(h), math.cos(h), 0.0], [0.0, 0.0, 1.0]])


def angles(fwd, up):
    """(pitch, roll, yaw) in degrees, CryEngine's Ang3 for a camera looking along fwd with up
    vector up: the rotation Rz(yaw) Ry(roll) Rx(pitch) takes (right, +Y, +Z) to (right, fwd, up)."""
    f = np.asarray(fwd, float)
    f = f / np.linalg.norm(f)
    u = np.asarray(up, float)
    r = np.cross(f, u)
    n = np.linalg.norm(r)
    if n < 1e-9:                      # looking straight up or down: any right will do
        r = np.cross(f, [0.0, 1.0, 0.0])
        n = np.linalg.norm(r)
    r = r / n
    u = np.cross(r, f)
    pitch = math.degrees(math.atan2(float(f[2]), float(u[2])))
    roll = math.degrees(math.asin(max(-1.0, min(1.0, -float(r[2])))))
    yaw = math.degrees(math.atan2(float(r[1]), float(r[0])))
    return pitch, roll, yaw


class KcdAdapter(Adapter):
    name = "kcd"
    capabilities = frozenset({"obstacles", "raycast"})
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
        self._arrived = 0.0
        self._step_debt = 0.0      # game time the time steps so far fell short of what was asked

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
            raise AdapterError("Kingdom Come: Deliverance is not running in a world with our script answering "
                               "(start it with: python -m adapters.kcd.launch)")
        try:
            launch.start()
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
        if self.hwnd and not window.set_client_size(self.hwnd, *render):
            raise AdapterError("the game window is %s, not %s" % (window.client_size(self.hwnd), render))
        st = self.sess.state()
        if st.get("ingame") != "1":
            raise AdapterError("no save is loaded in the game")
        pak = self.sess.cmd("cvar", "sys_PakPriority").data
        if not pak or pak[0] not in ("0", "0.0"):
            raise AdapterError("sys_PakPriority is %s, not 0 (our script's long inputs would not be read); "
                               "close the game and run: capture install kcd --only settings" % (pak[0] if pak else "?"))
        self.sess.cmd("savelock", 1)   # a session moves the player about: nothing of it into the saves
        self.applied = {}
        if self.settings.get("visual"):
            for k, v in VISUAL.items():
                self.sess.cmd("cvar", k, v)
            frames.wait(self.exchange, 60)
            self.applied = {k: (self.sess.cmd("cvar", k).data or ["?"])[0] for k in VISUAL}
            wrong = {k: v for k, v in self.applied.items() if float(v) != float(VISUAL[k])}
            if wrong:
                raise AdapterError("the game did not take the capture settings: %s" % wrong)

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
        return {"window_client_size": window.client_size(self.hwnd) if self.hwnd else None, "frame_size": self.last_size,
                "reshade_preset": None, "settle_frames": self.settings["settle"],
                "freeze": "t_Scale 0",
                "time_step": "t_FixedStep, %d even frames, t_Smoothing 0" % int(self.settings["step_frames"]),
                "frames_per_shot": int(self.settings.get("accumulate") or 1),
                "game_settings": dict(getattr(self, "applied", {}) or {})}

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
        """Runs one command of our script and returns its Reply (eval runs any Lua)."""
        return self.sess.cmd(op, *args, check=False)

    # --- the world ---------------------------------------------------------------------------
    @staticmethod
    def _clock(st):
        t = int(float(st.get("gt", 0)))
        return "%02d:%02d" % (t // 3600 % 24, t // 60 % 60)

    def subject_state(self):
        st = self.sess.state()
        p = vec(st["player"])
        return {"position": self.ground_point(p), "facing_deg": float(st.get("heading", 0.0)),
                "clock": self._clock(st), "title": self.place_title(p)}

    def place_title(self, position):
        """The nearest of the game's named places (places.py) within 400 m: "Rattay - middle pub"."""
        near = places.nearest(position)
        return near[1]["title"] if near else None

    def go_to(self, position, facing_deg):
        if self.subject_hidden or self.frozen:
            self.hide_subject(False)
        self.sess.cmd("teleport", float(position[0]), float(position[1]), float(position[2]) + 0.1, float(facing_deg))
        self._arrived = time.time()
        frames.wait(self.exchange, 30)
        if self.settings.get("weather") and self.settings["weather"] != "free":
            self.set_weather(self.settings["weather"])
        time.sleep(float(self.settings.get("populate_s") or 0))   # people stream in around a new spot

    def set_weather(self, name):
        if name.lower() == "free":
            return None
        self.sess.cmd("weather", name)
        if not self.frozen:
            frames.wait(self.exchange, int(self.settings["clock_settle"]))
        return name

    def ground_point(self, position):
        r = self.sess.cmd("ground", float(position[0]), float(position[1]), float(position[2]) + 1.0)
        if r.data and r.data[0] != "none":
            return vec(r.data[0])
        return [float(v) for v in position]

    def set_clock(self, hhmm):
        h, m = [int(v) for v in hhmm.split(":")]
        self.sess.cmd("clock", h, m)
        if not self.frozen:
            frames.wait(self.exchange, int(self.settings["clock_settle"]))
        return self._clock(self.sess.state())

    def hide_subject(self, hidden):
        """Takes the player and the HUD out of the pictures and holds the world; showing it again
        lets the world run and gives the camera back to the game."""
        if hidden:
            self.sess.cmd("hud", 0)
            self.sess.cmd("ghost", 1)          # hidden, perceived by nobody, no physics (see Player)
            self.sess.cmd("freeze")
            frames.wait(self.exchange, 5)
            self.frozen = True
        else:
            self.sess.cmd("unfreeze")
            self.sess.cmd("release")
            self.sess.cmd("ghost", 0)
            self.sess.cmd("hide", 0)
            self.sess.cmd("hud", 1)
            self.frozen = False
        self.subject_hidden = hidden

    def _pose(self, pos, fwd, up, vfov):
        pitch, roll, yaw = angles(fwd, up)
        self.sess.cmd("pose", float(pos[0]), float(pos[1]), float(pos[2]), pitch, roll, yaw, float(vfov))
        self._pose_asked = (np.asarray(pos, float), np.asarray(fwd, float), np.asarray(up, float), float(vfov))

    def _shoot(self, path, settle, stem="shot"):
        a = frames.shoot(self.exchange, stem, after=int(settle), timeout=60 + int(settle) / 5.0)
        if self.sess.console_clear_in() > 0:
            # the settle passed faster than the console slides shut: taken again once it has
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
        from PIL import Image
        acc = np.asarray(Image.open(first).convert("RGB"), dtype=np.float32)
        for p in more:
            acc += np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
            os.remove(p)
        Image.fromarray(np.clip(acc / (len(more) + 1) + 0.5, 0, 255).astype(np.uint8)).save(first, format="BMP")

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
        frames.wait(self.exchange, int(self.settings["first_settle"]))
        st = self.sess.state()
        self.frozen = True
        self._step_debt = 0.0
        if st.get("held") != "1":
            raise AdapterError("the world is not held (t_Scale %s)" % st.get("t_scale"))

    def set_camera(self, shot):
        self._pose(shot["pos"], shot["fwd"], shot["up"], shot["vfov_deg"])

    def capture(self, path, settle):
        a = self._shoot(path, int(settle or self.settings["settle"]))
        st = self.sess.state()
        self.last_size = [a["width"], a["height"]]
        return {"width": a["width"], "height": a["height"], "health": {"problems": self._problems(st)},
                "rendered_pos": st.get("cam"), "rendered_fwd": st.get("fwd"), "rendered_up": st.get("up"),
                "rendered_fov": st.get("fov"), "sim_time": st.get("world"), "player": st.get("player"),
                "frame": a["frame"]}

    def advance(self, seconds):
        """`seconds` of world time with everything in it moving: cm step runs the world over
        step_frames frames of exactly the same game time each (t_FixedStep) and holds it again.
        What a step missed is added to the next one."""
        want = float(seconds) + self._step_debt
        if want <= 0:
            want = float(seconds)
        mark = self.sess.log_size()
        r = self.sess.cmd("step", want, int(self.settings["step_frames"]))
        done = self.sess.wait_line("t", r.seq, mark, timeout=30.0)
        if done is None:
            raise AdapterError("a time step did not end within 30 s")
        got = parse_kv(done)
        frames.wait(self.exchange, 3)
        st = self.sess.state()
        if st.get("held") != "1":
            raise AdapterError("the world is not held after a time step")
        adv = float(got.get("advanced", 0))
        self._step_debt = want - adv
        return {"advanced_s": adv, "ticks": int(got.get("frames", 0)), "sim_time": st.get("world"),
                "asked_s": want, "behind_s": self._step_debt}

    def instant(self):
        """The world's time as our script counts it (the sum of the steps, plus the game's timer while
        the world runs free); the game's own timer creeps while held (see Freeze)."""
        return self.sess.state().get("world")

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
        if st.get("ingame") != "1":
            problems.append("no save loaded (the main menu?)")
        if st.get("loading") == "1":
            problems.append("the game is loading")
        if self.frozen and st.get("held") != "1":
            problems.append("world not frozen")
        if self.subject_hidden and st.get("hidden") != "1":
            problems.append("subject visible")
        err = self._pose_error(st)
        if err and (err[0] > float(self.settings["pose_tolerance_m"]) or err[1] > 0.05):
            problems.append("camera %.1f mm and %.3f degrees off its pose" % (err[0] * 1000, err[1]))
        if self._pose_asked and "fov" in st and abs(float(st["fov"]) - self._pose_asked[3]) > 1e-2:
            problems.append("field of view %s, not %.4f" % (st["fov"], self._pose_asked[3]))
        return problems

    def health(self):
        return {"problems": self._problems(self.sess.state())}

    def recover(self):
        """Refocus the window, hold the world again, set the pose again; the held world is not let go."""
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.hwnd and not window.is_foreground(self.hwnd):
                window.focus(self.hwnd)
            if self.subject_hidden:
                self.sess.cmd("hud", 0)
                self.sess.cmd("ghost", 1)
                self.sess.cmd("hide", 1)
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
        """Line probes against the static scene (terrain and static objects; not people or
        animals), through a file our script runs. Returns (hit bool N, points N x 3, normals N x 3)."""
        starts, ends = np.asarray(starts, float), np.asarray(ends, float)
        n = len(starts)
        hit = np.zeros(n, bool)
        pts, nrm = np.zeros((n, 3)), np.zeros((n, 3))
        for i0 in range(0, n, RAYS_PER_CALL):
            i1 = min(n, i0 + RAYS_PER_CALL)
            self.sess.send_numbers("rays", np.hstack([starts[i0:i1], ends[i0:i1]]).ravel())
            items = self.sess.items(self.sess.cmd("rays", timeout=120))
            if len(items) != i1 - i0:
                raise AdapterError("the game answered %d of %d rays" % (len(items), i1 - i0))
            for k, a in enumerate(items):
                v = a.split("_")
                if v[0] == "1":
                    hit[i0 + k] = True
                    pts[i0 + k] = [float(x) for x in v[1:4]]
                    nrm[i0 + k] = [float(x) for x in v[4:7]]
        return hit, pts, nrm

    # --- moving things near the rig ------------------------------------------------------------
    def obstacles(self, center, radius):
        """People and animals within radius as oriented boxes from their own bounding boxes. None
        counts as owned: saving is locked while a session is open, so a removal never reaches a
        save, and the game starts again from its save."""
        r = self.sess.cmd("ents", float(center[0]), float(center[1]), float(center[2]), float(radius), timeout=20)
        out, self._ents = [], []
        for line in r.data:
            head, _, name = line.partition(" name=")
            e = dict(kv.split("=", 1) for kv in head.split())
            pos = np.array(vec(e["pos"]))
            lo, hi = np.array(vec(e["min"])), np.array(vec(e["max"]))
            c_local = (lo + hi) / 2.0
            half = list(np.maximum((hi - lo) / 2.0, 0.1))
            right, fwd, up = self.heading_basis(float(e["yaw"]))
            centre = pos + c_local[0] * np.array(right) + c_local[1] * np.array(fwd) + c_local[2] * np.array(up)
            self._ents.append(pos)
            out.append({"id": len(self._ents), "kind": "animal" if e["class"] in ANIMALS else "human", "owned": False,
                        "center": list(centre), "axes": [list(right), list(fwd), list(up)], "half": half,
                        "approx": "bounding box", "name": name.strip()})
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
