# AGENTS.md: adding a game to capture_mod

This file is for an agent (or a person) bringing a new game into the capture pipeline, or picking
up work on an existing game adapter. `README.md` is the reference for what exists and what was
measured; `BACKLOG.md` lists what is designed for but not built. Read both before starting.

The pipeline captures a camera rig inside a running game: many cameras around a subject, all the
cameras of one clip frame seeing the same held instant, the world stepped by exactly 1/fps between
clip frames when the rig films over time, packaged in the camera-rig repository's delivery
layout. The pictures are training data that stands in for real footage. Three things matter above
everything else (next section), and most of the work of a new game goes into proving them in that
game.

## 1. What a capture must be

**Frozen while held at one instant; stepped exactly between instants.** A rig is not always a
single instant: its `time` mode may film over many clip frames (temporal rings, moving cameras,
ST-DM's 58 clip frames), and then the world runs between clip frames, by exactly 1/fps of game
time each, with its natural motion. What must hold is the instant itself: every shot taken at one
clip frame (all the cameras that see it, and every pose of a sweep at it) shows the world at that
one moment, however many real seconds the shots take. A static rig is the one-clip-frame case.
"Frozen" means measured, not assumed: over hundreds of held frames, people, vehicles, foliage,
cloth, particles and water do not move (RDR2 and GTA V: 0.000 m over 240-480 frames; Cyberpunk
2077: 113 people, 0.000 m over 480 frames). A world that still creeps by a minimum time step is not
frozen: RDR2's and
GTA V's `SET_TIME_SCALE(0)` both advance about 0.33 ms per frame, and a 48-minute take renders
about 376,000 frames (9,411 shots x 40 settle frames): two minutes of motion. If an exact hold is
impossible, the residual motion over a whole take must make no visible difference; say how much it
is and how you measured it.

**Consistent between views.** Two cameras of the same clip frame must look as if they were taken
at the same moment by two real cameras: same lighting, same exposure, same positions of
everything, and nothing in one picture that depends on where the other camera points. In
practice this rules out, or requires fixing:

- anything that animates on real time instead of game time: video screens and ads, holograms,
  blinking lights, shader animations (Cyberpunk: held by our clock plug-in, `addons/clock`);
- auto-exposure that re-adapts to each view (Cyberpunk does, GTA V does not; RDR2 locks it);
- per-camera screen-space effects: lens flare, chromatic aberration, vignette, depth of field,
  motion blur, film grain, SSR, SSAO/MXAO, screen-space GI, anything that "dithers" per frame;
- temporal accumulation that has not settled after a camera cut (TAA, DLSS, ray reconstruction,
  path tracing): each shot waits a measured number of frames;
- per-frame noise (path tracing): averaged over several frames per shot where needed;
- the game's population system spawning or despawning people in a held world;
- the player's body, the HUD, and anything a mod draws on screen.

Between clip frames (1/fps apart) motion must be plausible: nothing teleports, pops, or changes
state in a way a real scene could not in 33 ms.

**Photorealistic.** Install the best visual setup the game's community has, measured, with frame
rate no concern (captures are offline): path tracing or the game's ray tracing, the best upscaler
at native resolution (DLAA, Ray Reconstruction), DLSS 5 through OptiScaler where it works, and the
community's photorealism overhaul if there is one (GTA V: NaturalVision Enhanced; Cyberpunk: Ultra
Plus path tracing settings, optional Nova LUT). Prefer world-space effects (ray-traced GI,
reflections, shadows) over screen-space ones, and never grade twice (an overhaul with its own
tonemapping replaces a ReShade grade, it does not stack with it). Judge every visual change with
`tools/preset_ab.py` / `tools/compare_sheets.py` (side-by-side sheets with FLIP maps at one frozen
instant), and check its consistency between views before it becomes a default.

## 2. What "done" means for a game

A game is done when a fresh machine with the game installed can do all of this through the
existing CLI (`.\capture.ps1 <command>`, which is `python -m capture` through uv):

