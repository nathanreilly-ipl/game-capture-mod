# Backlog

Work that is designed for but not built. Each item says what the current system does instead,
and what is already in place so the item can be added without reworking the pipeline.

## The QC loop: what is left (docs/QC_LOOP.md)

- **Automatic back-and-forth.**
  - Now: the Windows session mediates every exchange. It runs `capture qc pull/run/push` when the
    CoreWeave session's message names a game and round, and messages back when the feedback is up.
  - Planned: a watcher on each side, polling `s3://.../transfer-qc/` for a new `manifest.json`
    (Windows) or `feedback/findings.json` (CoreWeave), then running the next step.
  - In place: `qc pull` and `qc push` are each one command, and `qc run` picks up games queued while
    it runs.
- **Splitting a big round over consecutive reviewers.**
  - Now: one reviewer per game per round, so a round too big for one is sent smaller (CoreWeave's
    choice of data).
  - Planned: `qc run --takes-per-agent N`, which gives a game's takes to reviewers one after the
    other, each carrying the last one's findings, and merges their findings.json files.
- **The QC tool survey (CoreWeave, step 0).**
  - An NPC track log recorded at capture time (the adapters' `obstacles()` per clip frame), with a
    tool that flags speed outliers, stops, flying, and paths bending around the parked player.
  - An evidence tool: time strips, difference maps between neighbouring clip frames, same-instant
    pairs, crops where metrics flag something.
- **Round summaries on the work-docs page.** Written by hand from each round's `report.md` for now.

## Top priority now: visual faults in the CoreWeave takes (before The Witcher 3)

Set by Nathan, 2026-11-23, after watching the nine locations' takes on the work-docs page (near
sweep and 30 clip frames each, Linux on CoreWeave). Most faults show in the 30-clip-frame takes,
where the world steps 1/30 s between clip frames. Tick an item once a retake at the same place
shows it gone and `tools/temporal_flicker.py` (each fixed camera's clip frame against the average
of its neighbours) says so; the numbers before are in `out/checks/visual_20261123/before/`, after
in `.../after/`. "First multi-frame" below is the moving camera's video, "second" the fixed camera
00's. docs/VISUAL_CHECKS.md has every fault, its check and its fix for any game. None of the fixes
below is committed yet (2026-11-24).

Cyberpunk 2077 (fixed cameras before: roughness 0.46-0.61 Kabuki, 1.10-1.41 Cherry Blossom
Market, 1.33-1.59 Badlands; pixels over 12: 0.2-0.5%, 0.7-1.0%, 2.2-2.9%):

- [x] **Time-lapse of what runs on the real-time clock between clip frames.** A time step
  released our clock plug-in to full speed for the whole step, so the clock moved 1.67 s per 1/30 s
  step (`probes/step_clock_probe.py`): ad billboards changed picture every clip frame, foliage
  thrashed, people's small motions jumped. The game's frame time follows that clock, so a step now
  keeps the dilation at 1 and slows the clock alone (session command `step`; the clock moves 33-40
  ms per step, steps 33.331-33.333 ms). Badlands retake (2026-11-23): fixed cameras roughness 1.33
  and 1.59 to 0.40 and 0.47, pixels over 12 2.2% and 2.9% to 0.03% and 0.11%, brightness jitter 0.32
  to 0.08. Kabuki retake: roughness 0.46 and 0.61 to 0.41 and 0.42, pixels over 12 0.19% and 0.53%
  to 0.08% and 0.07%; the sign that changed picture every few clip frames shows one picture
  throughout. Left: at clip frame 19 of the Badlands retake the whole scene brightens 0.5 levels and
  the bushes change shape once (a gust or a cloud edge, both cameras).
- [ ] **Cloth through time steps** (from the PC session's The Witcher 3, 2026-11-24: steps that
  end on microsecond frames kicked the cloth solver). Cyberpunk's `step` also ends on small frames
  (an eighth of what is left per frame, then the dilation for the last microseconds). No kick seen
  in the Kabuki and Badlands retakes or at the Cherry Blossom Market (`hold_step_check.py`: the
  flicker map shows only a walker), but nothing with cloth was aimed at. Check with a flag or
  awning in a fixed camera; if it kicks, even frames as the PC session did.
- [x] **NPCs gliding across the ground in sync** (Kabuki, moving camera): the old take's walker
  goes through a stride every clip frame or two while hardly moving (walk animation on the
  time-lapsed clock). With `step`, a walker at the Cherry Blossom Market takes half a stride over 15
  steps (0.5 s), as walking does (`hold_step_check.py` steps sheet, 2026-11-23). The Kabuki retake
  had no walker in view.
- [x] **Path-tracing noise between clip frames** (all three places). With the clock fixed, what is
  left between steps equals the change within one step: renderer noise. 8 frames averaged per shot
  instead of 4 (the default now): Badlands roughness 0.54/0.44 to 0.46/0.30, brightness jitter 0.05
  to 0.02 (`hold_step_check.py`, 2026-11-24), 12% more frames per shot.
