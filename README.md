# capture_mod

Captures a camera rig (`camrig/v1` cameras around a subject) inside a running game: the world
is held at exactly one instant across every view, stepped by exactly 1/fps between instants,
and the result is packaged in the camera-rig repository's delivery layout. Rig formats are
pluggable providers (`rigs/`). Games: Red Dead Redemption 2, GTA V (Legacy and Enhanced) and
Cyberpunk 2077, all in story mode.

```
capture/            game-agnostic: rig sources, the scene, placement, shot lists, the take loop,
                    per-shot checks, packaging, sheets, locations, the job queue, the worker, the CLI
capture/install/    game-agnostic installer: steps, where mod files come from, and the components
                    every game shares (ReShade, our capture add-on, optional OptiScaler)
addons/capture/     our ReShade add-on that saves frames (game-agnostic)
rigs/               rig providers, one file per rig format (rigs/README.md has the contract)
third_party/        the camera-rig repository as an optional git submodule (for the camrigs provider)
adapters/common/    what adapters share, tied to no game: the game window (focus, keys, grabs, size),
                    process memory, and RedLua (the job loader script and the session client)
adapters/rdr2/      everything RDR2: the adapter, its install plan and mod lockfile, visual set, ray
                    tracing, Lua jobs, launch and recovery scripts, the render camera writer, probes
adapters/gtav/      everything GTA V, both editions: the adapter, the install plans (install.py,
                    install_enhanced.py) and lockfile, the unattended launcher, the freeze
                    (timestep.py), the session job, probes
adapters/cyberpunk/ everything Cyberpunk 2077: the adapter, the loader mod for Cyber Engine Tweaks, the
                    session job, install plan and lockfile, game settings, launcher, probes
docs/MOD_FILES.md   the third-party files an install needs and where to get them (generated)
tools/              comparison tools (DLSS 5, ray tracing, sheets with FLIP maps), frame reports,
                    documentation media
tests/              checks that need no game (installer, obstacle policy, rig providers)
out/                all outputs, mod files and this machine's config (gitignored; CAPTURE_OUT moves it)
BACKLOG.md          designed-for but not built
```

## Install

On a fresh PC: install the game and start it once, clone this repository
(`git clone --recurse-submodules`), install [uv](https://docs.astral.sh/uv/), then:

```powershell
.\capture.ps1 mods status rdr2          # which third-party files are found, which are missing
.\capture.ps1 mods fetch rdr2           # downloads the ones that may be downloaded, checks their hashes
#   ...put the ones you must supply yourself into out\mods\ (docs/MOD_FILES.md says where to get them)
.\capture.ps1 install rdr2 --dry-run    # every step and what it would change
.\capture.ps1 install rdr2 --dlss-nr <nvngx_dlssnr.dll>   # game closed; the full capture setup (below)
.\capture.ps1 verify rdr2 --launch      # starts the game, checks scripts, a test frame, a small take
```

After that the machine can scout, run a worker, or be driven by an agent (see Workflow). The same
commands take `gtav` for GTA V Legacy and `gtave` for GTA V Enhanced (see GTA V adapter).

The RDR2 default (since 2026-11-20) is the full capture setup: Direct3D 12, a 2560x1440 window,
the visual set's ReShade preset, ray tracing (Reality Redemption 2) and DLSS 5 (OptiScaler, which
needs your `nvngx_dlssnr.dll`). `--no-ray-tracing`, `--no-optiscaler`, `--no-preset`,
`--api vulkan` (with `--no-ray-tracing`) and `--resolution WxH` change it; an install without one
of them stops it from loading (its loader file goes, backed up).

- **What it does.** Game-agnostic components install ReShade for the game's graphics API, build
  and deploy our capture add-on, and optionally OptiScaler; the game's adapter adds the game's own
  mods, our scripts and a few game settings. For RDR2: Script Hook RDR2 and its ASI loader, RedLua
  (autorun on, natives patched), Native Trainer (`--no-native-trainer` to leave out), our Lua
  scripts, the game's visual set, VSync off.
- **Visual set** (`adapters/<game>/visual/`). The add-on saves frames after ReShade's effects, so
  the preset is part of what a capture looks like. RDR2's is `visual/ReShadePreset.ini` (CAS,
  chromatic aberration, colour matrix, deband, fake HDR, vibrance), installed as the game's
  `ReShadePreset.ini` together with the eight shader files it uses, pinned in the lockfile and
  downloaded from their repositories by `mods fetch`. `--no-preset` captures without effects
  instead. A preset you change in game is backed up before an install replaces it; to make the
  change the default, copy it over `adapters/rdr2/visual/ReShadePreset.ini`.
- **Direct3D 12** (`--api d3d12`): ReShade goes into the game folder as `ReShade.asi` and loads
  itself through Script Hook's loader, with or without OptiScaler (OptiScaler preloads Windows'
  own `dxgi.dll`, so a `dxgi.dll` ReShade never loads next to it). Two copies of ReShade in the
  game crash it (out of memory), so RDR2 comes off ReShade's machine-wide Vulkan app list, and the
  Vulkan layer itself is unregistered once no Vulkan app uses it (`--only machine`, an
  administrator prompt each); its copy loads into the game even when the game is not listed.
  Until then, start Steam with `DISABLE_VK_LAYER_reshade_1=1` set, so games it starts keep that
  copy out. The game rewrites its settings on its first Direct3D 12 start (window size, DLSS
  mode, VSync); run install again after it.
  Captures target 2560x1440 (`--resolution 2560x1440`, the portrait crops are then native).
- **Ray tracing** (`--ray-tracing`, Direct3D 12 only): Reality Redemption 2 Beta 2, pinned in the
  RDR2 lockfile (the RAR is read as downloaded). Its effect is added to the visual set's preset,
  and three presets switch live: F14 with ray tracing, F15 ray tracing off, F16 the mod off.
  `tools/preset_ab.py --location ID --clock HH:MM` captures all three at one frozen instant
  (player, street, building fronts, ground, overview, people) and sheets them.
