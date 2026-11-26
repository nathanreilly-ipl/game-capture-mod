# Visual checks: what can go wrong in a capture, how to see it, how to fix it

A capture stands in for footage from real cameras (AGENTS.md section 1). Two kinds of fault spoil
it, and every game so far has had some of each:

- **Rendering faults**: the picture is not what a real camera would show of that instant: noise,
  exposure that moves, effects that differ per camera, history from another view, things on screen.
- **Scene faults**: the scene does not behave like a real one over the capture: a held instant
  that creeps, people who vanish, pop in, glide or react to the hidden player, cloth or foliage that
  vibrates, geometry that switches detail, screens or skies that time-lapse.

This file is the list to go through for every new game, and after every change to visual
settings, mods or an adapter's method: each fault with what it looks like, how to check it (the
tool or probe and the number to read), and what each game does about it, with dates and numbers.
BACKLOG.md holds the faults still open ("Top priority now: visual faults in the CoreWeave takes");
tick them there.

## The tools

All under `tools/` are game-agnostic: they read a take's files, or drive any game through its
adapter (`capture/adapter.py`). Run them with `uv run --project . python tools/<tool>.py`.

The QC loop's reviewers (`docs/QC_LOOP.md`) run the ones that read a take's files, on the data a
round sends; the live ones need the game and stay with the capturing machine. The last column says
which of the loop's categories each tool serves: geometry, lighting or NPC, each for continuity
(C) or accuracy (A).

| tool | reads | measures | catches | QC categories |
|---|---|---|---|---|
| `hold_step_check.py --game G --location L` | the game, live | (1) each view captured repeatedly in a held world: per-pixel spread (`share_std_over_4/12`, map); (2) 1/fps time steps, each view captured twice per step: flicker over the steps (`roughness`, `share_over_12`, map), change within one step (`within_step_diff`), `exposure_drift`, the game's step sizes; (3) a census of people, animals and vehicles at every step, matched by position (who left or arrived). `--shots <take>/shots.json --cameras ...` uses a take's own cameras; `--key`/`--key-after` press a key first and last (a ReShade preset); `--set k=v` an adapter setting; `--clock`, `--weather` | noise, real-time animation, exposure moving, flicker caused by steps, history settling after a step, people vanishing or popping in | live: lighting C, geometry C, NPC C |
| `temporal_flicker.py <take>` | a take's raw frames | per camera over its clip frames: `roughness`, `share_over_12`, `brightness_jitter`, `first_step_ratio`, `exposure_drift` (whole-frame brightness against clip frame 1 from the pixels that hardly change), `brightness_steps` and `brightness_step_flags` (a step over 0.3 levels and 3x the median), `brightness_blips` (fixed cameras: a single clip frame over 0.3 levels off the clip's median while its neighbours are not), `pops` (a region that jumps in one step while calm before, after and around it), maps; `--size 960x540` finds small pops | flicker in multi-frame takes, exposure drift or a flash at the start, pops (vanishing people, LOD switches, shadows switching), time-lapsing screens | take: lighting C, geometry C, NPC C |
| `sweep_flicker.py <take> [--warp]` | a take's raw frames (and shots.json for `--warp`) | along a sweep at one instant: each pose against its neighbours' average; `--warp` first turns each neighbour into this pose's view by the rotation between the cameras, so what is left is parallax and flicker (Electors' Square: roughness 16.1, warped 13.0) | exposure re-adapting per view, noise, real-time animation, anything that differs between cameras of one instant | take: lighting C and A (noise), geometry C |
| `vignette_check.py --game G --location L` | the game, live | the same patch of scene at the centre of a held view and with the camera turned so it lands near each corner (`live_ratio`, 1.0 = same) | vignettes and any other darkening or brightening by position on screen | live: lighting A |
| `exposure_check.py --game G --location L` | the game, live | a target view after holding the camera on bright and dark views | auto-exposure that re-adapts per view | live: lighting C |
| `clip_strip.py <take> <camera> <out.jpg> [--crop x,y,w,h] [--diff]` | a take's raw frames | one camera's clip frames side by side, a crop of them; `--diff` puts each frame's difference to the one before (x6) under it | looking at what the numbers point to (the pop boxes are crops) | take: all six (evidence) |
| `compare_sheets.py`, `preset_ab.py`, `upscaler_ab.py`, `upscaler_sweep.py`, `dlss5_skin_sweep.py` | the game, live | settings side by side at one frozen instant, with FLIP maps | what a visual setting changes, and whether it differs between views | live: lighting A |
| `frame_report.py` | a job's frames | contact sheet and pairwise differences | a quick look | take: all six (overview) |
| `qc_round.py <game> <round> [--upload]` | the capturing machine's takes | builds a QC round (docs/QC_LOOP.md step 3): per take the logs, full-resolution JPEG frames (every camera at every clip frame; a near sweep's every 6th pose and the poses around flagged ones), preview videos, sheets, temporal/sweep_flicker reports on the full take, and manifest.json | nothing itself: what reviewers get | all six (data) |
| `npc_tracks.py <take>` | a take's npc_tracks.jsonl (the obstacle list at every clip frame, since 2026-11-25) and take.json | each person, animal and vehicle near the rig linked through the clip frames: speed per step; flags teleports, jerks (speed changing faster than a body can), dead stops, lifts (flung, flying, a cart lifting off), sharp turns, popping in or out inside the reach, people inside each other (`overlaps`: centres under 0.5 m apart), and coming within 2 m of the hidden player's parked spot; with shots.json, `close_to_camera`: anything in a camera's view nearer than 1.5 m; `events`: who entered or left the list per clip frame, at the reach's edge (walking in or out) or inside it (a spawn or despawn: flagged as a pop); a top-down map; `--draw near_temporal_00,...`: every box projected onto that camera's frames with its track's name and distance | NPCs teleporting, gliding, stopping or reacting to the hidden player; things flung by physics | take: NPC C and A, geometry C |
| `qc_evidence.py <take>` | a take's frames and logs | timestamps.md (game time per shot and per clip frame: still within one, 1/fps between), per camera a strip of every clip frame and of the differences between neighbours (x6), crops around temporal_flicker's pops, a sweep's flagged poses with their neighbours and what neither has | where to look, and the frames that show it | take: all six (evidence) |
| `take_frames.py` | a take folder | where a logged frame is: the log's file, or the same stem as .jpg/.png (a QC round) | used by the tools above, so they run on a round's JPEG frames | (helper) |

