# Backlog

Work that is designed for but not built. Each item says what the current system does instead,
and what is already in place so the item can be added without reworking the pipeline.

## Next: finish the RDR2 install test (needs someone at the PC)

**Done (2026-11-20), the clean-slate run on the development machine:** every mod file moved out
of the game folder (kept in out/clean_slate_backup/20261120_232605/), then a plain
`capture install rdr2` with the defaults (Direct3D 12, 2560x1440, the visual set, Reality
Redemption 2, OptiScaler DLSS 5): 148 steps, the files found by hash in out/mods and Downloads.
`capture verify rdr2 --launch --quick` passed every check but one (below): 2560x1440 frames
through the capture add-on, colours match the screen, 60 frames/s, DLSS 5 engaged (OptiScaler.log).
A queued ring take then ran end to end: 8 cameras, 48/48 shots, 1.14 s per shot, packaged.

Left:

1. **The administrator step.** `.\capture.ps1 install rdr2 --only machine` (Windows asks for
   approval) unregisters ReShade's machine-wide Vulkan layer; without it a second ReShade loads
   into the game and runs it out of memory. Until then Steam has to be started with
   `DISABLE_VK_LAYER_reshade_1=1`. After it: start Steam normally, `capture verify rdr2 --launch`
   (the full verify, with its small take), and expect no "1 to do".