| capability | commands | what it needs from the game |
|---|---|---|
| install | `mods status/fetch <game>`, `install <game> [--game-dir] [--mods] [--dlss-nr]`, `uninstall <game>` | an install plan and a lockfile |
| check | `verify <game> --launch` | the adapter, the add-on, unattended start |
| scout | `scout --game <game> [--at x,y,z] [--facing]`, `locations [--titles] [--publish]`, an in-game overlay | `subject_state`, `go_to`, `view`, `publish_locations`, `place_title` |
| solve | `providers`, `solve --location <id> --solver <key>` | `raycast` (capability) |
| capture | `submit --location <id> --rig <file> \| --solver <key> \| --provider <p>`, `queue`, `worker --game <game>` | the frozen-capture half of the adapter |
| iterate | a script loader driven through files, a REPL/eval path, probes, `install --only scripts` | the loader and session job |

- **Any rig.** The adapter never sees rig formats. Providers (`rigs/`, `rigs/README.md`) turn a
  location's scene into a `camrig/v1` rig; `capture/placement.py` and `capture/shots.py` turn it
  into world-frame shots; the adapter only places a camera at a world pose. A fixed rig file
  (`--rig`), the camera-rig repository's solvers (`--solver yiming_stdm`) and any provider file
  must all work without game-specific code.
- **Scouting** works for a person at the keyboard and for an agent. A person walks or drives
  around with an in-game overlay that shows their position and place name, the nearest saved
  location (title, distance, red within 25 m), keys to cycle through saved locations, view one
  (front/right/back/left previews) and teleport to it; the overlay hides itself while a capture
  session runs (`session_active.txt`). An agent scouts with `capture scout --at x,y,z` or a
  game-specific helper (Cyberpunk: `probes/scout_fast_travel.py <fast-travel point>=<name>`). Both
  save to `out/locations/locations.json` with four previews and a sheet, warn within 25 m of a
  saved location and refuse within 5 m. RDR2 has the overlay (`adapters/rdr2/lua/scout_overlay.lua`,
  fed by `publish_locations`); GTA V and Cyberpunk do not yet (BACKLOG).
- **Capturing** directly (`tools/*` and probes drive the adapter) and as workers: `submit` queues
  one job per location and rig, `worker --game <game>` claims jobs from a folder queue (shareable
  between machines), restarts the game when it goes away (stale heartbeat), retakes when a camera
  ends up inside a person, and packages and QCs each take.