Also: every take's `capture_log.jsonl` (each shot's game clock, rendered pose and field of view,
picture saturation and brightness, health problems), `steps.jsonl` (each time step: world time
advanced, frames), `take.json` (render settings: exposure lock, clock rate, people kept, wind;
obstructions, QC) and its sheets (`sweep.png`, `time.png`, `ring.png`). Per-game probes
(`adapters/<game>/probes/`) find a method in the first place: freeze, geometry, settle, noise,
clock, step clock, step exposure, exposure range. To try engine calls in a running game:
`python -m adapters.common.redlua_eval --game rdr2|gtave "<lua>"` (RedLua games),
`python -m adapters.cyberpunk.probes.repl "<lua>"` (Cyberpunk).

## The routine for a new game, or after a change

At three or more kinds of place (dense city with screens and signs, open land with foliage, water
or night), at the location's clock:

1. `hold_step_check.py` (about 10 minutes per place), with the take's own cameras once a take
   exists (`--shots`). Read: held `share_std_over_12` (about 0), `held_instant_moved` (false), the
   step sizes (1/fps, all of them), `within_step_diff` against `roughness` (roughness near
   within-step means the steps add only noise; well above it means something moves wrongly between
   steps: look at the map and the sheet), `exposure_drift` (1.00 within about 0.01), and the census
   (nobody leaves or arrives near the rig).
2. `vignette_check.py --game` once per game and visual set (live_ratio near 1.0 in every corner)
   and `exposure_check.py` (the target comes back to its own brightness).