- **Comparison sheets** (`tools/compare_sheets.py [folder]`, also run at the end of every
  comparison tool): pages of four views with a title band, column titles and per-view numbers,
  a centre-crop version of each page, and NVIDIA's FLIP error map (the `flip-evaluator` package,
  LDR, 67 pixels per degree) next to each pair: where and how much two pictures differ as a
  viewer would see it. Mean FLIP, 2026-11-20: ray tracing off to on 0.074 and 0.079 on the sunny
  street, 0.047 at the lakeshore, 0.040 at night; DLSS 5 off to on 0.038 to 0.044.
- **OptiScaler** (`--optiscaler`, the DLSS 5 fork). The game must have DLSS turned on; OptiScaler
  takes over that call and runs NVIDIA's DLSS 5 model on the result. Installed with frame
  generation off and the model running every frame (its edit cache off, so nothing is carried
  from one camera to the next); its menu is on End (ReShade's is Home by default), and in RDR2 its F6
  comparison key is unbound (F6 is the game's camera mode). F13 switches DLSS 5 on and off live.
  `nvngx_dlssnr.dll` is yours to supply (`--dlss-nr <file>` or out/mods). Installing again
  with `--no-optiscaler` stops it from loading (its loader file goes, backed up); F13 switches
  it off live.
  `tools/upscaler_ab.py [--location <id>] [--npcs N]` compares DLSS 5 off and on at the same
  frozen instant (views of the player, the street and close-ups of nearby people, as off/on
  sheets) and measures how long the picture takes to settle after a cut. Measured in RDR2 on
  Vulkan, 2026-11-20 (Rhodes, Saint Denis): DLSS 5 engages after the game's own DLSS
  (1066x600 to 1600x900); it adds contrast and local detail, most on faces; the mean change is
  1.1-2.9 levels of 255, against 1.1 between two captures of the same pose; settling after a cut
  and repeatability are the same with and without it (40 frames is enough).
  `tools/upscaler_sweep.py` repeats that for several OptiScaler settings, one game start each
  (OptiScaler reads TransferStrength and Style only at start on Vulkan), at the same location,
  clock and weather, with traffic cleared around the player; it puts OptiScaler.ini back at the
  end. Measured 2026-11-20 in Saint Denis (8 views per setting): TransferStrength 1.0, 1.5,
  2.5, 4.0 gave a mean change of 1.5, 1.9, 1.5, 1.7 levels of 255; on the player's face it grew
  from 1.4 to 2.8 (the strongest 1% of pixels from 10 to 30). The Natural and Cinematic styles
  change about as much as Default (1.4, 1.6). Thin things the scene probes miss (fences,
  leaves) can still stand in front of a close-up.
- **Mod files** are never in git. Lockfiles pin each one by SHA-256
  (`capture/install/mods.lock.json` for every game, `adapters/<game>/mods.lock.json` per game);
  the installer finds them by hash in `out/mods/` or `--mods <folder, archive or bundle>`, inside
  archives as downloaded. `capture mods bundle rdr2 --with-supplied` zips everything one machine
  has for your other machines (keep it out of git and off the internet).
- **Safe to repeat.** Steps already satisfied are skipped; `--dry-run` changes nothing; a missing
  file stops the install before anything is changed. Everything written is recorded in
  `out/install/<game>/installed.json` with backups, and `capture uninstall <game>` puts it back
  (files or settings you changed since are left alone; ReShade's machine-wide Vulkan layer stays).
- **Administrator prompts** only for ReShade's machine-wide Vulkan layer: registering it for a
  Vulkan install (`--api vulkan`), or unregistering it once no Vulkan app uses it
  (`--only machine`; until then a Direct3D game gets a second ReShade from it).
- **Iterating.** `capture install rdr2 --only scripts` copies changed Lua scripts (the game can
  be running; then `adapters\rdr2\scripts\reload_scripts.ps1`); `--only addon` rebuilds and
  deploys the add-on (game closed).
- `--game-dir` is only needed when the game is not found through Steam; the folder is remembered
  in `out/config.json`.
- `tests/test_install.py --mods <folder>` runs the whole RDR2 plan in a sandbox.

## Workflow

Scout locations, submit a rig for them, let workers capture. Scout and worker can run on
the same machine one after the other (the worker teleports to each location).

```powershell
# 1. scout: record where the player stands (or --at=x,y,z to go there first), with four
#    previews looking outward (front, right, back, left of the facing) at eye height
.\capture.ps1 scout --name lakeshore --tags open,shore
.\capture.ps1 locations                 # --titles fills in place names, --publish refreshes the overlay

# 2. submit: one job per location for a rig (any provider; see Rig providers below)
.\capture.ps1 submit --solver yiming_stdm --location rdr2-lakeshore-001   # solved per location
.\capture.ps1 submit --rig <rig_yiming_stdm.json> --location rdr2-lakeshore-001  # a fixed pose file
.\capture.ps1 submit --rig <rig.json> --all --last-frame 3 --sweep-stride 30   # a quick sample
.\capture.ps1 submit --rig <rig.json> --location <id> --cameras "?_near_sweep_t000"   # only some cameras
.\capture.ps1 submit --rig <rig.json> --location <id> --park-height 0   # hidden player stays at the spot (default 10 m up)
.\capture.ps1 queue

# 3. worker: claim jobs until none are left (--once: one job)
.\capture.ps1 worker
```

The scout records a readable place title from the game's map zones (e.g. "Saint Denis · Bayou
Nwa"), warns when a saved location is within 25 m and refuses within 5 m (`--force` to save
anyway).

**In-game overlay (RDR2)** while scouting by hand: your position and place name, and the nearest
saved location with its title, position and distance (red within 25 m). F11 hide, F8 next saved
location, F9 view it (front, right, back, left, off), F10 teleport there. F4 and F5 are left to
Native Trainer, F6 to the game's camera mode, F7 to RedLua. It hides itself while a take runs.

`capture.ps1` runs `python -m capture` through uv with this project's Python.

Tested 2026-11-20 on one machine: two locations scouted (one where the player stood, one
reached with `--at`), then a worker took a 3-frame sample job, teleported back to the first
location and captured it: 480 shots in 2.2 min, none recaptured, 275 cameras packaged, read
by the rig repository's `qc/stdm_view.py` (275 cameras, 18 groups, Diverse).

### Rig providers

Every rig format is a provider: one Python file that turns the scene around a location into a
`camrig/v1` rig (or declines the location), with an optional check of the captured package.
`rigs/README.md` has the contract. Providers are found in `rigs/` (add one by pull request), in
the folders on `CAPTURE_RIG_PATH`, or by passing a file path.

```powershell
.\capture.ps1 providers                                               # what this machine can use
.\capture.ps1 solve --location rdr2-rhodes-001 --solver yiming_stdm   # the rig there + a plan image, no take
.\capture.ps1 submit --location <id> --provider ring --set count=12 --set radius_m=5
.\capture.ps1 submit --location <id> --provider C:\my\rigs\dolly.py --set speed=0.5
```

| provider | what | scene |
|---|---|---|
| `file` (`--rig <file>`) | a `camrig/v1` pose file used as it is | not used |
| `camrigs` (`--solver <key>`) | the camera-rig repository's rigs, solved with its own rules (lift or shrink a ring, drop a blocked group, decline the location; its `docs/SCENE_FIT.md`) | used |
| `ring` | example: a ring of static cameras shrunk to clear the scene | used |

- **Scene** (`capture/scene.py`, adapters with `raycast`): 66,000 rays from 11 points around the
  location (the ground point at 0.5, 1.6 and 3 m, rings of 4 at 3 m and 7 m), 14 m long, against
  terrain, buildings, objects, glass and foliage; each hit becomes a 0.3 m patch facing its normal.
  Handed to every provider in the rig frame. Cached per location in `out/locations/scenes/`
  (.npz, and .obj to look at). About 30 s.
- **Jobs** record the provider's key, version and settings; a worker refuses a job whose provider
  version differs from its own. A provider file from outside the repository is copied into the
  queue at submit, so every worker runs the same file. The rig a provider returns is written to
  `out/solved/<rig id>/<location>.json` and reused.
- **QC**: a provider's `qc()` runs after packaging; the result goes into the job result and
  `take.json`. `--qc flag` (default) records a failed check, `--qc fail` fails the job.
- **camrigs** needs a checkout of `gamecapture-camera-rigs-huixin`. It is an optional git
  submodule at `third_party/gamecapture-camera-rigs-huixin`, pinned to the commit this
  repository was tested with: clone with `git clone --recurse-submodules`, or run
  `git submodule update --init` after a plain clone (needs read access to that repository).
  `CAMRIGS_REPO` overrides it (for working on the rig repository itself); `~/repos/...` is the
  last fallback. Without any of them the other providers still work. Its version is that
  checkout's commit; updating the rig rules is a submodule bump committed here. No-performer
  captures need no SMPL-X model: the ST-DM and Diverse rules read only the performer's bounding
  box and pelvis, so the subject is a static stand-in box of the demo performer's size; on an
  open floor this reproduces the demo rig (poses within 1e-5 relative to the subject). The
  Diverse trajectory (`zehao_traj`) is folded in as the demo file does. Its `qc()` runs that
  repository's `qc/stdm_view.py` (skipped for takes without the temporal ring). The repository's
  other rigs (hemisphere, chaowei_v2) test the performer's silhouette and are not checked with
  the stand-in.
- Measured at the Rhodes location: 28,492 of 66,000 rays hit; camrigs' far ring went from 4.57 m
  (open floor) to 4.37 m to clear a porch, 8 s to solve. A wall 5 m away in a test scene shrinks
  it to 3.47 m; a 7 x 7 x 3 m room drops it and caps the higher groups.

A changed rig (for example ten cameras raised by 0.5 m) is a new rig file, so a new rig id
and a new job; it is captured again in full. Reusing the unchanged shots needs a restorable
world state (BACKLOG.md).

### Outputs (`out/`)

```
out/locations/locations.json            capture_locations/v1
out/locations/previews/<location>/      front/right/back/left.jpg, sheet.jpg
out/queue/{pending,claimed,done,failed}/<job>.json, out/queue/rigs/<rig id>.json
out/takes/<location>/<rig id>/<time>_<job>/
    take.json          job, location, rig, placement, settings, world state id, render settings, timing
    shots.json         the shot list as captured (world coordinates)
    capture_log.jsonl  per shot: file, health, picture stats, rendered camera, game timer, attempts
    steps.jsonl        per time step: seconds advanced, ticks, game timer
    raw/               one full frame per shot
    package/           delivery layout: <label>/rgb.mp4, <label>/NNNN.camera.json, render_metadata.json
    sheets/            ring, far ring, portrait, sweep, time, Diverse
```

A rig id is the rig's key plus a hash of the file. A job id is the location, the rig id and
a hash of the settings, so submitting the same job twice queues it once.

### The queue on several machines

The queue is a folder. Put `out/` (or `--queue`, `--takes`) on a shared drive and run one
worker per machine; a worker claims a job by renaming it into `claimed/` and keeps a lease
file fresh. A claim whose lease is 15 minutes old is requeued (`capture queue requeue`, and
every worker on start). If the game goes away mid-take (a script fault closes it, a graphics
error stops it), the worker restarts it and takes again, up to twice per job. Failed jobs stay
in `failed/` with the error until `capture queue retry <job>`.

### Per-shot checks

Every shot is checked before it is accepted:

- **Game state** (adapter): the game window has focus, no pause menu, the hidden player is
  still hidden, the world is still frozen.
- **Picture**: colour saturation and brightness against the frames accepted just before. On
  the full take of 2026-11-20 this flags 121 of the 130 grey pause-screen frames of clip
  frame 54 (saturation 5-7 against 45-62), at 7 ms per frame.

A failed shot gets a recovery attempt (refocus the window, wait for the pause menu to close,
hide the player again, settle) and is captured again, up to 3 times. The take fails if the
frozen instant moved (the game timer changed), since a frozen world cannot be resumed.

### People, animals and vehicles in the cameras

For adapters with the `obstacles` capability (`capture/obstacles.py`), every person, animal
and vehicle near the rig is an oriented box; a camera position inside the box, or within
`--obstacle-margin` of it (0.15 m), is a hit.

- **Start of a take**, frozen at its first clip frame: anything holding any camera position of
  this take is deleted, with its rider, mount, vehicle occupants or draft horses. Nothing a game
  script owns is ever deleted; if such a thing holds a camera, the take is retaken.
- **No deletions after that.** Before each clip frame's shots, the frame's cameras are checked
  again. A hit before `--retake-before` (2/3) of the shots stops the take and the worker starts
  it again (up to `--max-retakes`, 3; the aborted attempt keeps its logs in `<take>_retakeN`, its
  frames are deleted). A later hit lets the take finish; the shots are marked `camera_inside` in
  the capture log and listed under `obstructions` in `take.json`.
- `--no-obstacle-check` turns both off. `tests/test_obstacle_policy.py` checks the policy
  against a fake game.
- Fixed 2026-11-21: both session jobs listed people and vehicles in one shared pool, so with
  vehicles near the rig the people's entries pointed at vehicles by the time they were deleted,
  and a person in a camera survived the clearing (the take was then retaken). Found in GTA V
  (19 of 21 people removed after the fix, against 7 of 34 before); RDR2's job has the same fix,
  not yet run in the game.

## Adding a game

- **Adapter**: implement `capture.adapter.Adapter` in `adapters/<game>/` and register it in
  `capture/adapters_registry.py`. It supplies the world conventions (how the rig frame maps into
  the world for a facing, the heading basis) and the operations: go to a location, ground point,
  clock, hide the subject, a preview view, freeze, write a camera, capture, advance by exact
  seconds, health, recover. Optional capabilities: `obstacles`, `raycast`, `snapshot`.
  `capture verify <game>` is the acceptance test (a frozen 8-camera take with exact time steps).
- **Shared pieces** (`adapters/common/`): for a game with a Script Hook and RedLua build, the
  job loader (`lua/capture_loader.lua`, installed with the game's own exchange folder written in)
  and the session client (`redlua.py`: one long Lua job driven a command at a time); the game
  window (find by class, focus, keys, client size, grab); process memory. The game writes its own
  session job (`adapters/<game>/lua/jobs/cam_session.lua`) with its natives.
- **Install plan**: `adapters/<game>/install.py` (registered in `capture/install/__init__.py`)
  with the game's lockfile `mods.lock.json`. It names the game's exe, finds its folder, calls the
  shared components with the game's choices (graphics API for ReShade, how OptiScaler is loaded)
  and adds the steps only this game needs. `adapters/<game>/visual/` holds the game's visual set
  (the ReShade preset for captures).

## RDR2 adapter

### Setup

`capture install rdr2` (see Install). The game-side scripts and the add-on exchange files in
`%USERPROFILE%\Documents\RDR2Modding\captures` (the default in the shared
`adapters/common/lua/capture_loader.lua`, and `ReShade.ini`). Frames only pass through it; the
worker moves them into `out/`.

### Running without anyone at the keyboard

`capture_loader.lua` (RedLua, Autorun on) polls the exchange folder and runs Lua jobs from
`adapters/rdr2/lua/jobs/`; the adapter drives one long job, `cam_session.lua`, a command at a
time. The worker restarts the game itself when the loader's heartbeat is missing.

```powershell
.\adapters\rdr2\scripts\run_job.ps1 smoke          # run one Lua job and print its result
.\adapters\rdr2\scripts\check_lua.ps1              # compile-check every Lua file (no game needed)
.\adapters\rdr2\scripts\reload_scripts.ps1         # Script Hook's CTRL+R: reload scripts (~10 s)
.\adapters\rdr2\scripts\restart_game.ps1           # relaunch through Steam until the loader is up (~90 s)
```

Keys are only sent while the game is the foreground window. The game must stay in the
foreground during a take (a lost focus is detected and recovered, see Per-shot checks).

### How a take is captured in RDR2 (measured 2026-11-19/20)

- **Freeze.** `SET_TIME_SCALE(0)` is not a freeze: the simulation still advances about
  0.33 ms per tick. The photo-mode freeze (`ANIMSCENE::_REQUEST_PHOTO_MODE_FREEZE`) holds the
  world exactly (zero bone movement over 240 ticks) while scripts run and frames render, but
  it ignores every script camera call.
- **Camera writes.** While frozen, each pose is written straight into the engine's render
  camera frame in memory (`render_camera.py`): right at -0x30, forward at -0x20, up at -0x10,
  position at 0 (rows of 4 floats), vertical FoV at +0x30. The address changes per launch: a
  scan for the current camera position (about 7 GB in 11-15 s, ~520 hits), a match on FoV and
  rotation (~14 copies), then a 2 m nudge under the freeze picks the copy the render follows.
- **Geometry.** Written poses render the same picture as the engine's own camera at that pose;
  the engine projects within 1 pixel of the rig's pinhole model (vertical FoV, centred
  principal point). At 16:9 the frozen frame has no letterbox (16:10 is letterboxed).
- **Exposure.** Locked on the take's first shot (`_SET_PHOTO_MODE_EXPOSURE_LOCKED`); without it
  auto-exposure carries over between views (4% darker in one test).
- **Settle.** 40 ticks after each write: mean difference to the engine's render 3.7 at 10 ticks,
  2.5 at 20, 1.7 at 40, 1.5 at 80; frame-to-frame noise 1.6.
- **Time steps.** Released at time scale 0.1 (about 72 ticks per 1/30 s), frame times summed,
  frozen again at the nearest tick (the freeze lands one tick late). Full take: game timer
  1,898 ms over 57 steps for 1,900 ms scheduled, within 2 ms at every clip frame, and
  unchanged across the shots of a clip frame.
- **Teleport** (`teleport` session command): the player is moved with its position frozen,
  collision and the scene are loaded around it, then it is put on the ground and kept frozen
  until the session ends (no landing stumble). About 8 s for 8 km.
- **Taking the player out of the scene.** Cameras are placed in world coordinates at the
  location, independent of the player. The player only has to be near for streaming, and must
  not affect the scene: an invisible player still has collision (traffic piled up on the spot
  in Saint Denis) and NPCs still respond to its wanted status. Hiding the subject therefore also
  turns on the `ghost` natives: everyone ignores the player, law off, wanted score cleared,
  silent, invincible, no collision; all undone when the session ends. During a take the player
  is also parked 10 m above the spot (`submit --park-height`, 0 to stay at the spot), with
  streaming focus kept at the location; each shot's log line records where the player was.
  At 200 m no render detail is lost (`probes/ghost_probe.py`), and in Rhodes neither 10, 30
  nor 200 m changed how many people were near the spot (`probes/npc_probe.py`, counts within
  15/30/60 m; two runs at the spot differed more than any parked run). An area already in a
  fight stays in it.
- **Obstacle boxes.** `GET_MODEL_DIMENSIONS` returns zeros here; `_GET_ENTITY_WORLD_POSITION_OF_DIMENSIONS`
  gives the entity's world-axis-aligned box, and the oriented box is recovered from it and the
  entity's heading (falls back to the axis-aligned box near 45 degrees, where it cannot be
  separated). Deleting works while the world is frozen (checked 2026-11-20: a passer-by is gone
  from the next frame, the frozen instant unchanged).
- **Ped heights.** A ped set to height z reads back at z + 1 (its origin is about 1 m above
  its feet), and the ground probe hits the player's own collision; the teleport probes with
  collision off and sets the ground height itself, so a held player stands on the ground.
- **Frame rate.** A shot waits 40 ticks to settle, so the frame rate sets the shot time: 0.75 s
  at 60 fps, 0.3 s at 134 fps, 0.20 s at about 210 fps. All three were seen on 2026-11-20 with
  VSync on in the game's settings, so the cap is not VSync alone (not tracked down). The
  installer turns VSync off; `capture verify` reports the frame rate.
- **Speed.** 0.20 s per shot at 1600x900; the full ST-DM rig (12,356 shots, 24,387 camera
  frames) takes 41 min and 50 GB of BMP; 1.3 GB packaged.

RedLua quirks: `PLAYER_ID()` comes back typed as a Cam, which Player natives reject; a Player
made with `native.new('Player', 1)[0]` (index 0) works and is our player (`lua/jobs/type_probe.lua`).
Parameters typed `Any` only accept `native.new('Any', 1)`; out-pointers are
`native.new('float', 1)` read with `[0]`; RedLua's `natives.json` names some natives only by
hash (`patch_natives.ps1`).

### Research probes

`adapters/rdr2/probes/` holds the tools the method was found with (memory scans, the frozen
orbit, geometry and step checks). They are not part of the pipeline.

## GTA V adapter (Legacy and Enhanced)

GTA V Legacy (`gtav`: Steam app 271590, Direct3D 11, game build 1.0.3889.0) and GTA V Enhanced
(`gtave`: Steam app 3240220, Direct3D 12 with ray tracing, build 1.0.1158.13), story mode only.
Both run the same adapter, session script and freeze; what differs is under "GTA V Enhanced" below.

### Setup

```powershell
.\capture.ps1 install gtav --mods "C:\...\Grand Theft Auto V Enhanced"   # or put Script Hook V in out\mods
.\capture.ps1 verify gtav --launch
.\capture.ps1 scout --game gtav --name legion-plaza --at "190,-955,30.5"
.\capture.ps1 worker --game gtav
```

- **Mods**: Script Hook V with its ASI loader and Native Trainer (supplied: the readme forbids
  redistribution; build 3889.0.1158.13 runs both Legacy 1.0.3889.0 and Enhanced, so an Enhanced
  folder that has it is a source), RedLua for GTA V (downloaded), our loader written with GTA V's
  own exchange folder (`Documents\RDR2Modding\captures_gtav`), ReShade 6.8 as `ReShade.asi` with an
  empty preset (no visual set yet), the capture add-on. `ScriptHookV.dev` turns on CTRL+R reload.
- **BattlEye off**: `-nobattleye` in the game's `commandline.txt` (GTA5.exe starts, not
  GTA5_BE.exe), so the game cannot go online with mods.