- **Iterating.** An agent arriving cold can read the repo, run `capture verify <game> --launch`,
  start the game unattended, send Lua (or the game's script language) into the running game and
  read the answer, edit a script and reload it without restarting the game where possible, and run
  probes that print numbers. See section 5.
- **Decoupled.** Game-specific code lives in `adapters/<game>/` only; `capture/`, `rigs/`,
  `addons/` and `capture/install/components/` stay game-agnostic. When two games need the same
  thing, it moves into `adapters/common/` or a shared component with the game's choices passed in
  (examples: `reshade.steps(..., asi_dir=)`, `clock.steps(asi_dir, control, status, modules)`,
  `redlua.Session(..., staged=True)`, the adapter attributes `min_fps` and `prepare_take`).

## 3. Repository map

```
capture/                 game-agnostic: CLI, locations, scout, scene (rays), providers, placement,
                         shot lists, take loop (runner.py), per-shot picture check (checks.py),
                         obstacles policy, packaging, sheets, folder queue, worker
capture/adapter.py       THE contract a game implements (read it first)
capture/adapters_registry.py   game name -> adapter class
capture/install/         installer framework: steps with status/apply/record, lockfiles, file
                         sources by sha256, verify, docs; install/__init__.py registers games
capture/install/components/   shared install pieces: reshade, addon (our ReShade add-on), clock
                         (our clock plug-in), optiscaler (DLSS 5), pack (multi-GB overhauls)
addons/capture/          our ReShade add-on: saves the frame after ReShade's effects on request
addons/clock/            our clock plug-in (ASI): slows the real-time clock of named modules
adapters/common/         shared by adapters: window (focus, keys, grabs, client size), mem (process
                         memory), redlua (loader script + session client for RedLua games)
adapters/<game>/         adapter.py, install.py, mods.lock.json, launch.py, lua/ (loader, session
                         job), visual/ (presets), probes/ (how the method was found), settings
rigs/                    rig providers (file, ring, camrigs) and their contract
tools/                   game-agnostic comparison tools: preset_ab, upscaler_ab/_sweep,
                         compare_sheets (FLIP), exposure_check, sweep_flicker, frame_report,
                         dlss5_skin_sweep
tests/                   no-game tests: test_install.py (sandboxed plans), test_obstacle_policy.py,
                         test_providers.py; run each with `uv run --project . python tests/<file>`
out/                     everything produced (gitignored): mods, locations, queue, takes, probes,
                         install records, config.json (game folders); CAPTURE_OUT moves it
```

Paths an install may need, when they cannot be found: `--game-dir` (remembered in
`out/config.json`), `--mods <folder|archive|bundle>` (repeatable; third-party files are found by
hash), `--dlss-nr <nvngx_dlssnr.dll>` (OptiScaler's DLSS 5 model, never redistributed),
`CAPTURE_OUT`, `CAMRIGS_REPO` (the camera-rig repository), `CAPTURE_RIG_PATH` (more providers).

## 4. The architecture a game plugs into

```
 Python (capture/, adapters/<game>/adapter.py)                     the game process
 ─────────────────────────────────────────────                     ────────────────
 adapter ── session_in.txt (seq, cmd, args) ──────────────────────▶ session job (Lua)
         ◀── session_out.txt (seq, status, answer lines, state) ─── runs commands per frame
         ── command.txt (start a job) ─────────────────────────────▶ loader script
         ◀── heartbeat.txt (about 1/s), result.txt ──────────────── (RedLua / CET / ...)
                                       session job ── request.txt ─▶ ReShade + our add-on
                                                   ◀── ack.txt ──── frame -> jobs/<id>/*.bmp
 adapter (optional) ── clock.txt ──────────────────────────────────▶ capture_clock.asi
                    ◀── clock_status.txt ─────────────────────────── (hooks the exe's clock)
```

- **The exchange folder** is a folder both sides can write (per game; Cyberpunk's sits inside its
  mod folder because Cyber Engine Tweaks mods may only touch their own folder). Frames only pass
  through it; the adapter moves them to `out/`.
- **The loader** runs in the game from start-up, writes the heartbeat, and runs job files on
  request. A job returns a function of `ctx` (`ctx.log`, `ctx.wait`/`ctx.after`, `ctx.capture`,
  `ctx.defer`, `ctx.each_tick`, `ctx.result`). RedLua jobs are coroutines; CET has none, so
  Cyberpunk's commands that take several frames answer later (`ASYNC` + `reply`).
- **The session job** (`adapters/<game>/lua/jobs/cam_session.lua`) is one long job driven a
  command at a time by `redlua.Session` (works for any loader speaking the protocol). Every answer
  carries the state (frozen, paused, player, rendered camera pose and FOV, game time, ...), which
  the adapter checks after every shot. `ctx.defer` undoes everything the session changed, however
  it ends. Typical commands: `state, wait n, shoot n stem, freeze, unfreeze, advance s, pose ...,
  teleport x y z yaw, ground x y z, clock h m, weather, hud 0|1, park, obstacles, remove,
  raycast, eval, end`.
- **The capture add-on** (`addons/capture`) saves the frame after ReShade's effects, so a ReShade
  preset is part of the picture by design. It is shared by every game; ReShade must load in the
  game (as `dxgi.dll`, `d3d12.dll`, or `ReShade.asi` through the game's ASI loader).
- **The adapter** (`adapters/<game>/adapter.py`) implements `capture.adapter.Adapter`. Its module
  docstring is where the game's method lives, with numbers and dates: how the freeze works and was
  measured, the camera, settle, exposure, player hiding, quirks. Its settings (`DEFAULTS`) travel
  with each job under `settings["adapter"]` (`submit --settle`, `--park-height` set two of them);
  probes and tools pass any of them when they build the adapter.

## 5. Workflow for a new game

Work in this order; each step has a check that must pass before the next one builds on it. Write
down every number you measure (README and the adapter's docstring), with the date and place.

### 5.0 Reconnaissance (no code)

- Game version and store, graphics APIs, whether it runs offline/story mode (captures never touch
  online modes; anti-cheat must be off or absent: GTA V runs with `-nobattleye`).
- A script layer that can run code every frame, call engine functions, and read/write files:
  Script Hook + RedLua (RDR2, GTA V), Cyber Engine Tweaks + RED4ext/Codeware (Cyberpunk), or
  similar. Note its exact supported game version; a game update usually breaks it.
- How mods load: an ASI loader (which DLL name the exe actually imports at start: GTA V Enhanced
  does not import `dinput8.dll`, so `xinput1_4.dll`), which folders it reads (CET's loader reads
  only `bin\x64\plugins`), folder locks (GTA V Enhanced holds its whole folder read-only while it
  runs).
- The community's photorealism setup for captures (frame rate no concern) and its licences: which
  files may be downloaded by script (pinned, `mods fetch`) and which must be supplied (Nexus logins,
  licences forbidding redistribution: `docs/MOD_FILES.md`).
- How the game starts without anyone at the keyboard: launchers, "press any key" screens, intro
  videos (Cyberpunk: Space skips them), Steam prompts, where saves load from.

### 5.1 Script layer and loader

- Install the script layer by hand once, then a loader that speaks the exchange protocol: for a
  RedLua game reuse `adapters/common/lua/capture_loader.lua` (installed with the game's exchange
  folder written in, `redlua.loader_text`); otherwise write one in the game's script language
  (Cyberpunk: `adapters/cyberpunk/lua/capture_mod/init.lua`) with the same files.
- The heartbeat should say more than "alive": Cyberpunk's has `world` (a save is loaded) and
  `ingame` (the ground under the player has loaded and the clock runs), because commands sent while
  a save loads crashed the game.
- Lock saving while a session can move the player (Cyberpunk's loader adds a save lock whenever a
  world is loaded), so nothing reaches the player's own save slots.
- Check: a smoke job runs and its result comes back; an `eval`/REPL command runs arbitrary script
  code in the game and returns output (Cyberpunk: `python -m adapters.cyberpunk.probes.repl
  "<lua>"`; RDR2: `scripts/run_job.ps1 <job>`). This is the agent's main research tool: use it to
  dump the API, try calls, and probe before writing adapter code.

### 5.2 Frames

- ReShade for the game's API plus our add-on (`capture/install/components/reshade.py`,
  `addon.py`), with no effects at first. One ReShade only: a second copy (ReShade's machine-wide
  Vulkan layer) ran RDR2 out of memory.
- Check: a requested frame arrives at the window's client size, 16:9 (other ratios letterbox),
  2560x1440 by default, and its colours match a screen grab (`verify`'s colour check; the add-on
  once had red and blue swapped).

### 5.3 Unattended start and recovery

- `adapters/<game>/launch.py`: close the game (and wait until the process is gone), start it,
  get through launchers and intros, load the last save, wait for the heartbeat's "in game".
  Measure how long it takes. Keep the display awake (`window.keep_awake`): with it asleep, screen
  grabs return the last picture.
- Prefer starts that cannot raise a dialog nobody answers (Cyberpunk is started from its exe:
  Steam's first-time setup raised an administrator prompt on every Steam start). Clicks and keys
  only go to the game's window while it is in front (`window.press`).
- `ensure_ready(restart=True)` uses it; the worker restarts a game that went away mid-take.
- Check: three starts in a row reach "in game" without help.

### 5.4 Probes: find the method, with numbers

Each probe lives in `adapters/<game>/probes/` (Python) or `lua/jobs/` (script), prints a report
and saves pictures under `out/probes/`. They are how the method was found, so keep them.

1. **Freeze** (`freeze_probe`): candidates are the game's time scale, time dilation, photo-mode
   freeze, pause; measure people's movement and the game clock over 240-480 held frames, whether
   frames still render, whether a moved camera re-renders, whether scripts and teleports still
   run. Minimum time steps are common (RDR2, GTA V: 1/3000 s); GTA V's was a writable float found
   by value (`adapters/gtav/timestep.py`). A step or clock of exactly 0 crashed GTA V and made
   Cyberpunk quit: hold at a tiny non-zero value.
2. **Camera** (`geometry_probe`): how to place a camera at an exact world pose and vertical FOV
   while frozen (script camera, a camera component, or memory writes as in RDR2's
   `render_camera.py`). Project known world points and compare with the rig's pinhole model: all
   three games are within 1 px (Cyberpunk 0.04 px at 3840x2160). Check roll, pitch and FOV range.
   Find out whether FOV or camera changes ease over game time (Cyberpunk's FOV does, so a held
   world cannot change it: render at the widest FOV and crop).
3. **Settle** (`settle_probe`, `converge_probe`): after a camera cut, capture every N frames and
   measure the difference to the settled picture; pick the frame count where it stops falling
   (RDR2 40, GTA V 40, Cyberpunk path traced 120).
4. **Noise** (`noise_probe`): the same pose captured many times a few frames apart; per-pixel
   standard deviation map. Spatially uniform: renderer noise (average frames per shot); hot spots:
   something animating (go to 6).
5. **Exposure** (`tools/exposure_check.py`): does auto-exposure re-adapt between poses while
   frozen? If yes, lock it (Cyberpunk: `Rendering/ForcedExposureAvgLum` found by bisection to match
   the first shot; RDR2: photo-mode exposure lock).
6. **Real-time animation** (`clock_probe` in Cyberpunk): screens, holograms, blinking lights that
   keep changing in a held world. Try the game's own switches first (devices off, pause states),
   then `addons/clock` (`capture install <game> --only clock`, its `Modules=` list naming the exe
   and the video player): measure the share of pixels varying across repeated captures with the
   clock running and held, and find the slowest clock scale the game tolerates.
7. **Time steps**: advance exactly 1/fps and freeze again; measure the game clock per step
   (RDR2 within 2 ms, GTA V and Cyberpunk within 0.002 ms).
8. **Subject and scene**: hide the player (invisible is often not enough: collision and AI still
   react; RDR2 "ghost" natives, parking the player 10 m up or 12 m underground), the HUD, other
   overlays; teleport and wait for streaming; ground height; raycasts against the static scene
   (collision groups); people/vehicles as oriented boxes; deleting them while frozen.

### 5.5 The adapter

- Implement every method of `capture/adapter.py`; keep the game's axes inside the adapter
  (`rig_rotation`, `heading_basis`: all three games so far are Z up, heading counter-clockwise from
  north, forward = (-sin h, cos h, 0)).
- `capture()` returns health problems the take loop acts on: window focus, a menu or pause open,
  the subject visible, the world not frozen, the rendered pose off the asked pose (Cyberpunk: 5 mm,
  0.05 degrees), the FOV wrong, the real-time clock not held. `recover()` fixes what it can
  without moving the frozen world; `instant()` must change if the world moved.
- Capabilities: `raycast` (scene for solved rigs), `obstacles` (people and vehicles in cameras).
- Check: `capture verify <game> --launch` passes (install complete, scripts answer, frame rate,
  a frame through the add-on, colours, a frozen 8-camera take with 1/30 s steps, packaging).

### 5.6 The install plan (the modpack)

- `adapters/<game>/install.py`, registered in `capture/install/__init__.py`: `GAME`, `TITLE`,
  `EXE` (process name; `EXE_PATH` if it is not in the game folder's root), `LOCK`, `OPTIONS`,
  `find_game_dir()`, `installed_dirs()`, `steps(ctx)`, `after_install(ctx)`.
- `adapters/<game>/mods.lock.json` pins every third-party file by sha256 (inside archives as
  downloaded; `source` download or supplied; `pack: true` for multi-GB overhauls). Run
  `capture mods docs` to regenerate `docs/MOD_FILES.md` (after merging branches, regenerate rather
  than hand-merge).
- Steps come from shared components plus the game's own: script layer, our loader and scripts
  (tag `scripts`, can be written with the game running), ReShade and the add-on, the clock plug-in,
  OptiScaler, the visual set, and the game's settings written into its settings file with the game
  closed (setting them live crashed Cyberpunk; games rewrite some on first start, so verify by
  reading back). Options turn parts on and off; turning one off removes its files (backed up;
  a pack's files are removed outright, since its archive installs them again).
- Everything is recorded for `capture uninstall`; `--dry-run` shows every step; `--only <tag>`
  re-runs one part while iterating.
- Check: `install` twice in a row does nothing the second time; `tests/test_install.py` covers the
  plan in a sandbox where the game has a section (add one for a new game).

### 5.7 Scouting

- `subject_state`, `go_to` (teleport, wait for the scene and the population), `ground_point`,
  `set_clock`, `set_weather`, `view` (previews with the world running or briefly held),
  `place_title` (readable names from the game's zones or districts).
- `publish_locations(locations)`: write the saved locations where the in-game overlay reads them,
  and the overlay itself (the RDR2 one is the model: position, place, nearest saved location and
  distance, cycle, view, teleport, hides during sessions). Choose keys the game and other mods do
  not use; write them down.
- Check: scout three kinds of places (dense city, interior-like, open land), by hand and by agent;
  previews look right; the overlay shows them.

### 5.8 Takes, then consistency clips (section 6)

- A ring sample (`submit --provider ring --set count=8`), then a near sweep
  (`--solver yiming_stdm --cameras "H_near_sweep_t000"`: 345 poses at one instant, a dense camera
  path that turns any inconsistency into visible flicker), then a full ST-DM take.
- Send the sweep videos and sheets to the person you work for; they are the fastest review.

### 5.9 Documentation

- README: a section for the game (setup commands, mods and why, how a take is captured with the
  measured numbers, what is open). The adapter's docstring carries the method; probes carry how
  it was found. BACKLOG: what is designed for but not built.

## 6. Proving consistency: clips and numbers

Run these at several kinds of places (dense city with screens and signs, interiors or covered
markets, open land, water, night) and whenever a visual setting, mod or adapter change could
affect them. Keep the reports under `out/probes/` or `out/checks/`.

```powershell
# one pose in a held world, captured repeatedly (the game's probe; Cyberpunk's shown)
uv run --project . python -m adapters.cyberpunk.probes.clock_probe --location <id> --phases "run,hold@0.0002"
# a dense camera path at one instant: 345 poses, one video
.\capture.ps1 submit --game <game> --solver yiming_stdm --location <id> --cameras "H_near_sweep_t000"
# a short clip over time: 30 clip frames at 1/30 s, sweeps thinned out
.\capture.ps1 submit --game <game> --solver yiming_stdm --location <id> --last-frame 30 --sweep-stride 30
.\capture.ps1 worker --game <game> --once
# then watch <take>/package/*/rgb.mp4 and read <take>/sheets/ (sweep, time, ring) and capture_log.jsonl
```

1. **Same pose, held world** (`noise_probe`/`clock_probe`): 8-12 captures a few frames apart.
   Report the mean difference between neighbours, the share of pixels whose standard deviation is
   over 4 and over 12 levels of 255, and save the standard-deviation map. A uniform faint map is
   renderer noise; any bright region is something changing (screen, light, hologram, a person,
   exposure). Cyberpunk at the Cherry Blossom Market, 2026-11-22: 0.13% of pixels over 12 with the
   real-time clock running, 0.008% with it held.
2. **Near sweep at one instant** (345 poses, `package/*/rgb.mp4` and `sheets/sweep.png`): watch it.
   Flicker of the whole frame is exposure; flicker in reflections is noise or temporal history;
   flicker in one spot is an animation; anything that jumps between neighbouring poses is a bug.
   Measure it with `tools/sweep_flicker.py <take> [<take> ...]`: each pose against the average of
   its neighbours (smooth motion cancels, flicker does not), the share of pixels off by more than
   12, the brightness jitter, the worst poses and a map of where. Compare takes of the same rig at
   the same place only (parallax sets the floor). Cyberpunk, Cherry Blossom Market: roughness 8.25
   and brightness jitter 1.53 with nothing fixed, 4.80 and 0.59 with the exposure lock, 4-frame
   averaging and devices off, 4.38 and 0.045 with the real-time clock held as well.
3. **Two cameras, one instant**: the same surface seen from adjacent cameras must match in colour
   and brightness; screen-space effects fail here first. `tools/compare_sheets.py` puts FLIP maps
   next to each pair.
4. **Clip over time** (a moving-camera or temporal-ring sample, `--last-frame 30`): the world moves
   between clip frames as it would in 1/30 s; one pose across clip frames changes steadily
   (traffic, foliage), never within a clip frame, and nothing pops,
   teleports, spawns or despawns (GTA V's population budget did, in a frozen world, until its
   multipliers were set to 0).
5. **The time between shots**: record the game clock (`instant()`, `sim_time`) in every shot's
   log line; it must not change within a clip frame. Check `capture_log.jsonl` after every take.

## 7. Problems every game has had

- **No true freeze**: time scale 0 still steps (RDR2, GTA V); a hold at exactly 0 crashes or quits
  (GTA V step, Cyberpunk clock). Find the minimum and hold just above it.
- **Real time vs game time**: screens, ads, holograms, blinking lights, some shaders run on the
  real clock, which no freeze holds. Devices can sometimes be switched off; otherwise the clock
  plug-in.
- **Temporal rendering**: TAA, DLSS, ray reconstruction and path tracing carry history; after a
  camera cut the picture keeps changing for 40-120 frames. Measure the settle; average frames for
  noise; never reuse history between cameras (OptiScaler's edit cache off).
- **Auto-exposure** per view (Cyberpunk) needs a lock; check every game (`tools/exposure_check.py`).
- **Per-camera effects** baked into presets and overhauls: lens flares, fringing, vignette, DoF,
  motion blur, film grain, SSAO/SSR/screen-space GI. Turn them off in the game, the overhaul
  (NVE's own settings file) and ReShade.
- **Camera smoothing**: FOV and camera blends that ease over game time do not arrive in a held
  world (Cyberpunk: render at the widest FOV, crop narrower cameras).
- **The player**: invisible players keep collision and AI reactions; bodies cannot always be
  hidden. Park the player (above or below the spot) with streaming kept at the location; watch
  for side effects where it is parked (under water at Northside docks the camera parent drifted
  8.7 mm, which a recovery now corrects).
- **Things on screen**: the HUD (hide it every frame if the game redraws it), menus (pause on
  focus loss: turn the setting off where it exists, keep the window in front, detect and close
  menus with Esc), mod overlays (trainers, CET, ReShade, OptiScaler, Ultra Plus warnings), pickup
  glows. The picture check (`capture/checks.py`) catches grey pause screens; nothing catches a
  small overlay, so turn them off at install.
- **Population**: people stream in for tens of seconds after a teleport (populate before a take);
  some games spawn and despawn in a held world; clearing people from cameras must never delete
  what a game script owns (the obstacle policy retakes instead).
- **Settings**: games rewrite settings on first start or reject live changes; write them with the
  game closed and verify by reading them back when a session opens (refuse to capture otherwise).
- **Script-layer quirks**: RedLua passes numbers through a float (hashes above 2^24 need
  `hash_arg`), faults when collecting finished jobs; CET has no coroutines and no files outside its
  mod folder; raw memory reads from Lua crashed GTA V.
- **Anti-tamper and crashes**: GTA V Enhanced crashes itself on purpose now and then; ray tracing
  has hung the GPU. The worker treats a stale heartbeat as a closed game and restarts it.
- **One game at a time**: Steam runs one game; another session may be using it (section 8).
- **Window size**: the outer window is not the client area (GTA V: 2554x1400 for 2560x1440); set
  the client size and check the frame size; non-16:9 letterboxes.
- **Frame rate** sets the shot time (settle frames / fps); VSync and caps off. `verify` wants 55
  frames/s unless the adapter sets `min_fps` (Cyberpunk: 15, path tracing).
- **Versions**: script extenders support exactly one game version; pin everything and record the
  exe's version; a game update means new builds.

## 8. Working rules for agents here

- Ask the person you work for before downloading any third-party file (name, source, size), before
  anything that raises an administrator prompt (`install --only machine`), and before committing
  or pushing. Commit messages are brief conventional subjects (`feat: ...`, `fix: ...`).
- Story mode and offline only; never start online modes or touch anti-cheat beyond what the
  install documents.
- Several agent sessions may share one PC. Before starting a game, check Steam's
  `HKCU\Software\Valve\Steam\RunningAppID` and the game processes (a game started from its exe,
  like Cyberpunk, does not show in Steam); never close another session's game. Ask for the slot
  ("REQUEST: need the game for about N min for X"), wait for "YIELD", and hand it back when done.
- Do not touch other games' folders, exchange folders, or `ProgramData\ReShade`.
- Keep game-specific code in `adapters/<game>/`; when you add a shared hook, keep the default
  behaviour of every other game unchanged and say so in the commit.
- Measure, then write down: every claim in README and docstrings carries the number, the place
  and the date. Say plainly what was not measured.
- Before handing work back, run the no-game tests (`tests/*.py`), the Lua compile check
  (`adapters\rdr2\scripts\check_lua.ps1` covers every adapter's Lua), and the game's `verify`.

## 9. Where each game stands

| | RDR2 | GTA V Enhanced (`gtave`) | Cyberpunk 2077 |
|---|---|---|---|
| script layer | Script Hook RDR2 + RedLua | Script Hook V + RedLua (Ultimate ASI Loader as `xinput1_4.dll`) | Cyber Engine Tweaks + RED4ext, redscript, Codeware |
| loader | `adapters/common/lua/capture_loader.lua` | same | `adapters/cyberpunk/lua/capture_mod/init.lua` |
| freeze | photo-mode freeze (exact) | minimum time step written to 1e-7 s (`timestep.py`) | time dilation 1e-7 + clock plug-in at 1/5,000 |
| camera | render camera in memory (`render_camera.py`) | script camera | first-person camera component, player parked 12 m under |
| exposure | photo-mode lock | does not re-adapt | forced average luminance, bisected to the first shot |
| settle | 40 ticks | 40 frames | 120 frames, 4 frames averaged |
| visuals | ReShade preset, Reality Redemption 2 ray tracing, DLSS 5 | NaturalVision Enhanced, game ray tracing, DLSS 5 (skin 2) | path tracing, DLAA + ray reconstruction; Ultra Plus / Nova LUT optional; DLSS 5 untried |
| scout overlay | yes (F8-F11) | no | no (fast-travel scouting helper) |
| full take | yes (2026-11-20, before the per-shot checks; spoiled from clip frame 53) | Legacy yes (48 min, QC passed); Enhanced: a 32-camera sample | near sweeps only |

GTA V Legacy (`gtav`) still installs and runs but is dropped. Details and open items per game are
in README and BACKLOG.