3. A near sweep (`submit --cameras "H_near_sweep_t000"`), then `sweep_flicker.py`. Watch the video.
4. A 30-clip-frame take (`submit --last-frame 30 --cameras "H_near_moving,H_near_temporal_00,H_near_temporal_16"`),
   then `temporal_flicker.py` (and `--size 960x540` for small pops far away). Watch the three
   videos: the fixed cameras show flicker, pops and drift; the moving camera shows gliding and
   jumps. Look at what the numbers point to with `clip_strip.py`.
5. Read `capture_log.jsonl`: the game clock must not change within a clip frame; and `steps.jsonl`.

Numbers measured so far (fixed cameras of 30-clip-frame takes, `temporal_flicker.py` at 480x270,
CoreWeave, 2026-11-23/24): roughness 0.2-0.6 where nothing is wrong (GTA V Legion Square
0.21-0.28, RDR2 after its fixes 0.23-0.63, Cyberpunk after its fix 0.40-0.47, GTA V Vinewood 0.39-0.53
with walkers); 1.1-1.6 with Cyberpunk's real-time clock time-lapsing (Badlands 1.33-1.59, 2.2-2.9%
of pixels over 12). On the PC (2026-11-24, 8-camera rings over 30 clip frames of 2026-11-23): The
Witcher 3 at Hierarch Square 0.54-0.75 (path tracing's noise and a crowd; exposure within 0.2%, no
pops); Kingdom Come: Deliverance at Rattay pillory 0.42-0.97, the cameras with a grass patch in
view at the top (see E6, B2). Compare a place only with itself, and only with the same people
about (see Pitfalls).

Before 2026-11-24 the take loop let an adapter's fields replace its own in `capture_log.jsonl`:
The Witcher 3's and Kingdom Come's logs have the game's frame counter as `frame` instead of the clip
frame. `temporal_flicker.py` and `clip_strip.py` read the clip frame from the shot's name
(`t<frame>_...`), which is right for every take.

## Pitfalls when measuring

- **Walkers and traffic** make roughness and brightness move: a carriage through a fixed camera
  raised its roughness from 0.4 to 3.7 (RDR2 Saint Denis). Read the flicker map before the number;
  use `exposure_drift` (static pixels only) rather than mean brightness.
- **A median of per-pixel ratios cannot see small changes**: whole-number pixels stay equal and
  the median stays 1.0. `exposure_drift` uses the ratio of means over the static pixels.
- **Returning to a view proves nothing about an exposure lock**: an exposure that follows the view
  comes back to the same value too. Check that the target is unchanged *right after* a bright or a
  dark view (`exposure_check.py`).
- **A game's own weather and clock change between runs**: the same view measured 45, 70 and 94 in
  RDR2 an hour apart. Set clock and weather (`--clock`, `--weather`), and compare runs made one after
  the other.
- **The probe and the take differ**: a check that runs clean is not the take. When the take shows a
  fault the check does not, rerun the take (RDR2's lakeshore drift went from -11% to -1% on a retake
  before any fix; its 3% start drift shows only in takes).
- **Heavy script work can crash the script layer**: GTA V's RedLua faulted (`lua51.dll+0x5C83`,
  `+0x5DDE`) during `hold_step_check.py`'s census four times on 2026-11-23/24, with and without
  `keep`; with `--radius 0` (no census) the same check ran through. The worker restarts the game, a
  probe does not.

## Catalogue

Each entry: what it looks like; how to check; what each game does about it. "Open" items are in
BACKLOG.md.

### A. The held instant and the time steps

**A1. The world creeps in a "held" world.** People, vehicles, foliage, water still move a little
while one instant is captured, so cameras of one clip frame disagree.
Check: the game clock per shot in `capture_log.jsonl`; `hold_step_check.py` (`held_instant_moved`,
held spread); the game's freeze probe (people's positions over 240-480 frames).
Games: RDR2 and GTA V's time scale 0 still steps about 0.33 ms per frame (a 48-minute take would
move two minutes): RDR2 uses the photo-mode freeze (0.000 m over 480 frames), GTA V writes the
engine's minimum step to 1e-7 s (`adapters/gtav/timestep.py`); Cyberpunk holds with a time dilation
of 1e-7 (0.000 m over 480 frames, 113 people). A step or clock of exactly 0 crashed GTA V and made
Cyberpunk quit: hold just above the minimum. Kingdom Come: Deliverance holds exactly at `t_Scale 0`,
but its own timer (`GetCurrTime`) creeps while nothing moves (5.9 ms over 420 s held, no person
moving 0.1 mm): a game clock that moves does not prove the world moves; its take log uses the
script's own world clock (PC session, 2026-11-24).