- **Settings**: Direct3D 11, VSync off, no pause on focus loss, windowed 2560x1440. The game sizes
  the outer window from its settings (client 2554x1400), so the adapter resizes the window until
  the client area, and so every frame, is 2560x1440.
- **Unattended start** (`adapters/gtav/launch.py`, used by the worker when the loader is gone):
  closes the game and its launcher, starts it through Steam, answers Steam's launch-option
  dialog with "Play Grand Theft Auto V Legacy", clicks STORY MODE on Rockstar's landing page (the
  rightmost item of its bottom bar, found in a grab of the window), and waits for the loader:
  about 75 s. Clicks only go to Steam's dialog and to the game while the loader is not running.

### GTA V Enhanced (`gtave`)

```powershell
.\capture.ps1 install gtave --mods "C:\...\Grand Theft Auto V Enhanced"   # Script Hook V is already there
.\capture.ps1 install gtave --optiscaler --dlss-nr "C:\...\nvngx_dlssnr.dll"   # DLSS 5 (optional)
.\capture.ps1 verify gtave --launch
.\capture.ps1 scout --game gtave --name vinewood-walk --at "300,177,103.13" --facing 180
.\capture.ps1 worker --game gtave
```

Verified 2026-11-21: every check passes (frames through the add-on at 2560x1440, colours, a
frozen take with every step exactly 1/30 s, packaging) but the machine-wide administrator step;
a 32-camera moving sample at Vinewood (960 shots, 30 steps) passed QC. What differs from Legacy:

- **The ASI loader.** GTA5_Enhanced.exe does not import dinput8.dll (it loads it only late, for
  DirectInput), so Script Hook V's own loader never loads Script Hook V or any plug-in at start:
  the reason modding Enhanced seemed not to work. Ultimate ASI Loader 10.0.4 (MIT, downloaded and
  pinned) goes in as `xinput1_4.dll`, which Enhanced does import; Script Hook V then logs
  `Success, game version is VER_EN_1_0_1158_13`. Script Hook V's own `dinput8.dll`, if there from
  a manual install, is removed (backed up): Enhanced still loads it late and it loads every plug-in
  a second time.
- **The game locks its own folder.** While Enhanced runs it holds every file in its folder open
  read-only and denies writes (BattlEye's licence texts too). ReShade therefore could never save
  and printed "Unable to save configuration" over every frame. The game folder's `ReShade.ini`
  now only holds `[INSTALL] BasePath=<exchange>\reshade`. ReShade keeps its config, preset and
  log there, and finds the add-on in the game folder through `[ADDON] AddonPath`. The same lock
  means our loader script and RedLua's settings cannot change while the game runs, and Script
  Hook V's log stops after its first lines.
- **Launcher.** The window is class `sgaWindow`; the landing page has tabs (ONLINE, GTA+, STORY)
  instead of a bottom bar: E moves one tab right, Enter on STORY resumes the story (found from the
  white box behind the selected tab). About 3.5 min to the loader, most of it Rockstar's launcher.
- **Settings** in `Documents\Rockstar Games\GTAV Enhanced\settings.xml`; Direct3D 12 only, no
  `DX_Version`. Ray tracing is the game's own (shadows, reflections, ambient occlusion, indirect
  diffuse). Frame generation is set off (`FrameGenType` 0). The game has DLSS, FSR and SSAA built
  in; without `--optiscaler` its upscaler setting is left as it is.