2. **A fresh machine.** Never tried: a PC with no ReShade, no mods and nothing in out/mods, where
   `capture mods fetch rdr2` downloads every file (ReShade, the shader repositories, OptiScaler,
   Reality Redemption 2's Google Drive archive) and the C++ build tools build the capture add-on.
   Script Hook RDR2 and nvngx_dlssnr.dll still come from the person installing (never
   redistributed).

## GTA V (Legacy and Enhanced): what is left

`capture install/verify gtav`, the unattended launcher, scouting with place titles and queued
takes work (README: GTA V adapter); verify passes everything but the machine-wide administrator
step above. A full ST-DM take ran on 2026-11-21 (Legion Square: 9,411 shots in 48.4 min, every
step exactly 1/30 s, QC passed). GTA V Enhanced (`gtave`) works the same way since 2026-11-21:
verify passes (same exception), and a 32-camera moving sample at Vinewood passed QC; no full take
yet. Left:

- **Enhanced: the game's protection crashes it now and then.** Four times in about 18 sessions;
  all four of Rockstar's crash dumps (`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`)
  fault at `GTA5_Enhanced.exe+0x13f8980`, `mov qword ptr [0], 0x621`: a crash on purpose, in code
  encrypted on disk, not RedLua (Legacy's faults are in lua51.dll). What it detects is not known.
  Not the minimum-step write: the fourth came before any freeze or write, 3.4 min after a start,
  during a teleport, the crowd and an obstacle scan (Script Hook V's entity pools). None of the
  parts of a take repeated alone set it off. Suspects left: the ASI loader (Ultimate ASI Loader
  as xinput1_4.dll; the community's Enhanced loader is the dsound.dll that OpenRPF ships),
  natives the session calls (teleport, populate, crowd, ghost), the entity-pool scan. Count the
  crashes over a long run of short sessions with one change at a time. The worker restarts the
  game (stale heartbeat), about 4 min each time.
- **Enhanced: DLSS 5 works** (`--optiscaler`, 2026-11-21; README), and ray tracing switches live
  through the settings menu, so `tools/preset_ab.py --game gtave --with-dlss5` compares all four
  at one frozen instant. Left: DLSS 5 and the game's ray tracing each change GTA V far more than
  their RDR2 counterparts (mean FLIP 0.17 each, 0.26 together, against 0.055, 0.054 and 0.069),
  so their consistency between adjacent cameras of one instant needs measuring before DLSS 5
  becomes the default here. The game's
  DLSS mode renders at 1707x960 (`dlssQuality` 2); which value is DLAA (native 2560x1440 input)
  is not mapped (OptiScaler's wiki: the game's presets are hard-coded). No moving sample or full
  take with DLSS 5 yet.
- **Enhanced: launcher.** Steam keeps a window titled like its launch dialog up for about two
  minutes after Play, so the launcher answers it up to four times (30 s apart); harmless so far.
- **DLSS 5 skin controls** (`tools/dlss5_skin_sweep.py`, README): swept once at Vinewood; Nathan
  picked skin structure 2, now set by Enhanced's install. Left: RDR2 still uses the model's
  default (-1); the tool drives OptiScaler's menu by fixed positions (2560x1440, OptiScaler
  10.0.0-dev), so a menu change breaks it; the repo copy has not yet run end to end (the sweep ran
  from the same code as a scratch script). No capture yet with skin 2 and the colour grade together.
- **Enhanced capture default: NaturalVision Enhanced** + ray tracing + DLSS 5 (skin 2), no
  ReShade effects (Nathan, 2026-11-21; README). Installed from its pinned archive
  (`components/pack.py`), with its lens effects, lateral chromatic aberration and screen-space AO
  (VBAO) off and the game's motion blur at 0; checked once at Vinewood (README; NVE filled in its
  own defaults around a settings file holding only our keys). Left: a full take with it; NVE's own
  motion blur setting (`mb_config`, no label in the July build) not checked; whether NVE's
  convolution bloom streaks and halo around bright lights (a lens look too, left on) differ
  visibly between adjacent cameras (auto-exposure was checked: it does not re-adapt between poses
  under the freeze, `tools/exposure_check.py`, README); some red fringing on frame-edge window frames remains with the
  effects off (DLSS 5, the game, or NVE's bloom chromatic setting: not separated); a newer
  NVE build that runs on the current game version would bring its September features (third
  ray-traced bounce, heat haze, newer skin subsurface scattering). CoreFX and QuantV not tried
  (Nathan: NVE only).
- **GTA V visual presets** (`--preset`, README; no longer the Enhanced default): grade + Clarity
  as their capture preset, the others on F14-F18. Left: the grade's values are a first guess. In
  the grade + Clarity run the first preset's shots caught nearby people slightly moved (Chrome had
  the foreground when it started; the adapter now focuses the window before each key press);
  whether a focus change lets the frozen world step is not checked.
- **Enhanced: the settings-menu switch** is checked against screens grabbed at 2560x1440 in
  English; another window size or language needs its positions measured again. DLSS mode and
  frame scaling could go through the same menu if a comparison needs them.

- **RedLua faults.** lua51.dll faulted four times in its interpreter core, always at or just
  after the start or end of a session job (once 90 s after the full take ended, the loader idle).
  Suspected: RedLua's garbage collection of a finished job's native objects. Script Hook V then
  closes the game. The worker restarts a game that went away mid-take and takes again (up to
  twice per job; capture/worker.py, checked against a fake game in tests/test_obstacle_policy.py;
  not yet seen live), and starts a closed game before the next job. To try: keep one session for
  the game's lifetime, or stop Lua's collector during a session.
- **Street names** are still hashes (the session returns them); titles use the zone only.
- **DLSS 5 and a visual set** (options scanned 2026-11-21, nothing tried yet):
  - OptiScaler takes over a game's own DLSS/FSR2/XeSS call; Legacy has none (FXAA, MSAA, TXAA).
    DLSS5-Feeder (github jlrouzies-fr/DLSS5-Feeder), a ReShade add-on, makes that call itself
    from ReShade's colour, depth and estimated motion vectors, for Direct3D 11 among others; we
    already load ReShade, so it is the likeliest route. NVIDIA's DLSS 5 model reportedly refuses
    Direct3D 11 itself, so it may also need a Direct3D 12 bridge (OptiScaler's "w/Dx12"
    upscalers, DLSS5oneclick's dlss5-bridge). Enhanced has DLSS natively (OptiScaler would take
    it over directly; see the Enhanced DLSS item above). nvngx_dlssnr.dll is the user's, as for RDR2.
  - Visual mods for Legacy: NaturalVision Evolved (Razed, free beta, installed as OpenIV packages
    into a mods folder, tens of GB), QuantV (paid), and many ReShade presets, most made for one of
    those two. The installer copies files and edits settings; OpenIV packages (RPF archives)
    would need a new component. A ReShade-only visual set, as in RDR2, works with what exists.
  - For multi-view data: changes in the world (NVE's textures, lighting, weather) look the same
    from every camera; screen-space effects and DLSS 5 work per view, so their consistency
    between adjacent cameras needs measuring (as for RDR2).
- **Exposure.** Not locked as in RDR2: the frozen world holds eye adaptation too (moving a camera
  away and back gave the same frame within 0.04), so every shot of a take has the exposure of the
  view the freeze started on. Not yet checked across a bright and a dark view.
- **Settle.** 40 frames, carried over from RDR2 (TAA there). GTA V Legacy's anti-aliasing here is
  not temporal, so far fewer frames may do; measuring it would cut the 0.32 s per shot.
- **The game timer** does not count the frozen world's steps, so `instant()` cannot see the world
  move during a recovery; frozen frames are checked by their frame time instead.
- **Locations** are not shown in game: no scout overlay for GTA V yet (`--at x,y,z` scouts).

## The install CLI and DLSS 5, what is left

`capture install`, `verify`, `uninstall` and `mods` exist and are applied on the development
machine (README: Install). Left open:
- **DLSS 5 for captures: whether to use it.** Off/on sheets exist (out/checks/upscaler_ab/); the
  effect is mostly on faces. Not measured: consistency between adjacent cameras of one instant
  (does the model treat the same surface the same from two views), and its automatic white
  point, which is measured per frame. The game's DLSS renders at 1706x960 for 2560x1440;
  OptiScaler can force DLAA (QualityOverrides) for a native-resolution input.
- **Visual set per game** (`adapters/<game>/visual/`): the ReShade preset; OptiScaler settings
  and game graphics settings could go there too.
- **Frame rate.** 60 fps after a fresh start with VSync off, 134 fps earlier the same day; the
  cap is not VSync and is not tracked down. It sets the time per shot.
- **Things other mods draw** (an open trainer menu) end up in frames; nothing detects them.
- **Game highlights in frames.** Dropped items (a weapon, hat or loot from an NPC that died) get
  the game's pickup glow, which is not part of the scene. Rare, but it lands in every camera that
  sees the item. RDR2 natives for it: GRAPHICS::SET_PICKUP_LIGHT(object, false),
  _BLOCK_PICKUP_OBJECT_LIGHT(object, true), BLOCK_PICKUP_PLACEMENT_LIGHT(pickup, true),
  OBJECT::SET_PICKUP_PARTICLE_FX_HIGHLIGHT; and _SET_SNIPER_GLINTS_ENABLED(false) for scope glints.
  Plan: at the start of a take and at each clip frame (an item can drop mid-take), list pickups and
  objects near the rig (RedLua's native.allpick / allobjs) and switch their light off; verify on a
  dropped weapon. Object handles are small, but any hash passed needs hash_arg (RedLua float bug).
- **The exchange folder** is still `%USERPROFILE%\Documents\RDR2Modding\captures`, fixed in the
  Lua scripts; it works on any machine but is not configurable.

## Ray- or path-traced lighting in RDR2

**Now (2026-11-20):** Reality Redemption 2 Beta 2 installs with `capture install rdr2 --api d3d12
--ray-tracing` and runs (RT shadows, AO, GI, reflections, about 2 ms of GPU time at 2560x1440).
`tools/preset_ab.py` compares mod off / ray tracing off / on at one frozen instant
(out/checks/preset_ab/): ray tracing changes 2-6 levels of 255 on average in daylight (bounce light
in shade, warmer walls), 1-4 at night. With it on, a view needs about 60 frames after a camera
cut to settle (the take settle is 40). With DLSS 5 on top (`tools/preset_ab.py --with-dlss5`,
DirectX 12): mean FLIP 0.055 for ray tracing, 0.054 for DLSS 5 over it, 0.069 for both on the
sunny street; 0.026 / 0.042 / 0.051 at night; 0.048 / 0.046 / 0.065 in a thunderstorm (wet
paths), 0.087 / 0.076 / 0.109 in the game's RAIN (patchy, sun breaks). Twice, a few minutes
after a run with both on, the game's graphics failed: the GPU device was lost
(DXGI_ERROR_DEVICE_HUNG), and on 2026-11-20 23:32, two minutes after the clean-slate take, an
ERR_GFX_STATE "Game error" dialog. The worker would restart the game (no heartbeat), but a dialog
left open blocks focusing the window until the game is killed. Left: consistency between
adjacent cameras, whether captures should use it, and unregistering ReShade's Vulkan layer
(needs an administrator; meanwhile Steam is started with DISABLE_VK_LAYER_reshade_1=1).

**RedLua passes numbers through a float** (0.6.4, src/native/call.hpp): every Hash argument
above 2^24 arrives as a different hash and the game ignores the call silently (weather,
IS_MODEL_VALID). cam_session.lua wraps hashes in a RedLua Hash object (`hash_arg`); any new
Lua code that passes a hash, or an integer above 16,777,216, must do the same.

Earlier notes:

**Goal:** better light (global illumination, shadows, AO) that stays the same from every camera
of a take.

What exists (searched 2026-11-20), and what matters for multi-view captures:

- **Reality Redemption 2** (BadassBaboon, beta since early November 2026, shared through Google
  Drive): hardware ray-traced GI with up to three bounces, AO and shadows. World-space, so in
  principle the same light from every camera. Not known yet: whether it runs on Vulkan next to
  ReShade and Script Hook, how it installs, its licence. About half the frame rate at 4K on an
  RTX 5080 in one test.
- **RTGI** (Pascal Gilcher, Patreon, paid) and **Complete RT** (NiceGuy): ReShade shaders that trace
  in screen space, so the light comes from what is on screen and differs between cameras of the
  same instant. They need ReShade's depth buffer, which a ReShade forum thread reports failing
  for RDR2 on Vulkan. Not suitable for multi-view data as they are.
- **A true path tracer** for RDR2 or as a ReShade add-on: none released. Gilcher's path tracing
  add-on was shown in 2023 as a work in progress.

To try first: Reality Redemption 2, with the same checks as OptiScaler (settle frames after a cut,
the same pose twice in one frozen instant, adjacent cameras), plus the frame rate it leaves.

## Reuse captured shots when a rig is edited

**Now:** an edited rig (say ten cameras raised by 0.5 m) is captured again in full at the same
location: a new take, all shots.

**Goal:** capture only the shots the edit changed and take the rest from the earlier take. A take
mixed from two runs is only valid if both runs saw the same world at every clip frame, so this
needs the game's world state to be saved and restored exactly:

- **Snapshot and restore** per game adapter: time of day, weather, the frozen instant (clip frame
  0), entities and their animation state, and anything random that drives them. In RDR2 this
  probably means a save made at the location plus a check that the world reloads identically;
  not known to be possible yet.
- **Verify** a restore by recapturing a few reference shots and comparing them with the cache
  (the per-shot difference used in the settle test; noise floor about 1.6). Shots from a restore
  that fails the check are not reused.
- **Shot cache** keyed by (location, world-state id, clip frame, pose, intrinsics, render
  settings). A rig edit becomes a top-up take: the shots missing from the cache, captured after a
  verified restore.

**In place (2026-11-20):**

- Shot ids are derived from what the shot is (clip frame, pose in the rig frame, field of
  view), not from where it sits in a take (`capture/shots.py`). Moving one ST-DM camera by
  0.5 m changes 58 shot ids and leaves the other 12,356 as they were.
- The packager and the sheets find a shot's frame through a lookup (`capture/take.py`
  `frame_paths`), not by assuming every frame is in the take's own `raw/` folder.
- Each take records its world-state id (one per run, never reused) and its render settings
  (window size, frame size, ReShade preset, settle ticks, park height) in `take.json`.
- Adapters declare capabilities (`capture/adapter.py`); `snapshot` / `restore` are optional
  and nothing calls them yet.

## Rig providers: what is still approximate

Rig formats are providers (README: Rig providers, rigs/README.md). Left open:

- **Other camera-rig repository rigs** (hemisphere, chaowei_v2) test the performer's silhouette
  and line of sight; they are not checked with the stand-in box and may need a real SMPL-X body.

- **The scene is sampled by rays** from 11 points around the location: surfaces no ray reaches
  (behind a wall, inside a closed room) are missing, so the solver may think space behind them is
  free. Rays from more points, or from the solved cameras themselves before capture, would close
  most gaps.
- **Performers**: the solve uses a static stand-in box (the demo performer's size). With a real
  performer, its SMPL-X motion (and the SMPL-X model files) would replace the stand-in.
- **The player's own horse** (or anything else a game script owns) standing on a camera is never
  deleted, so the take is retaken until it moves or the retakes run out; moving such entities
  away instead of deleting them would avoid that.