**A2. Time steps that are not 1/fps.** Motion between clip frames is uneven.
Check: `steps.jsonl` (`advanced_s`), `hold_step_check.py` (the steps it prints).
Games: GTA V steps exactly (67 frames of 0.5 ms between two pauses); Kingdom Come: Deliverance in
8 even frames (`t_FixedStep` 1/240 s with `t_Smoothing 0`; with smoothing on, frames ramped up
after a hold), 33.3330 ms; RDR2 sums frame times at a
reduced time scale: 28-36 ms per 1/30 s step (open); Cyberpunk's `step` 33.331-33.333 ms (it
overshot to 34-43 ms until its pacing allowed for the one-frame delay of a clock change).

**A3. Things on the real-time clock change within an instant.** Video screens, ads, holograms,
blinking lights and some shader animations run on the clock the game's code reads, which no freeze
holds; they differ between cameras of one clip frame.
Check: the held spread map of `hold_step_check.py` (bright spots on screens), `sweep_flicker.py`
(brightness jitter, a screen changing along the sweep), the game's clock probe.
Games: Cyberpunk: our clock plug-in (`addons/clock`) slows the exe's and Bink's clocks to 1/5,000
while held (varying pixels 0.13% to 0.008%, Cherry Blossom Market, 2026-11-22) and devices within
60 m are switched off. RDR2 and GTA V: none found so far.

**A4. Things on the real-time clock time-lapse between clip frames.** Screens change picture every
clip frame, foliage thrashes, people moonwalk (legs cycling, body hardly moving), shadows of moving
foliage flicker: what the clock drives runs many times faster than the world between clip frames.
Check: `temporal_flicker.py` (high roughness on foliage and screens, pops on screens),
`hold_step_check.py` (roughness well above `within_step_diff`), the game's step clock probe; watch
walkers in the moving camera.
Games: Cyberpunk, found 2026-11-23: a time step released the clock plug-in to full speed for the
1-2 s of real time a step takes, so the clock moved 1.67 s per 1/30 s step
(`probes/step_clock_probe.py`). The game's frame time follows the hooked clock, so a step now
leaves the dilation at 1 and slows the clock alone (session command `step`): the clock moves 33-40
ms per step. Badlands retake: fixed cameras roughness 1.33/1.59 to 0.40/0.47, pixels over 12
2.2%/2.9% to 0.03%/0.11%; Kabuki retake: a sign that changed picture every few clip frames shows one
picture; a walker takes half a stride over 15 steps, as walking does.