- **DLSS 5** (`--optiscaler`, measured 2026-11-21): OptiScaler loads as `OptiScaler.asi` through
  the same loader, and the install turns the game's DLSS on (`ResScalingType` 4; 0 off, 1 SSAA,
  2 FSR 1, 3 FSR 3, per PCGamingWiki). Enhanced calls DLSS through NVIDIA Streamline, which
  OptiScaler hooks. The game's mode (`dlssQuality` 2) renders 1707x960; DLSS 5 then runs on every
  2560x1440 frame (2.2 ms). Verify passes with it on. `tools/upscaler_ab.py --game gtave` at
  Vinewood: off to on, mean FLIP 0.16 to 0.21 (RDR2: about 0.055), largest on faces and clothes;
  settle after a cut and the same pose twice are about as with it off (40 frames: 1.58 against
  1.45; twice: 0.87 against 0.66). OptiScaler's ini cannot be saved from its menu while the game
  runs (the folder lock); the install sets it beforehand.
- **Ray tracing switched live** (`settings_menu.py`, adapter capability `ray_tracing_switch`): the
  game applies "Enable Ray Tracing" from its pause menu without a restart, also while frozen, so
  `tools/preset_ab.py --game gtave --with-dlss5` compares neither / ray tracing / DLSS 5 / both at
  one frozen instant, as for RDR2. The adapter presses the keys, checks each step on screen (the
  lit tab and row, the list moving, "Apply Changes" appearing), confirms the result in
  settings.xml, and freezes the world again afterwards. Keys are sometimes dropped, so each one is
  confirmed before the next. Scripts do not run while the pause menu is open. About 25 s per
  switch. Vinewood at 14:00, extra sunny, 13 views: mean FLIP 0.172 for ray tracing, 0.174 for
  DLSS 5 over it, 0.259 for both (RDR2's Saint Denis: 0.055, 0.054, 0.069).
- **Speed.** About 158 frames/s at 2560x1440 with ray tracing at the Alamo Sea, 94 in Vinewood with
  DLSS 5; 0.30 s per shot, 0.53 s with a moving crowd.
- **Freeze**: the same minimum step, found the same way (a different address). Find it before
  freezing: at time scale 0 the value 1/3000 is copied into 321 other places.
- **A deliberate crash.** Three times in about 15 frozen sessions (2026-11-21) the picture froze,
  scripts stopped, and about a minute later the game exited. Rockstar's crash handler wrote a
  dump each time (`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`). All three dumps fault
  at the same instruction, `GTA5_Enhanced.exe+0x13f8980`: `mov qword ptr [0], 0x621`, a crash on
  purpose with code 0x621, in code that is encrypted on disk. That makes it the game's protection,
  not a script fault. What sets it off is not known. It came during or 1-3 min after frozen work
  (the minimum-step writes), but each part of a take repeated alone did not set it off, and a
  9.4-minute frozen take ran clean. The worker treats it like a closed game: a stale heartbeat
  ends the game and starts it again.

### How a take is captured in GTA V (measured 2026-11-21)

- **Freeze.** GTA V has no photo-mode freeze. `SET_GAME_PAUSED` stops rendering (a moved camera
  returns the same frame). `SET_TIME_SCALE(0)` still advances the world by a minimum step of
  1/3000 s per frame (people walked 3.6 m in 240 frames; RDR2 shows the same 0.33 ms). That
  minimum is a single writable float in GTA5.exe's image (`timestep.py` finds it by value on every
  start; `probes/timestep_probe.py` found it). At 1e-7 s the world holds exactly: over 480 frames
  nobody moved (0.000000 m), the same pose 240 frames apart gave identical frames, and a moved
  script camera re-renders (`probes/freeze_probe.py`). A step of exactly 0 crashes the game.
