# capture_mod

Captures a camera rig (a `camrig/v1` file from the camera-rig repository) inside a running
game: the world is held at exactly one instant across every view, stepped by exactly 1/fps
between instants, and the result is packaged in the rig repository's delivery layout.
The first game is Red Dead Redemption 2 in story mode.

```
capture/            game-agnostic: rigs, placement, shot lists, the take loop, per-shot
                    checks, packaging, sheets, locations, the job queue, the worker, the CLI
adapters/rdr2/      everything RDR2: the adapter, Lua jobs, the ReShade add-on, launch and
                    recovery scripts, the render camera writer, research probes
tools/              generic helpers (frame reports, documentation media)
out/                all capture outputs (gitignored; CAPTURE_OUT moves it)
BACKLOG.md          designed-for but not built: shot reuse, solved rigs
```

## Workflow

Scout locations, submit a rig for them, let workers capture. Scout and worker can run on
the same machine one after the other (the worker teleports to each location).

```powershell
# 1. scout: record where the player stands (or --at=x,y,z to go there first), with four
#    previews looking outward (front, right, back, left of the facing) at eye height
.\capture.ps1 scout --name lakeshore --tags open,shore
.\capture.ps1 locations

# 2. submit: one job per location for a rig file (copied into the queue, never changed)
.\capture.ps1 submit --rig <rig_yiming_stdm.json> --location rdr2-lakeshore-001
.\capture.ps1 submit --rig <rig.json> --all --last-frame 3 --sweep-stride 30   # a quick sample
.\capture.ps1 submit --rig <rig.json> --location <id> --cameras "?_near_sweep_t000"   # only some cameras
.\capture.ps1 queue

# 3. worker: claim jobs until none are left (--once: one job)
.\capture.ps1 worker
```

`capture.ps1` runs `python -m capture` through uv with this project's Python. The rig files
are in the rig repository, e.g. `~/repos/gamecapture-camera-rigs-huixin/web/data/demo/rig_yiming_stdm.json`.

Tested 2026-11-20 on one machine: two locations scouted (one where the player stood, one
reached with `--at`), then a worker took a 3-frame sample job, teleported back to the first
location and captured it: 480 shots in 2.2 min, none recaptured, 275 cameras packaged, read
by the rig repository's `qc/stdm_view.py` (275 cameras, 18 groups, Diverse).

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
every worker on start). Failed jobs stay in `failed/` with the error until
`capture queue retry <job>`.

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

## Adding a game

Implement `capture.adapter.Adapter` in `adapters/<game>/` and register it in
`capture/adapters_registry.py`. The adapter supplies the world conventions (how the rig
frame maps into the world for a facing, the heading basis) and the operations: go to a
location, ground point, clock, hide the subject, a preview view, freeze, write a camera,
capture, advance by exact seconds, health, recover. Optional capabilities (`snapshot`,
`scene_mesh`) are for the backlog items.

## RDR2 adapter

### Setup

Script Hook RDR2 and the dinput8 ASI loader in the game folder, then:

1. **RedLua** (https://github.com/igor725/RedLua/releases, v0.6.4): extract into the game
   folder so `RedLua.asi` sits next to `RDR2.exe`. Scripts live in `<game>\RedLua\Scripts`.
2. **ReShade 6.8** (Vulkan) with add-on support.
3. **Build tools**: Visual Studio or Build Tools with "Desktop development with C++" (includes CMake).
4. Build and deploy (game closed):

```powershell
.\adapters\rdr2\scripts\fetch_deps.ps1     # ReShade v6.8.0 headers into adapters\rdr2\deps
.\adapters\rdr2\scripts\build.ps1          # adapters\rdr2\build\Release\capture_mod.addon64
.\adapters\rdr2\scripts\deploy.ps1         # add-on and Lua scripts into the game folder
.\adapters\rdr2\scripts\patch_natives.ps1  # names for the photo-mode exposure natives (backup: natives.json.orig)
```

The game-side scripts and the add-on exchange files in
`%USERPROFILE%\Documents\RDR2Modding\captures` (fixed in `capture_loader.lua` and
`ReShade.ini`). Frames only pass through it; the worker moves them into `out/`.

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
  collision and the scene are loaded around it, then it is put on the ground.
- **Speed.** 0.20 s per shot at 1600x900; the full ST-DM rig (12,356 shots, 24,387 camera
  frames) takes 41 min and 50 GB of BMP; 1.3 GB packaged.

RedLua quirks: parameters typed `Any` only accept `native.new('Any', 1)`; out-pointers are
`native.new('float', 1)` read with `[0]`; RedLua's `natives.json` names some natives only by
hash (`patch_natives.ps1`).

### Research probes

`adapters/rdr2/probes/` holds the tools the method was found with (memory scans, the frozen
orbit, geometry and step checks). They are not part of the pipeline.

## Known gaps

- The ReShade preset's effects (sharpening, chromatic aberration, colour matrix, fake HDR) are in
  every frame: the add-on reads the frame after them.
- Frames saved before 2026-11-20 12:07 (every take in `out/takes/_before_queue/` and the
  lakeshore sample) have red and blue swapped: ReShade's `capture_screenshot` returns the swap
  chain's own BGRA layout, not RGBA as documented. The add-on now orders channels by the back
  buffer's format (checked against a screen grab: mean difference 1.5).
- At 1600x900 the portrait crops (768x1344) are upscaled; delivery needs a render at least 1344 high.
- Rigs are placed as solved on an open floor: nothing stops a camera standing inside a rock.
  Scouting picks open spots for now (BACKLOG.md: rig solver format).
- No resume: a take runs in one go.
- Raw frames are uncompressed BMP; depth is not captured.
- The full take of 2026-11-20 (`out/takes/_before_queue/full_20261120_102239`, before the
  per-shot checks existed) is clean through clip frame 52: from partway through frame 53 the
  player is visible and frames 54-55 show the pause screen.