**A5. The game's clock of day runs faster than real time.** The sky, sun and clouds, and the light
they cast, move many times faster between clip frames than the world: whole-frame brightness drifts
over a take, shadows switch.
Check: `exposure_drift` in `hold_step_check.py` (over 30 steps, at the take's cameras) and
`temporal_flicker.py`; the game's clock rate (RDR2 and GTA V: `GET_MILLISECONDS_PER_GAME_MINUTE`).
Games: RDR2 runs 2000 ms per game minute (30x real time): each 1/30 s step moved the sky by a
second, frames drifted 3-9% over 30 clip frames at Saint Denis and 11% at the lakeshore; at real
time (60000) 0.1-0.7% (2026-11-24). Takes now run the clock at real time (`clock_ms_per_minute`,
session command `clockrate`) and give the rate back. GTA V: its clock runs at the same rate but
the light does not move with it over a clip: exposure drift 1.000 on both fixed cameras over 30
steps at Vinewood (2026-11-24); nothing done. Cyberpunk: not measured.

**A6. Cloth, flags, foliage or particles that vibrate or kick.** A flag or plant jitters from clip
frame to clip frame instead of moving smoothly: wind on cloth stepped at 1/30 s, a simulation on its
own clock, or a cloth solver kicked by uneven frame times within a step.
Check: the held spread map with the thing in view (black there means it holds); the step flicker
map and `clip_strip.py` on it; compare steps made of different frame sizes (`--set step_frame_s=`).
Games: GTA V, a banner at Legion Square: still in a held world; across steps it swings with the
wind (12 m/s: roughness 2.05 with 67 frames of 0.5 ms per step, 4.26 with 4 of 8.3 ms; with light
wind it hardly moved); takes record the wind (open: hold it lower or not). The Witcher 3 (PC
session, 2026-11-24): steps that shrank to microsecond frames kicked the cloth solver (an awning
9-12 levels per step and growing); even frames per step fixed it (2.3 against 1.5 with the world
running unbroken). Cyberpunk's `step` also ends on small frames: no kick seen so far, cloth not
aimed at (open). Kingdom Come: Deliverance steps in even frames, so it cannot kick that way; a
kick on resuming from the hold was not looked for. RDR2: rain splashes in a Rhodes puddle may run fast (open, no reference).

### B. Exposure and tone

**B1. Auto-exposure that re-adapts per view.** Whole-frame brightness jumps between cameras of
one instant.
Check: `exposure_check.py` (the target right after a bright and a dark view); `sweep_flicker.py`
brightness jitter; `hold_step_check.py` brightness per step with several views.
Games: Cyberpunk re-adapts per view: forced average luminance bisected to match the first shot
(jitter along a sweep 2.12 to 0.45); it has a floor (B3). RDR2: the photo-mode lock holds (target
71.58, 73.9 right after the sky, 71.58 later, 71.62 after a dark view; 2026-11-24). GTA V adapts
slowly even in a held world: a view came back 0.4 levels brighter after 67 frames on a brighter
view, and cycling three views over steps moved the frame 1.2-1.4 levels (Vinewood, 2026-11-23,
`adapters/gtav/probes/step_exposure_probe.py`); `SET_EXPOSURETWEAK` did not hold it (open).

**B2. Exposure that drifts over a take, or a flash at the start.** The first clip frames are
brighter or darker and the rest converge, or it keeps drifting.
Check: `exposure_drift` and `exposure_by_frame` in `temporal_flicker.py`; `first_step_ratio`; a drift
that settles after a few frames is something converging, one that goes on is the light changing
(A5).
Games: RDR2: the lakeshore's "white flash" (-11%) was the clock (A5). Left, with the clock at real
time: a smooth 2-4% over the first 10 clip frames in takes at Saint Denis and Rhodes, up or down,
not seen in `hold_step_check.py` at the same place; ruled out: the obstacle checks, the order of
the cameras, the view showing during a step, an eye not yet adapted at the lock, a clock jump;
a pre-roll turned it around (open). Kingdom Come: Deliverance (Rattay pillory ring, measured
2026-11-24): every camera 1.1-2.8% brighter from clip frame 2 to 11, then flat to 0.1%; the same
rise on all eight cameras, so the exposure: its eye adapts on game time, which a hold stops (so
`exposure_check.py` in a held world saw nothing) and each step runs, towards whatever view is
rendered during the step, from the player's view it had adapted to before the hold. Now the camera
is at the take's first pose while the world still runs, and every step renders that pose
(`step_view`): the retaken ring stays within 0.4% over its 30 clip frames. Not everywhere: at Sasau
bridge (CoreWeave node, noon, 2026-11-24) the fixed cameras still rose 2.75% and 1.8% almost evenly
over the whole clip, the eye too slow to arrive in the 2 s run before the hold (Talmberg, the same
day: within 0.2%; the node's Rattay retake 1.006 and 1.012, from 1.062 and 1.048 before the fix).
So the adapter now also holds the eye from the hold to the end of the take (`eye_lock`,
`r_HDREyeAdaptationSpeed 0`) and lets it adapt ten times faster in the run before
(`eye_run_speed 30`). At Sasau (`adapters/kcd/probes/eye_run_probe.py`): 2 s at the game's speed
left a frame 15-25 levels from adapted, 2 s at 30 arrived; at 0 a view stayed within 0.1 levels
through 30 steps and did not re-adapt after bright or dark views. The three node takes retaken with
the lock (2026-11-24/25, fixed cameras 00 and 16):
- Sasau: 1.0033 and 1.0064 (were 1.0275 and 1.0177).
- Rattay: 0.9984 and 1.0009.
- Talmberg: 1.0302 and 1.0254 (were 1.0019 and 1.0007). This is not the eye: the frame brightens
  by a nearly constant +2.5 levels at every brightness, shadows included, smoothly over the clip.
  That looks like light added in the scene (voxel GI or ambient light still settling while the
  world runs during the steps), which the eye's adaptation hid before the lock. Open (CoreWeave,
  with the KCD look).

**B3. An exposure lock with a floor.** Cyberpunk's forced exposure stops at about 61-64 whatever
the value, so places that auto-exposure makes darker come out 9-14 levels too bright (Kabuki,
Badlands, 2026-11-23, `probes/exposure_range.py`); `ForcedPreExposure` hardly moves the frame
(open).

**B4. An upscaler or overhaul that meters each view.** DLSS 5's automatic white point moved
1.10x-2.00x across 8 views of one instant: held per take (`lock_white_point`, all three games).

**B5. Wrong colours.** Red and blue swapped in saved frames (ReShade hands over the swap chain's
BGRA): `verify`'s colour check against a screen grab (fixed 2026-11-20).

**B6. Grading twice.** An overhaul with its own tonemapping plus a ReShade grade: never stack
them; judge with `preset_ab.py`/`compare_sheets.py`.

### C. Effects that differ per camera

Lens flares, chromatic aberration and edge fringing, vignette, depth of field, motion blur, film
grain, screen-space reflections, ambient occlusion and GI, local tone mapping. A real rig's
cameras would agree on any point they all see.
Check: `vignette_check.py --game` (the same patch at the centre and near each corner);
`compare_sheets.py` (two cameras of one instant side by side); `sweep_flicker.py` map; look at the
corners and around bright lights.
Games: Cyberpunk turns grain, chromatic aberration, depth of field, lens flares, motion blur and
vignette off (read back when a session opens); `vignette_check.py`: 0.93-1.08 (Kabuki, 2026-11-24).
GTA V: NaturalVision Enhanced's lens effects, fringing and screen-space occlusion off. RDR2: the
same patch of road comes out 0.57/0.20 of its centre brightness near the top/bottom corners in haze,
0.29/0.56 in sun, with Reality Redemption 2 off and with no ReShade effect at all: something in
the game's renderer makes a point darker toward the frame's edges depending on its surroundings,
like a local tone mapper (the exposure itself holds); not its HDR setting (open: ambient occlusion,
volumetric and screen-space shadow settings one at a time). Its motion blur is also on (open). Its ReShade
preset also still runs ChromaticAberration.fx and FakeHDR.fx, and Reality Redemption 2 is
screen-space ray tracing (GI, AO, reflections, shadows).

### D. Temporal rendering and noise

**D1. History not settled after a camera cut.** TAA, DLSS/DLAA, ray reconstruction and path
tracing carry history; a shot taken too soon after a cut is still changing.
Check: the game's settle probe (difference to the settled picture every N frames); in
`hold_step_check.py`, `within_step_diff` (two captures a few frames apart after the same cut);
`sweep_flicker.py` brightness jitter with two settle values.
Games: RDR2 40 ticks, GTA V 40 frames, Cyberpunk path traced 120 frames. GTA V Enhanced's Vinewood
sweep at 80 frames: brightness jitter 0.43 to 0.054 (open: make it the default).

**D2. Renderer noise.** Path tracing and ray reconstruction differ from frame to frame.
Check: held spread map (uniform faint), `sweep_flicker.py`, `within_step_diff`.
Games: Cyberpunk averages frames per shot: 4 (sweep roughness 4.80 to 4.38 with the other fixes,
2026-11-22), 8 since 2026-11-24 (Badlands between clip frames: roughness 0.54/0.44 to 0.46/0.30,
brightness jitter 0.05 to 0.02). The Witcher 3 with ray reconstruction: 16% of pixels with a
spread over 4 across 16 frames, 6.4% with the game's own denoiser (PC session, 2026-11-23). GTA V:
faint noise in ray-traced reflections on marble at Vinewood (D1).

**D3. History or shadows that change after a time step.** A shadow or occluded area goes dark or
light for one clip frame, or switches once.
Check: `temporal_flicker.py` pops and map, then `clip_strip.py --crop` on the pop's box.
Games: RDR2 Saint Denis: a house's gable sunlit in some clip frames and in shade in others; with
the clock at 30x at frames 3, 11 and 13, at real time once (clip frame 3) in 2 of 4 takes, with 3
pre-roll steps before clip frame 1 (`preroll_steps`, capture/runner.py) in 0 of 2 (2026-11-24).
GTA V Vinewood: palm fronds' shadows on a wall differ for one clip frame and come back (wind, A6;
open).