- **Time steps.** At time scale 0 every frame advances exactly the minimum step, so 1/30 s is 67
  frames of 0.4975 ms, independent of the frame rate: the session pauses the game (no frame runs),
  the adapter sets the step, the session runs exactly 67 frames and pauses, the hold step goes
  back, the game resumes. Every step measured 33.333 ms. GTA V's game timer does not count these
  steps; frozen frames are checked by their frame time instead.
- **Camera.** GTA V's own script camera renders while frozen, so poses go through camera natives
  (rotation order 2, roll included, vertical FoV); no memory writes. The engine projects world
  points within 0.02 px of the rig's pinhole model at 2560x1440 (pitch, roll to 60 degrees, FoV
  40-90; `probes/geometry_probe.py`); heading is counter-clockwise from north as in RDR2.
- **HUD.** The HUD, radar, notification feed and help text are hidden on every frame, also while
  a shot settles (the loader's `ctx.each_tick`); without that the minimap was in the frames.
- **Speed.** About 185 frames/s at 2560x1440; 0.31 s per shot with the 40-frame settle.
- **Full take** (2026-11-21, Legion Square, noon, ST-DM rig solved around a cube sculpture): 9,411
  shots for 24,387 camera frames in 48.4 min, none recaptured; 57 time steps, each exactly
  1/30 s; 287 cameras packaged (0.52 GB; 97 GB of raw BMP), the rig repository's QC passed (30
  groups, Diverse). One pose seen across the 58 clip frames changes steadily (mean difference
  0.44 after one step, 1.69 at the end: traffic, foliage) and not at all within a clip frame.