- [ ] **Exposure 9 and 14 levels of 255 too bright at Kabuki and Badlands**: the forced exposure
  has a floor the lock cannot go under (README, Cyberpunk on Linux). Not a flicker, but wrong.
  `Rendering/ForcedPreExposure` does not help (70-82 for 0.001 to 10, Kabuki 2026-11-23,
  `probes/exposure_range.py --option ForcedPreExposure`). Tried 2026-11-24 at Kabuki at noon
  (`exposure_range.py --category ... --hold 1000`): `DLSS/ExposureScale` moves the held frame only
  62.1 to 58.6 for 0.25 to 4; `Developer/FeatureToggles/EyeAdaptation` false drops it to 4.3 (a fixed
  default exposure), so neither helps. That day the floor (63-69) was below auto-exposure (69-77):
  the failing case depends on the light and was not reproduced. Left: `Rendering/ACES/*`.
- [ ] **One step that changes every camera at once, mid-clip** (QC rounds 2-3, cyberpunk-003/013/
  016): Kabuki between clip frames 14 and 15 (a banner gets its texture, a puddle's reflection and far
  windows change), Badlands between 25 and 26 (grass and bush shadows regenerated). Not a game minute
  passing (`probes/tod_step_probe.py`), not detail first asked for mid-take (12 pre-roll steps showing
  each of the take's cameras, 2026-11-25), not real time: 30 s held at the first pose inside the
  pre-roll (`preroll_wait_s`, capture/runner.py) only moved it (Kabuki 15 -> 9, Badlands 26 -> 23,
  2026-11-26). It comes 0.57-1.23 s of game time after the world is first held (17-37 steps), the
  banner going from plain to its full pattern as a detail level arriving would. Being tried: 60
  pre-roll steps (2 s of game time at the rig). Every shot's log line carries `wall_time` (UTC).
- [ ] **A walker 1.0-1.5 m in front of a lens for half a clip** (QC round 3, cyberpunk-021, Kabuki):
  the start-of-take clear deleted only what stood within 1 m of a camera's position. Cyberpunk now
  deletes people within 1.5 m in front of a camera, inside its view, too (`obstacle_front_m`; other
  games unchanged). Check in round 4; someone who walks in later is left (a real crowd does).
- [x] **Steps 34.2-34.7 ms instead of 33.3** in 2-3 of 29 steps at Kabuki and Badlands (the
  advance overshot on a slow frame). With `step`: 33.3314-33.3327 ms over the 29 steps of the
  Badlands retake.

RDR2 (fixed cameras before: roughness 0.33-0.64, pixels over 12 at most 0.35%):

- [x] **Exposure falls over the take at the lakeshore**: brightness 117.3 at clip frame 1 and
  105.3 at frame 30 (camera 00): the "white flash" at the start. Cause: the game's clock runs 30
  times real time (2000 ms per game minute), so each 1/30 s step moved the sky and its light by a
  second. `hold_step_check.py` at Saint Denis, 30 steps, the take's two fixed cameras (2026-11-24):
  exposure drift 0.970/0.978 and 0.915/0.916 at the game's rate, 0.999/0.993 at real time. Takes
  now run the clock at real time (`clock_ms_per_minute` 60000, session command `clockrate`; given
  back after). Lakeshore retake: 0.991/0.992 (was 0.89).
- [ ] **A smooth 2-4% exposure change over the first 10 clip frames** (Saint Denis, Rhodes, with
  the clock at real time; up in some takes, down in others): not from the obstacle checks, the
  order of the cameras, the view showing during a step, the eye adapting before the lock (primed on
  sky or ground: same), or a clock jump; not seen in `hold_step_check.py` at the same place. A
  15-step pre-roll turned +3% into -3%.
- [x] **Shadows flicker very dark in some clip frames** (Saint Denis: the house most). With the
  game's clock at 30x the house's gable switched between sun and shade at clip frames 3, 11 and 13;
  at real time once, at clip frame 3, in 2 of 4 takes; with 3 pre-roll steps before clip frame 1
  (`preroll_steps`, capture/runner.py) in 0 of 2 (2026-11-24). Rhodes' basket: no pop in the
  retake.
- [ ] **Rain splashes in a Rhodes puddle may run too fast and look noisy** (no reference yet):
  check whether particles follow the game timer.
- [ ] **The corners darker** (also in the PC's Saint Denis sweep of 2026-11-20). Measured with
  `tools/vignette_check.py --game rdr2` (the same patch of scene at the centre and turned near each
  corner, exposure held): 0.57/0.20 of its centre brightness at the top/bottom corners in haze,
  0.29/0.56 in sun; the same with Reality Redemption 2 off and with no ReShade effect at all;
  Cyberpunk by the same test 0.93-1.08. So the game renders a point darker toward the frame's
  edges depending on what surrounds it, a per-camera difference. It acts like a local tone mapper
  (the whole frame darker when bright sky or sunlit road fills it; `exposure_check.py` shows the
  exposure itself held). Not the game's HDR setting (`hdr` false: the same 0.45-0.73 on the
  landscape view, 2026-11-24). Not a setting in system.xml either (`probes/corner_variants.py`,
  Lakeshore, wide view, 2026-11-26, each written with the game closed and the game started again):
  SSDO off, screen-space sun shadows off, probes relit every frame, full-screen SSAO, the filmic
  curve off and HDR off all leave the four corners where they were (within 0.02). What moves them is
  the scene: with the weather left free the runs split by weather (clear sky with clouds: top
  corners 0.64-0.66, bottom 0.34-0.35; haze: 0.77-0.81 and 0.29-0.31), and with the weather held
  sunny at noon top 0.33-0.34, bottom 0.60-0.64. The patch is the same bush tip in every view, so
  the darkening follows what fills the rest of the picture (a view turned down onto sunlit sand
  darkens it most): an exposure or tone mapping keyed to each view's content, not a fixed vignette.
  Next: whether the photo-mode exposure lock holds in vignette_check's views (the same patch with a
  bright and a dark object brought into the frame's far side).
- [x] **Motion blur is on in RDR2** (`<motionBlur value="true" />` in system.xml, from the PC's
  profile). A per-camera effect AGENTS.md wants off: moving people were blurred along their 1/30 s
  motion. The install now writes `motionBlur` false (XmlSet, 2026-11-24; in the retakes).

GTA V Enhanced (fixed cameras before: roughness 0.21-0.90, Vinewood 0.8-1.1% of pixels over 12):

- [x] **NPCs disappear in the background between clip frames** (Vinewood, both multi-frame
  videos). Measured: with the multipliers at 0 the game removed 5 people and 2 cars within 150 m
  over 30 steps (`tools/hold_step_check.py` census, 50-130 m out). Fixed in the check: the session
  makes everyone within `keep_radius` (150 m) its own for the take (command `keep`): 0 people gone,
  1 car at the 150 m edge. Vinewood retake: fixed cameras roughness 0.74/0.72 to 0.53/0.39, no
  pop but palm shadows at clip frame 9 (below). Takes record the people and cars kept and the
  wind. The 2026-11-24 retakes: nobody vanishes at Vinewood; 20 people kept at the Alamo Sea.
- [ ] **Shapes flicker in and out on trees and a background billboard; bad geometry in far
  trees** (Vinewood): `temporal_flicker.py --size 960x540` finds pops at clip frame 20 (old take)
  and 9 (retake) on palm fronds' shadows on a wall: different for one clip frame, then back.
  Palms move with the wind as the banner does; a held world shows no change there. A test with the
  wind held at 0 was cut short by RedLua's fault.
- [ ] **A flag near the red cube vibrates** (Legion Square, moving camera). Measured: still in a
  held world; across steps it moves with the wind (12 m/s: roughness 2.05 with the 67-frame steps,
  4.26 with 4 frames of 8.3 ms; with the wind of the first check it hardly moved). The game's cloth,
  not a clock. To decide: record the wind per take, and hold it lower during takes or not.
- [ ] **Temporal noise in ray-traced reflections** (the marble ground at Vinewood, faintly the
  whole frame, near sweep). A held world shows none (spread over 4 on 0.000-0.085% of pixels), so it
  is the history after each camera cut. Vinewood near sweep with 80 settle frames against 40:
  brightness jitter along the sweep 0.43 to 0.054 (one take each; the crowd differs, so roughness
  cannot be compared). To decide: settle 80 for GTA V Enhanced (a sweep takes 13 min instead of 7).
  Also: exposure follows the view slowly even in a held world (+0.4 levels after 67 frames on a
  brighter view, 1.2-1.4 between steps when cycling views; `probes/step_exposure_probe.py`;
  `SET_EXPOSURETWEAK` did not hold it).
- [x] **The clock of day moving the light between clip frames** (RDR2's fault, A5): not in GTA V,
  exposure drift 1.000 on both fixed cameras over 30 steps at Vinewood with its clock running
  (2026-11-24). Nothing to change.
- [ ] **RedLua faults mid-session** (`lua51.dll+0x5C83`, `+0x5DDE`): four times in
  `hold_step_check.py` runs on 2026-11-23/24, each during its per-step census of people (with and
  without `keep`); without the census the run went through. Takes list obstacles once per clip
  frame and went through. Watch the worker logs for restarts.
- [ ] **Aliasing**, slight in general and in the far background (Legion Square, right edge near
  the truck, camera 00). The game runs DLSS under Proton (nvngx_dlss loaded, settings.xml DLAA,
  sharpening 0.8). Options: sharpening 0; rendering 3840x2160 and scaling down.

## Top priority: the game-agnostic code on Linux, what is left

Set by Nathan, 2026-11-23, as the long-term priority. Started that day, once Cyberpunk 2077
rendered a frame through the capture add-on under Proton on a CoreWeave node (docs/LINUX_PORT.md).

**Done (2026-11-23, README "On Linux"):** `capture/host` (the machine a game runs on: Windows, or
Proton on a headless display), `capture host status|setup|prefix|stop|steam` with its pinned parts
(`capture/host/linux.lock.json`), `capture.sh`, `adapters/common/window.py` and `mem.py` with a
Windows and a Linux implementation each, the installer on Linux (paths written as the game sees
them, our two plug-ins taken built from a mods bundle, Wine's per-exe DLL overrides as a step),
a Steam client inside a prefix for the games that need one, 32-bit Windows programs where 32-bit
system calls are forbidden (`wow64/tls32.c`), and three games through all of it from the Windows
PC's bundles on fresh depot downloads: Cyberpunk 2077, RDR2 and GTA V Enhanced each pass
`capture verify <game>`, and the worker captured and packaged a near sweep and a 30-clip-frame
take at three locations for Cyberpunk 2077 and RDR2 and at two so far for GTA V Enhanced (Alamo
Sea, Vinewood Boulevard; the solver declined Legion Square: no collision-free near ring there).

Left, game-agnostic:

- **The game's files by the command line.** They were downloaded by hand with DepotDownloader
  (README; `out/probes/linux_port/scripts/depot_download.sh` is what ran). A `capture game fetch
  <game>` would take the app, depot and manifest from the game's adapter (RDR2 and GTA V now have
  them as `STEAM` facts) and the owner's Steam login; which tool, and where the login is kept, is
  Nathan's call. DepotDownloader keeps its login per path of its own program.
- **The game user's files.** Saves and settings files are copied into the prefix by hand, and
  the first start to make a game write its settings file is a manual step. Both Rockstar games
  throw a settings file away that names other hardware: RDR2 goes by `videoCardDescription`
  (an install step sets it), GTA V Enhanced also by `VideoDriverDescription`,
  `MinimumVideoDriverDescription` and `CPUDescription`, whose values only the game knows (580.99
  for driver 580.178.04): on 2026-11-23 they were taken by hand from the file the game wrote on
  its first start and put into the PC's file. A command that takes a folder or a bundle of user
  files, does the first start and merges such lines is not written.
- **The Steam client in a prefix: what was done by hand.** `capture host steam <game>` unpacks
  the client, installs its service, registers the game and keeps the client running. Not in it:
  the two sign-ins (the owner's, once, in a remote view); accepting the game's EULA in Steam's
  window (a click, once per game); the remote view itself (x11vnc, noVNC and websockify from
  Ubuntu's packages, unpacked into `out/host/sysroot` and started by hand, password in
  `out/host/vnc`); the prefix folder made readable by its owner only (it holds the logins;
  `/mnt/data/<user>` was group-readable on the cluster). The client ends itself or stops taking
  requests some minutes after a game it started is closed ("BMainLoop appears to have stalled >
  15 seconds"; by signal and by taskkill alike), so a stop ends the whole prefix and `--keep`
  starts the client again: every restart of a Rockstar game costs a client start (about 1.5 min).
  Why it stalls was not looked into.
- **`wow64/tls32.c` is a way around a restriction of the cluster** (README): Nathan knows; the
  cluster's owner has not been asked. It finds Wine's function by its bytes (wine-staging 11.0,
  GE-Proton11-12) and changes nothing when it does not find them; another Wine needs a look.
  Entry 12 of the three per-thread GDT entries is taken without asking whether it is free.
- **`capture host setup` was run in parts only.** Proton, the runtime and the Ubuntu packages
  were fetched by hand on 2026-11-23 and the command written from that. Run as written since:
  NVIDIA's package for a second driver version (580.178.04, 5 s to fetch, pinned afterwards) and
  the build of `tls32.so`. ffmpeg, xclip and xsel are in the conda environment
  (`~/.conda/envs/game-capture`), strace too (for the 32-bit finding). Xvfb, xkbcomp and xdotool
  could move there from the unpacked Ubuntu packages: conda-forge has xdotool; whether it has a
  usable Xvfb and xkbcomp was not settled.
- **Nodes of one cluster differ.** Two jobs landed on driver 580.105.08 and 580.178.04; NGX
  files are now chosen by the node's driver and a prefix gets them without a Proton run. Each
  start of the runtime container took 50 to 70 s on the second node (network file system).
  Proton's `waitforexitandrun` waits for everything in a prefix to end, so `host.run` blocks
  while a Steam client lives there; `wine_direct` does not.
- **Several games on one node.** One display per game (`CAPTURE_DISPLAY`), one GPU per game (a
  job step), one prefix per game or per launcher. Cyberpunk ran beside the Rockstar prefix that
  way on 2026-11-23. Two Rockstar games at once (one launcher, one Steam account) were not tried.
  Nothing in the repo starts job steps; `capture/host` only refuses several GPUs.
- **`tools/`** that press keys or list processes (`upscaler_ab`, `upscaler_sweep`,
  `dlss5_skin_sweep`, `preset_ab`) were not run on Linux; F13 to F16 (OptiScaler's live switches)
  are mapped in `window_x11.py` but never pressed there.
- **The scout overlay** (RDR2's F8 to F11) was not looked at on Linux. `capture scout` works there
  (GTA V's Alamo Sea location was scouted on the node).
- **Frame rate: ask Slurm for one thread per core.** At the Cherry Blossom Market, 2560x1440
  path traced, the RTX PRO 6000 under Proton (2026-11-23):

  | Slurm job | CPUs the game used | frames/s running | held | GPU | s per shot |
  |---|---|---|---|---|---|
  | `--cpus-per-task=8` | 4 (24, 25, 27, 28) | 17 to 18 | 25 to 26 | 40 to 50%, 220 to 250 W | 7.28 (345-pose near sweep) |
  | the same with `--hint=nomultithread` | 8 (2, 3, 8 to 13) | 28.1 | 36.3, 38.5 | 71%, 290 W | 5.59 (every 8th pose, 44 shots) |

  The PC (RTX 5090) took 2.50 s per shot. Slurm counts threads as CPUs there (`CR_CPU_MEMORY`),
  so 8 CPUs were 4 cores with both threads, the second thread being the first's number plus 64,
  and no process in the game's prefix ran on a CPU numbered 64 or more (a Windows affinity mask
  has 64 bits; that this is the reason is an inference). With the hint the job was given 8 cores
  (16 threads allowed, counted as 8 CPUs) and all 82 of the game's threads were on the eight
  numbered below 64 (the Windows session's idea; `out/probes/linux_port/cpu_test`).
  `WINE_CPU_TOPOLOGY` changed nothing (tried, taken out). Presenting to Xvfb is not the limit:
  vkcube does 2560x1440 at about 360 frames/s there. Left: the hint is not in the job this was
  developed in (`vscode-tunnel.sbatch`, Nathan's); nothing in the repo starts Slurm jobs; more
  than 8 cores was not tried (the GPU was still at 71%); and at 37 frames/s held the 132 frames of
  a shot take 3.6 s, so about 2 s of each shot goes elsewhere (not looked into; the game's folder
  and `out/` are on a network file system).

## Then: the game-specific parts on Linux, what is left

Set by Nathan, 2026-11-23, to follow the item above. `capture verify <game>` passes on the Linux
machine for Cyberpunk 2077, RDR2 and GTA V Enhanced (2026-11-23; each game's README section has
the numbers). What that took per game is in the adapters; what is left:

- **No DLSS 5 there.** OptiScaler needs a newer driver than the cluster has (580), so all three
  were installed with `--no-optiscaler`. RDR2 then renders with the game's own DLSS at Quality
  (its DLAA came from OptiScaler's ratio override), GTA V Enhanced with its own DLAA, Cyberpunk
  with DLAA and Ray Reconstruction. Whether OptiScaler's ratio override alone works on 580 was
  not tried. `capture verify` and the worker pass without it; `capture install <game>` without
  the flag would add its steps.
- **RDR2:** Reality Redemption 2's add-on loads (ReShade's log); its picture was not compared
  with the PC's. The five PowerShell scripts (`adapters/rdr2/scripts/*.ps1`) are still Windows'
  own: on Linux `launch.py` does the restart; reload, input and run-a-job have no Linux twin
  (`redlua.run_job` runs a job from Python on both).
- **GTA V Enhanced:** the settings menu navigated by screenshots (`settings_menu.py`: live ray
  tracing and DLSS mode switches) was not run on Linux; NaturalVision Enhanced loads (Script
  Hook's log) and its picture was not compared with the PC's; the protection crash was not seen
  in the first hour. `adapters/gtav/launch.py`, rewritten onto `adapters/common/window` and
  `capture/host`, runs on Windows (the PC, 2026-11-24): story mode in 71 s and 66 s, and
  `capture verify gtave --launch` passes but the machine step (120 frames/s, a frozen 8-camera
  take, both steps 0.00 ms off).
- **RedLua gives a shape test's handle back as another object** of the same number (the
  session's camera: "ScrHandle expected, got Cam"): every RDR2 take after the first failed in
  its scene raycast on Linux until the ray was simply tried again (both games' session jobs,
  2026-11-23). Not seen on Windows; nothing about it is Linux's.
- **RedLua faulted in lua51.dll** in GTA V when a scout opened a session seconds after verify's
  had ended (two "starting" lines in the loader's log, then Script Hook V's error box): the
  known fault when a finished job is collected. The worker restarts the game; a box like that
  is not detected as such (the heartbeat goes stale).
- **Cyberpunk, a stale heartbeat right after a session:** a `verify` started within about 10 s
  of another session's end was refused once ("stale heartbeat", older than 5 s); 30 s later the
  heartbeat was a second old and verify passed (2026-11-23, Linux; not looked into, not tried on
  Windows). GTA V's heartbeat also pauses for some seconds after "loader ready" while the world
  loads. A worker going from one job straight to the next could meet the same.
- **Cyberpunk, the exposure lock does not reach the first shot's brightness in sunlit places.**
  The forced average luminance has a floor: at Kabuki at noon, one view, the frame's brightness
  was 248.6 at 0.01, 161.7 at 1, 66.2 at 10, 64.4 at 100, 62.8 at 1000 and 61.0 at 1e6, where
  auto-exposure gave 71 to 73 (`probes/exposure_range.py`, Linux, 2026-11-23). A first shot that
  auto-exposure made darker than that floor is not reached, the search ends at its upper end and
  the take is held brighter: Kabuki 78.0 for 72.4 and, with the upper end raised to 1e6 for a try,
  71.6 for 63.2 on Linux; on Windows Kabuki 75.8 for 67.1, Badlands 178.3 for 165.9. Raising the
  range is no fix (taken out again). The take is still held at one exposure. Not looked into:
  why auto-exposure gets below the floor (its own metering, or a compensation the forced value
  skips), whether `Rendering/ForcedPreExposure` or the free camera's exposure options can make up
  the rest, and whether the first reading (one frame after the pose is set, where the search's
  readings wait twelve) is itself darker than the settled frame.
- **`capture verify`'s colour check** grabs the screen after the preview let the world go, so it
  compares two different pictures in Cyberpunk (51.5 against 51.8 with the channels swapped,
  where one held instant gives 0.19 against 11.22). RDR2 (0.6 against 11.9) and GTA V (3.0
  against 41.8) separate well. Not a Linux matter, found there.
- **The Witcher 3 and Kingdom Come: Deliverance** run on Linux since 2026-11-24 (their own
  sections below say what it took and what is left).
- **`capture verify`'s colour check in The Witcher 3 and Kingdom Come: Deliverance** does not
  separate either (51.9 against 54.1 with the channels swapped; KCD 34.1 against 35.9; Linux,
  2026-11-24): the screen grab is taken after `view()` gave the camera back, the same fault as
  Cyberpunk's above.

## The Witcher 3: what is left

Set up on 2026-11-23 (README: The Witcher 3 adapter). Left:

- **A scouting overlay.** The script cannot read files, so `publish_locations` would have to paste
  the saved locations into the console as a command the script keeps; the overlay itself (position,
  place, nearest location, keys to cycle, view and teleport) is WitcherScript with the game's own
  input bindings. Not started; scouting is by agent (`probes/scout_fast_travel.py`, `capture scout`).
- **An eval.** WitcherScript compiles at start only. A command interpreter in the script (a few
  getters and setters by name) would let an agent try more without a restart.
- **The player's horse** is hidden with the player when ridden; a horse standing near the rig is
  an ordinary animal (the obstacle check sees it).
- **A texture overhaul.** The visual set is the game's own path tracing, DLAA with Ray
  Reconstruction, and DLSS 5. The community's texture pack, HD Reworked Project NextGen Edition
  (Nexus Mods, about 11 GB, made for the 2024 build 4.04), was not tried: nothing says it works with
  the 2026 Remastered update and its path tracer, and its "2026" edition was announced, not seen.
- **Ray Reconstruction or the game's own denoiser.** The game's denoiser varies less from frame to
  frame (6.4% of pixels against 16%); near sweeps with each at one place were not compared.
- **Linux (CoreWeave, 2026-11-24).** Installed from the PC's bundle with `--no-optiscaler` (no
  DLSS 5 on the cluster's driver), `verify --launch` passed but the install-steps check (which
  counts OptiScaler's steps): 55 frames/s, 24 shots in 205 s, steps within 0.31 ms. Found on the
  way, each now in the code: the game reverted path tracing and detail settings at every start
  until `[Hidden] HasSetup=true` was written (`settings.py` DETAIL); the console paste needs xclip
  (in the conda environment, `linux.lock.json`); keys held at least 60 ms; and Ctrl+V sent by
  xdotool at once often reached the console as a plain "v", so about every second long command
  missed its first try and one in about 50 missed all four: every take failed in its scene
  raycast until `window_x11.paste` sent Ctrl and V a key's hold apart (40 ray commands, none
  missed; 2026-11-24). A ray command that still gets no answer is split in two and sent again.
  Not compared: the picture against the PC's.
  - **A crash** 1 h 45 min into a session, mid near sweep (Mulbrydale, 21:30 on 2026-11-24; the
    game's CrashInfo.json: not out of memory; the step's peak 7.5 GB). The minidump is in the
    prefix (`AppData\Local\REDEngine\ReportQueue`), not read. Run the worker in a job step with
    one GPU of its own, so it can restart the game: from a step that sees two it cannot.
- **A floating spear** (Nathan, 2026-11-23, Hierarch Square): a spear or bolt in mid-air beside a
  stall, during a probe that had just parked the player 80 m away and back, which emptied the
  crowd around the spot (22 to 1 people within 15 m) and let it come back. Not reproduced. Ruled
  out: the hidden player's own items (they go with his body: hiding his 11 item entities too
  changed 0.002% of a close view, `probes/hide_probe.py`) and removing people (torches and all go
  with them, `probes/remove_probe.py`). Likely a guard (they carry halberds through that square)
  whose body had not streamed in yet. Takes do not move the player away; watch for it in takes.
- **The kick left in each time step.** With even steps an awning moves 2.3 levels of 255 per 1/30 s
  step against 1.5 for the world running unbroken (README: Time steps): resuming from the pause
  still gives cloth a little more than the step's own motion. Not found: whether the cloth solver
  sees the held frames as steps of zero length. Water through steps was not looked at either.

## Kingdom Come: Deliverance: what is left

Set up on 2026-11-23 (README: Kingdom Come: Deliverance adapter). Left:

- **The HD texture pack**, a free Steam DLC, is not installed on the PC or the node. Installing it
  is a Steam action, for Nathan. The look (`look.py`) would then turn on `wh_r_HDTextures`. It is
  the one step left to "the highest possible quality on all settings" (Nathan, 2026-11-25): the
  look is now every spec group at the game's top level 7 with 3x3 supersampling (README, The look).
- **The scene's light settling over a take** (Talmberg, CoreWeave, 2026-11-25): with the eye held,
  both fixed cameras of a 30-clip-frame take brightened 3.0% and 2.5%, smoothly, by about the same
  few levels everywhere, shadows included (+2.6 in dark pixels, +2.9 in bright ones): additive, so
  ambient light or the voxel GI (SVOTI) still converging while the world runs during the steps,
  not exposure and not cloud shadows. Before the eye lock the eye hid it. Sasau 0.3-0.6%, Rattay
  under 0.2% with the lock. At the look's level 7 (2026-11-25) the same Talmberg clip stays within
  0.03% (exposure drift 0.9997/0.9998): gone in one take, to watch in the QC rounds. If it comes
  back: `probes/light_settle_probe.py` (how long the light takes to settle at a first pose), then
  a longer run before the hold (ghost_run_s) or the SVOTI settings.
- **A scouting overlay.** Our script could draw with the game's UI or debug text. Not started;
  scouting is by agent (`probes/scout_places.py`, `capture scout`).
- **Cloth through steps** against the world running unbroken (The Witcher 3's
  `cloth_clip_probe.py`), at a place with banners. Steps are even by construction, so no kick from
  shrinking frames is expected; a kick from resuming after a hold was not looked for.
- **A photorealism mod.** Only the game's own top settings are used. Community overhauls (lighting,
  ReShade looks) were not tried, and no ReShade grade either.
- **Linux (CoreWeave, 2026-11-24).** Runs under Proton in the RDR2/GTA V prefix beside its
  Windows Steam client (the game's licence check wants a running client that lists it installed:
  `capture host steam kcd` writes the app manifest from `install.STEAM`). Found on the way, each
  now in the code: CryEngine crashed at start with 128 processors visible (Wine shows only the
  job's: `WINE_CPU_TOPOLOGY`, `host.start_beside_steam(limit_cpus=True)`); the game moved `Mods`
  away at a first start without `mod_status.xml`; ProtonFixes failed without an app id; with loose
  files looked up (`sys_PakPriority` 0 or 1) the menu's level did not load in 5 minutes from the
  network folder (now 2, our script switching to 0 for its own reads). By hand, once: the
  publisher's EULA accepted with E (on Nathan's earlier word for this copy). Left:
  - **Steam Cloud** brought the account's own KCD saves (a playthrough from May) into the prefix
    when the game first ran beside the client; the PC's two saves were copied in by hand. A
    session locks saving, but a game closed from its menu writes `exit.whs`, which the client
    would upload. Turn the cloud off for this app in the node's client, or keep closing the game
    by its window (as `launch.quit_game` does).
  - The start takes about 2 minutes to the menu (most of it the runtime container and the
    network folder); not measured further.

## Every game: cloth through time steps

Found in The Witcher 3 (2026-11-23): steps whose frames shrink towards the end (each frame covering
a share of what is left) give cloth a kick at every step that builds up over a take; spreading the
step evenly over its frames removed most of it (README, The Witcher 3: Time steps). Cyberpunk 2077
steps the same way (each frame a fifth of what is left, 36 frames per step) and was not checked;
RDR2 (time scale 0.1) and GTA V (the minimum step) step at a constant rate. Check each with a clip of
cloth through 30 steps beside the world running unbroken, as `adapters/witcher3/probes/
cloth_clip_probe.py` does.

## Games to buy, then add (Nathan, 2026-11-23)

None of these is owned yet. Each one is to be bought, then brought in as a game adapter the usual way
(AGENTS.md section 5). Engines and likely script layers below are first guesses from what is publicly
known, not checked:

- **Kingdom Come: Deliverance II** (Warhorse, CryEngine like the first). The first game's route is
  likely to carry over: the console with `-devmode`, Lua through `#`, and `t_Scale` (`adapters/kcd`).
- **Death Stranding 2: On the Beach** (Kojima Productions, Decima). Check first that a PC version
  exists and how it is sold. No known script layer.
- **S.T.A.L.K.E.R. 2: Heart of Chornobyl** (GSC, Unreal Engine 5). Likely UE4SS (Lua and the console
  unlocked) or the official mod kit.
- **Assassin's Creed Shadows** (Ubisoft, Anvil). Check for anti-tamper and the Ubisoft launcher
  first. It has a photo mode; no known script layer.
- **Green Hell** (Creepy Jar, Unity). Likely BepInEx or MelonLoader with C# plug-ins.
- **The Vanishing of Ethan Carter** (The Astronauts; the Redux edition is Unreal Engine 4, the first
  release Unreal Engine 3). Get the Redux edition; likely UE4SS.
- **Max Payne 3** (Rockstar, RAGE like GTA IV). An ASI loader and community script hooks may exist;
  check how the Rockstar launcher starts it.

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
   (the full verify, with its small take), and expect no "1 to do". On 2026-11-24 the second copy
   stopped itself at once ("Another ReShade instance was already loaded ... Aborting", ReShade
   6.8.0), and that day's out-of-memory stops had another cause (3).
3. **The display on the processor's GPU.** With the monitor showing the motherboard's input, the
   PC's AMD Radeon drives the display and RDR2 on the 5090 stops at its legal screen with
   ERR_GFX_D3D_DEFERRED_MEM (twice on 2026-11-24); with `adapterIndex` 1 it ran on the AMD instead.
   Kingdom Come ran on the 5090 that day (its 3D engine there, the AMD only showing the frames);
   GTA V Enhanced passed verify that morning at 120 frames/s, its GPU not checked. The launcher now warns
   (`launch.display_gpu_note`). Left: whether the 5090 can be made to work for RDR2 with the
   display elsewhere (Windows' per-app GPU preference, OptiScaler or Reality Redemption 2 off one at
   a time), or the monitor shows the 5090's output for RDR2 runs.
4. **A fresh machine.** Never tried: a PC with no ReShade, no mods and nothing in out/mods, where
   `capture mods fetch rdr2` downloads every file (ReShade, the shader repositories, OptiScaler,
   Reality Redemption 2's Google Drive archive) and the C++ build tools build the capture add-on.
   Script Hook RDR2 and nvngx_dlssnr.dll still come from the person installing (never
   redistributed).

## GTA V Enhanced: what is left

GTA V Legacy (`gtav`) is dropped (Nathan, 2026-11-22): it still installs and runs, and a full ST-DM
take ran on it on 2026-11-21 (Legion Square: 9,411 shots in 48.4 min, every step exactly 1/30 s,
QC passed), but nothing more is planned for it. GTA V Enhanced (`gtave`) works the same way since
2026-11-21: `capture install/verify gtave`, the unattended launcher, scouting with place titles and
queued takes (README: GTA V adapter); verify passes everything but the machine-wide administrator
step above, and a 32-camera moving sample at Vinewood passed QC; no full take yet. Left:

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
  so their consistency between adjacent cameras of one instant needs measuring. The game's DLSS
  mode is pinned to DLAA since 2026-11-22 (`dlssQuality` 3, 2560x1440 in; README) and switches
  live like ray tracing. No moving sample or full take with DLSS 5 yet.
- **Enhanced: launcher.** Steam keeps a window titled like its launch dialog up for about two
  minutes after Play, so the launcher answers it up to four times (30 s apart); harmless so far.
- **DLSS 5 skin controls** (`tools/dlss5_skin_sweep.py`, README): swept at Vinewood; Nathan
  picked skin structure 2, now set by Enhanced's install. Swept in RDR2 too (Saint Denis,
  2026-11-22, the repo tool end to end): smaller effects, the default warms one face to a blotchy
  orange; Nathan picked 2 for RDR2 too, which its install sets (with DLAA through OptiScaler's
  ratio override). Left: neither game's DLAA + skin 2 checked between adjacent cameras. The tool drives
  OptiScaler's menu by fixed positions (2560x1440, OptiScaler 10.0.0-dev), so a menu change breaks
  it, and the DLSS 5 page and its "Model tuning" section must be opened by hand once per start.
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
- **DLSS 5's white point** (GTA V Enhanced and RDR2, 2026-11-22): metered per view on automatic,
  now held per take from the first shot (README). Left: a brightness lift of 0.4-0.6 levels 40
  frames after any cut, the same whatever the view before and gone by 600 frames (the renderer's
  temporal settle); whether a longer settle is worth its time per shot is not measured. Earlier
  measurements with DLSS 5 on (preset_ab, upscaler_ab, the skin sweeps) ran without the hold.
- **GTA V visual presets** (`--preset`, README; no longer the Enhanced default): grade + Clarity
  as their capture preset, the others on F14-F18. Left: the grade's values are a first guess. In
  the grade + Clarity run the first preset's shots caught nearby people slightly moved (Chrome had
  the foreground when it started; the adapter now focuses the window before each key press);
  whether a focus change lets the frozen world step is not checked.
- **Enhanced: the settings-menu switch** is checked against screens grabbed at 2560x1440 in
  English; another window size or language needs its positions measured again. DLSS mode and
  frame scaling could go through the same menu if a comparison needs them.

- **RedLua faults** (seen on Legacy; Enhanced runs the same RedLua). On Enhanced, 2026-11-22: the
  loader stopped (no heartbeat) right after a session job ended, while the game played on, with
  no crash dump; a game restart fixed it. Legacy: lua51.dll faulted four times in its interpreter core, always at or just
  after the start or end of a session job (once 90 s after the full take ended, the loader idle).
  Suspected: RedLua's garbage collection of a finished job's native objects. Script Hook V then
  closes the game. The worker restarts a game that went away mid-take and takes again (up to
  twice per job; capture/worker.py, checked against a fake game in tests/test_obstacle_policy.py;
  not yet seen live), and starts a closed game before the next job. To try: keep one session for
  the game's lifetime, or stop Lua's collector during a session.
- **Street names** are still hashes (the session returns them); titles use the zone only.
- **The game timer** does not count the frozen world's steps, so `instant()` cannot see the world
  move during a recovery; frozen frames are checked by their frame time instead.
- **Locations** are not shown in game: no scout overlay for GTA V yet (`--at x,y,z` scouts).

## The install CLI and DLSS 5, what is left

`capture install`, `verify`, `uninstall` and `mods` exist and are applied on the development
machine (README: Install). Left open:
- **Clean-slate installs for GTA V Enhanced, and Cyberpunk 2077 on Windows.** Every adapter has
  to be fully portable (Nathan, 2026-11-22; `AGENTS.md`, section 2): mod files moved out of the
  game folder, a plain `capture install <game>`, then `capture verify <game> --launch`. RDR2 has
  done it on Windows (2026-11-20) and Cyberpunk 2077 on Linux, from the PC's bundle on a fresh
  game download (2026-11-23: 50 steps, verify passed); on the PC both other games were installed
  part by part with `--only`. Known gaps, found while packing Cyberpunk for the CoreWeave machine
  (2026-11-22): `capture mods bundle` does not carry a pack such as NaturalVision Enhanced; a file
  installed in a subfolder (Cyber Engine Tweaks' fonts and scripts, RED4ext, redscript) shows as
  MISSING in `capture mods status` unless its archive is in out/mods, since the existing install
  is searched folder by folder; Cyberpunk's optional visual set has no CLI flag. (Closed
  2026-11-23: the bundle now carries the clock plug-in, and `tests/test_install.py` has a
  Cyberpunk part.)
- **Two checkouts replace each other's builds of our plug-ins.** The capture add-on and the clock
  plug-in are installed by comparing the file's bytes, and two builds of the same sources differ
  byte for byte. Seen 2026-11-22 on the PC: after the clock plug-in was built in the main checkout,
  `capture install cyberpunk --dry-run` wants to replace both files in the game, which hold the
  Cyberpunk worktree's builds of the same sources ("replace, was a different version"). Harmless
  (same sources), but an install is never "nothing to do" across checkouts. Options: compare the
  source stamp installed beside the file, not the bytes; or build once and install from the
  bundle's prebuilt everywhere.
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