**D4. History carried between cameras.** An upscaler's edit cache or frame generation reuses
another view's frame: OptiScaler's edit cache off, frame generation off (all games).

**D5. Aliasing.** Edges and far detail crawl. Check what anti-aliasing the game really runs on the
machine: on Linux GTA V Enhanced runs DLSS (DLAA, nvngx_dlss loaded, sharpening 0.8) and its far
background still aliases slightly at Legion Square (open: sharpening 0, or 3840x2160 scaled
down); RDR2 runs DLSS Quality (no DLAA without OptiScaler's ratio override).

### E. Scene consistency: people, objects, detail

**E1. The population system spawning and despawning in a held world.** People appear and vanish
within one instant.
Check: a census over thousands of held frames (`hold_step_check.py`'s census with a long held
phase, or the game's entities command).
Games: GTA V: 7 gone and 9 new within 60 m over 3,000 frozen frames; nothing with the population
multipliers at 0 (2026-11-21).

**E2. People and vehicles vanishing or popping in between clip frames.**
Check: `hold_step_check.py` census (by position; ids are not stable in every game);
`temporal_flicker.py` pops (`--size 960x540` for small far people).
Games: GTA V, 2026-11-23: with the multipliers at 0 the game still removed 5 people and 2 cars
within 150 m over 30 steps at Vinewood (50-130 m out). The session now makes everyone within
`keep_radius` (150 m) its own for the take (command `keep`) and gives them back at the end: 0
people gone, 1 car at the 150 m edge; the Vinewood retake has no person popping.

**E3. People gliding or jumping.** Feet slide, walks do not match the ground speed, or poses jump
between clip frames: movement and animation on different clocks.
Check: watch the moving camera's video; `clip_strip.py` on a walker over 15 clip frames (about half
a stride at a normal walk).
Games: Cyberpunk at Kabuki (people gliding in sync, a leg jumping at Badlands): the real-time clock
time-lapse (A4), fixed with it.

**E4. People reacting to the hidden player.** People step around, stop, look at or greet the
spot where the invisible player stands; the rule is that the player does not exist for the scene
(AGENTS.md section 1).
Check: the path of someone walking toward the player's spot over steps, with the player hidden
three ways (`adapters/witcher3/probes/npc_watch_probe.py`: closest approach, sideways stray).
Games: RDR2 and GTA V park the player 10 m above the spot, ghosted; Cyberpunk 12 m under the
ground. The Witcher 3 drops a teleported player to the ground and with all collisions off he falls
through the world, so he stays in place as a ghost (gameplay visibility off, character collisions
off, his horse the same); parked 80 m away he took the crowd with him (59 to 7 people within 15 m).
With him hidden but solid no walker came closer than 1.05 m and two walked around him; as a ghost
one walked straight through his spot (0.13 m); 8 trials, a direction rather than a number (PC
session, 2026-11-24). Kingdom Come: Deliverance hides the player, turns off his physics and uses the
developers' invisibility command: both walkers in the trials went straight through his spot.

**E5. Level of detail switching.** Tree shapes, far geometry or a billboard pop between detail
levels from clip frame to clip frame.
Check: `temporal_flicker.py` pops and map on the far background (`--size 960x540`); the held spread
map (detail does not switch in a held world).
Games: GTA V Vinewood: the pops found were palm shadows (D3) rather than detail switching (open).

**E6. Things missing from part of a take.** Grass or props not generated, or streamed in late.
Check: watch the sweep's start against its end; `sweep_flicker.py` worst poses.
Games: The Witcher 3 at Mulbrydale had no grass in poses 0-71: a stray Enter opened the map (a
menu that pauses the world) before the teleport; the adapter now closes menus before teleports
and freezes (PC session, 2026-11-23). Kingdom Come: Deliverance at Rattay pillory (the ring and
near sweep of 2026-11-23, measured 2026-11-24): the grass patch where the player stood is short and
flat in clip frame 1 and through the whole near sweep, and stands at full height from clip frame 2
(`clip_strip.py` on ring_01; `first_step_ratio` 3.5-4.8 on the five ring cameras that see it,
1.4-2.3 on the three that do not): his body pressed it down until the ghost command took his
physics away, five frames before the hold, and grass moves on game time only. The world now runs 2 s
after he becomes a ghost before it is held (`ghost_run_s`): the retaken ring has the grass up in clip
frame 1 and first steps of 0.79-1.27. All games: people stream in for tens of seconds after a
teleport (`populate_s`).

**E7. People inside cameras, or deleted when a script owns them.** The obstacle policy deletes
people and vehicles in cameras at the start of a take, never what a game script owns, and retakes
when a camera ends up inside one (`tests/test_obstacle_policy.py`). RDR2's first sweep passed
through a horse's neck (2026-11-20). Someone close in front of a lens is not inside it but fills the
picture (`npc_tracks.py`'s close_to_camera: Cyberpunk's Kabuki clip, a walker 1.0-1.5 m from two
cameras for half the clip, QC round 3): an adapter may set `obstacle_front_m` (Cyberpunk 1.5) to
delete people standing that near in front of a camera, inside its view, at the start of a take.

**E8. The player in the picture, or affecting the scene.** Visible, its collision or AI still
active. Parked out of sight with streaming kept at the spot; check the "subject visible" health
problem. Parking side effects: under water at Northside docks Cyberpunk's camera parent drifted
8.7 mm, which a recovery now corrects (pose check, F3).

### F. Things on screen and the frame itself

**F1. The HUD and mod overlays.** Hide the HUD every frame if the game redraws it; turn mod
overlays off at install (ReShade, CET, OptiScaler toasts, trainers). Nothing detects a small
overlay. The Witcher 3's debug console slides shut over 0.2 s after a command: nothing is captured
sooner than 0.45 s after one; and when the key that closes it is lost (Linux, 2026-11-24: one shot
of a 345-pose near sweep at Crookback Bog had the console over its top quarter, a dark frame in the
sweep: `sweep_flicker.py` brightness jitter 1.52 against 0.04 elsewhere), `capture()` now finds its
green echo in the shot (`session.console_in`) and the shot is taken again after `recover()` closes
it. Kingdom Come: Deliverance takes commands through its console too: the
session checks a frame for the open console (a solid black line at half height) and recovers when
it is out of step; anything else typing into the game while a worker runs breaks this (a probe
did once and failed a near sweep).

**F2. Menus, pause and loading screens.** `capture/checks.py` flags grey pause screens by
saturation (121 of 130 in the take of 2026-11-20); the adapters close menus with Esc and report
them as health problems. The Witcher 3 shows a loading screen with black frames after a far
teleport: the adapter waits for streaming and black to end.

**F3. Pose and field of view.** The rendered camera must match the asked pose (Cyberpunk: 5 mm,
0.05 degrees) and FOV; FOV changes that ease over game time cannot arrive in a held world
(Cyberpunk renders at the widest FOV and crops). Window client size 16:9 at the capture size
(other ratios letterbox).