- **Moving things**: people and vehicles as oriented boxes straight from their models'
  dimensions (`GET_MODEL_DIMENSIONS` works in GTA V); raycasts against map, objects and foliage.
- **People and traffic.** After a teleport the game's population takes about 50 s to stream in,
  even at its maximum density setting (Population Density 1.0; multipliers above 1 do nothing).
  The adapter fills it at once, spawns a crowd of its own walkers (12 within 12 m by default:
  people within 15 m went from 2 to 14 on Vinewood Blvd) and lets the world run 45 s
  (`populate_s`, `crowd`, `crowd_radius`). The crowd stays the session's own, so the
  start-of-take clearing may delete one standing in a camera. While frozen the population
  multipliers are 0: with more people than its budget the game despawns and spawns people even in
  a frozen world (7 gone, 9 new within 60 m over 3,000 frozen frames); with them at 0 nothing
  moved, appeared or went. The game's own people alone hold still without that.
- **Steam runs one game at a time**: with RDR2 running, a GTA V start fails and leaves Steam's
  launch waiting until Steam restarts; the launcher refuses to start while another game runs.
- **The display must stay on**: with it asleep, screen grabs return the last picture shown, so
  the launcher could not find the landing page; the launcher and the adapter keep it awake.

### RedLua in GTA V: what to avoid

- **No raw memory from Lua.** RedLua returns a C string as an object whose `tostring` is its
  address; reading it, or any absolute address, through LuaJIT's `ffi` faulted inside lua51.dll
  every time, and Script Hook V then closes the game. Place titles pass the zone code's pointer
  straight back into `GET_HASH_KEY` instead, and `zones.py` names the hash (Legion Square,
  Vinewood Hills, Los Santos International Airport, Sandy Shores, Paleto Bay checked).
- **Faults in RedLua's Lua core.** lua51.dll faulted four times (offsets 0x5C83, 0x5DE2), always
  at or just after the start or end of a session job, once 90 s after the full take's session
  ended with the loader idle; never in the middle of the 48-minute take. The likeliest cause is
  RedLua collecting a finished job's native objects. Script Hook V then closes the game; the worker
  restarts it and takes again if it happens mid-take. (Enhanced's freezes are something else: the
  game's protection crashes it on purpose; see above.) `SET_THIS_SCRIPT_CAN_BE_PAUSED`, first
  suspected, is no longer called (not needed: RedLua's scripts run while the game is paused).
- **Hashes above 2^24** go through a float in RedLua (as in RDR2): pass them as `hash_arg`.

## Cyberpunk 2077 adapter

Cyberpunk 2077 patch 2.5 (`cyberpunk`: Steam app 1091500, Direct3D 12, exe file version 3.0.88.46235).
Verified 2026-11-21 on one machine: `capture verify cyberpunk --launch` passes every check but the
machine-wide administrator step (unattended start in 97 s, 85 frames/s path traced at 2560x1440, a
frozen 8-camera take with every step within 0.002 ms of 1/30 s, packaging), and a scouted location
went through submit and worker (scene from 66,000 rays, a ring rig fitted to it, 24 shots).
Not done yet: a full ST-DM take, the visual mods, DLSS 5 (see "Open" below).

### Setup

```powershell
.\capture.ps1 mods fetch cyberpunk            # Cyber Engine Tweaks, RED4ext, redscript, Codeware (GitHub, pinned)
.\capture.ps1 install cyberpunk --only mods --only scripts --only reshade --only addon --only settings   # game closed
.\capture.ps1 verify cyberpunk --launch
.\capture.ps1 scout --game cyberpunk --name cherry-blossom-market "--at=-701.158,952.269,12.0" "--facing=-140"
.\capture.ps1 submit --game cyberpunk --location cyberpunk-cherry-blossom-market-001 --provider ring --set count=8
.\capture.ps1 worker --game cyberpunk
```

- **Mods** (all MIT, downloaded and pinned file by file in `adapters/cyberpunk/mods.lock.json`):
  Cyber Engine Tweaks 1.38.1 (the game's script API in Lua, and the ASI loader that loads ReShade),
  RED4ext 1.31.1, redscript 0.5.32 and Codeware 1.21.4 (the weather: patch 2.5 took `SetWeather` out
  of the game's own script interface). Each supports exactly this game version; a game update needs
  new builds. `python -m adapters.cyberpunk.pin <mod> <archive>` pins a new archive's files.
- **Our loader is a Cyber Engine Tweaks mod** (`adapters/cyberpunk/lua/capture_mod/init.lua`) with the
  same file protocol as the RedLua loader, so the same client drives it. Two things differ: a mod
  reads and writes only inside its own folder, so the exchange folder is
  `bin\x64\plugins\cyber_engine_tweaks\mods\capture_mod\exchange` in the game folder and job files
  are copied into it; and there are no coroutines, so a session command that takes several frames
  answers later.
- **ReShade** goes into `bin\x64\plugins` as `ReShade.asi` with its config and our add-on beside it
  (the loader only reads that folder, and ReShade keeps its config beside its own file).
- **Saving is locked** by the loader whenever a save is loaded (the game's save-lock manager), so
  nothing a session does reaches the player's save slots; `allow_saves.txt` in the exchange folder
  turns that off.
- **Game settings** are written into the game's `UserSettings.json` by the installer, game closed:
  path tracing, DLSS Ray Reconstruction, DLAA on the second-generation transformer model, no frame
  generation, no film grain, chromatic aberration, depth of field, lens flares, motion blur or
  vignette, a 2560x1440 window. The adapter reads them back when a session opens and refuses to
  capture on other settings. Setting them in the running game crashed it.
- **Unattended start** (`adapters/cyberpunk/launch.py`): the game's exe is started directly, the
  loader comes up in the main menu and loads the last save from a script. Starting through Steam
  instead raised a Windows administrator prompt on every start (Steam's first-time setup), which
  nobody answers and which blanks every screen grab for two minutes. Started directly, Steam does
  not list the game as running: other sessions must look for `Cyberpunk2077.exe`.

### How a take is captured in Cyberpunk 2077 (measured 2026-11-21)

- **Freeze.** The game's time dilation set near zero. Over 480 held frames 113 people moved
  0.000 m and the simulation clock advanced 0 s, while frames render, a moved camera is followed
  and a teleport takes effect (`probes/freeze_probe.py`).
- **Camera.** The player's first-person camera component, placed relative to the player's head;
  the session measures the head's transform and places the camera at world poses. Rendered poses
  are within 0.03 mm of the pose asked for, and every shot is checked against it. The engine
  projects world points within 0.04 px (mean 0.008) of the rig's pinhole model at 3840x2160, for
  yaw, pitch and roll (`probes/geometry_probe.py`); the field of view is vertical. World frame as
  RDR2 and GTA V: Z up, heading counter-clockwise from north.
- **Field of view.** It eases in world time, so it cannot change in a held world (no script call
  does it, and a memory write did not take: `adapters/cyberpunk/fov.py`). A take therefore renders
  at its widest camera's field of view and narrower cameras are cut from the middle of the frame
  and enlarged; a rig of one field of view is captured one to one. `--resolution 3840x2160` at
  install and the adapter setting `render_size` keep mixed rigs sharp, at 2.25 times the pixels.
- **Time steps.** The world runs at a time dilation chosen every frame so that the next frame covers
  a fifth of what is left: steps of 33.3321 and 33.3322 ms for 33.3333 asked, in 36 frames each.
- **Player and HUD.** The player's body cannot be hidden from scripts, so in the held world it is
  moved 12 m under the ground and the camera offset makes up for it; a time step lets it fall a
  little, so it is parked again after each. The UI's "Empty" game context removes the whole HUD.
- **Settle.** 120 frames per shot: after a cut the path-traced picture keeps changing for about
  that long (captures 40 frames apart differ by 3.7, 1.9, 1.5, 1.2 levels of 255, then 1.0 to 1.3
  for good; `probes/converge_probe.py`). 1.5 s per shot at 85 frames/s in the Badlands, more in the city.
- **Scene and moving things.** Ray probes against built things and open land (collision groups
  `Static` and `Terrain`); characters and vehicles as oriented boxes of stock sizes; quest
  characters are never removed.

### Open

- **Things that keep animating in a held world** (seen by Nathan in the first take, and in the
  probes): blinking lights such as the fast-travel terminal's, ceiling lights, advertising screens
  and holograms run on real time, so they differ between the shots of one instant. Not solved.
  Tried at the Cherry Blossom Market, the same pose captured six times 30 frames apart, mean
  difference between neighbours in levels of 255 on frames reduced to 1280x720
  (`probes/noise_probe.py`): the hold alone 1.07, with 2.9% of pixels varying strongly (the two
  hanging screens, the hologram tree, the terminal's beam); with the time system's paused state on
  top 1.07 and 2.9% (no effect); with the game's system pause on top 1.34 after its first second,
  in which the whole picture brightens by 18% (worse). The game's own photo mode holds the world
  the same way (time dilation 1e-6) and the terminal's hologram still flickers in it
  (`probes/photomode_probe.py`), so the game seems to have no switch for this.
  Partly solved by switching devices off: while the subject is hidden, every device within 60 m
  that is on (screens, terminals, vending machines, traffic lights; adapter setting
  `devices_off_m`, 0 to leave them on) is disabled through its state's `ForceDisableDevice` and
  enabled again afterwards (44 devices at the market). That takes out the fast-travel terminal's
  hologram and blinking bars and the device screens, which go dark; strongly varying pixels fell
  from 2.9% to 2.2%. What is left are screens and holograms that are part of the map, not devices
  (the market's two hanging screens, its hologram tree). Untried for those: Codeware's video
  component fields, freezing the clock the shaders read.
- People still appear in a held world (2 of 113 over 480 frames); `Traffic/StopSpawn` and the
  crowd options are untried.
- The first scouted location had 0 characters or vehicles within reach of the rig, so clearing a
  camera of a person has not been exercised in the game.
- The visual set (install option `preset`, off by default): Ultra Plus 10.1.0 for 2.5 at its top
  quality (mode PT21, quality and SHaRC "Insane", nothing drawn on screen), Nova LUT 4 and Remove
  Mods Menu, supplied by hand from Nexus Mods. With it the game starts unattended and
  `capture verify` passes as without (57 frames/s at the market); the picture is flatter, less
  saturated and darker (Nova LUT's AgX grading; `out\preview\visual_set_off_on_pose0.jpg`).
  Whether that is the look wanted is Nathan's call; noise and settle time with it are not measured.
  There is no `--preset` flag on this branch: `capture.install.install("cyberpunk", options={"preset": True})`.
- DLSS 5 through OptiScaler is untried (the shared component and `nvngx_dlssnr.dll` exist).
- No place titles, no scouting overlay, no visual set; `tests/test_install.py` has no Cyberpunk part.
## Known gaps

- The add-on reads the frame after ReShade's effects, so a game's visual set (RDR2's preset, ray
  tracing) is in every frame by design; `--no-preset` captures without effects.
- Anything another mod draws on screen is in the frames too: an open Native Trainer menu, for
  example. Nothing detects that yet; keep such menus closed during a take.
- Frames saved before 2026-11-20 12:07 (every take in `out/takes/_before_queue/` and the
  lakeshore sample) have red and blue swapped: ReShade's `capture_screenshot` returns the swap
  chain's own BGRA layout, not RGBA as documented. The add-on now orders channels by the back
  buffer's format (checked against a screen grab: mean difference 1.5).
- Takes rendered at 1600x900 (before 2026-11-20) have upscaled portrait crops (768x1344); the
  capture size is now 2560x1440, where they are native.
- A fixed rig file (`--rig`) is placed as solved on an open floor: nothing stops a camera
  standing inside a rock. Solved rigs (`--solver`) fit the scene, within what the rays reach
  (BACKLOG.md: solved rigs).
- No resume: a take runs in one go.
- Raw frames are uncompressed BMP; depth is not captured.
- The full take of 2026-11-20 (`out/takes/_before_queue/full_20261120_102239`, before the
  per-shot checks existed) is clean through clip frame 52: from partway through frame 53 the
  player is visible and frames 54-55 show the pause screen.
