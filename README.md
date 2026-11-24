# capture_mod

Captures a camera rig (`camrig/v1` cameras around a subject) inside a running game: the world
is held at exactly one instant across every view, stepped by exactly 1/fps between instants,
and the result is packaged in the camera-rig repository's delivery layout. Rig formats are
pluggable providers (`rigs/`). Games: Red Dead Redemption 2, GTA V Enhanced, Cyberpunk 2077 and
The Witcher 3, all in story mode (GTA V Legacy still works but is dropped: see GTA V adapter).

```
capture/            game-agnostic: rig sources, the scene, placement, shot lists, the take loop,
                    per-shot checks, packaging, sheets, locations, the job queue, the worker, the CLI
capture/install/    game-agnostic installer: steps, where mod files come from, and the components
                    every game shares (ReShade, our capture add-on, optional OptiScaler)
addons/capture/     our ReShade add-on that saves frames (game-agnostic)
rigs/               rig providers, one file per rig format (rigs/README.md has the contract)
third_party/        the camera-rig repository as an optional git submodule (for the camrigs provider)
adapters/common/    what adapters share, tied to no game: the game window (focus, keys, grabs, size),
                    process memory, RedLua (the job loader script and the session client), a
                    session typed into a game's debug console (console.py), frames asked of the
                    capture add-on (frames.py)
adapters/rdr2/      everything RDR2: the adapter, its install plan and mod lockfile, visual set, ray
                    tracing, Lua jobs, launch and recovery scripts, the render camera writer, probes
adapters/gtav/      everything GTA V, both editions: the adapter, the install plans (install.py,
                    install_enhanced.py) and lockfile, the unattended launcher, the freeze
                    (timestep.py), the session job, probes
adapters/cyberpunk/ everything Cyberpunk 2077: the adapter, the loader mod for Cyber Engine Tweaks, the
                    session job, install plan and lockfile, game settings, launcher, probes
adapters/witcher3/  everything The Witcher 3: the adapter, the session script (WitcherScript) and its
                    console client, install plan, game settings, launcher, probes
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
commands take `gtave` for GTA V Enhanced, `cyberpunk` for Cyberpunk 2077 and `witcher3` for The
Witcher 3 (see their adapter sections; `gtav`, Legacy, is dropped).

The RDR2 default (since 2026-11-20) is the full capture setup: Direct3D 12, a 2560x1440 window,
the visual set's ReShade preset, ray tracing (Reality Redemption 2) and DLSS 5 (OptiScaler, which
needs your `nvngx_dlssnr.dll`; skin structure 2, over DLAA since 2026-11-22). `--no-ray-tracing`,
`--no-optiscaler`, `--no-preset`, `--dlss-mode quality`,
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
  **DLAA** (`--dlss-mode`, default `dlaa` since 2026-11-22, Nathan): the game's own DLSS modes stay
  at Quality (`dlssQuality` 2: on Direct3D 12 the game once wrote 5 and then never created a DLSS
  feature), and OptiScaler answers the game's render-size query with a ratio of 1.0 for Quality
  (`[QualityOverrides] QualityRatioOverrideEnabled=true`, `QualityRatioQuality=1.0`), so the game
  renders the full 2560x1440 and DLSS 5's guides are full size (OptiScaler's log: "Render
  Resolution: 2560x1440 ... Quality: 2", "guides 2560x1440"; Quality rendered 1706x960). The frame
  rate stays at the game's usual cap of about 60 frames/s. `--dlss-mode quality` goes back.
  **Skin structure 2** (DLSS 5's skin control, as in GTA V Enhanced; Nathan, 2026-11-22, after the
  sweep below), written to OptiScaler.ini.
  **The white point held per take** (adapter setting `lock_white_point`, on; 2026-11-22, as in GTA
  V Enhanced): with the game's exposure locked, DLSS 5's automatic white point still metered each
  view (logged paper white 1-232x over one frozen run in Saint Denis), and a view shot 40 ticks
  after the sky came out 1.4 levels brighter than settled (mean change 5.2, p99 40), after a dark
  view 0.05 (`tools/exposure_check.py`). Held from the first shot (`adapters/common/optiscaler_live.py`),
  the same view came out 0.4 brighter 40 ticks after the sky and after the dark view alike (the
  settle), and within 0.01 settled; no white point change was logged during the take.
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
  DLSS 5's skin controls (`tools/dlss5_skin_sweep.py --game rdr2`, as for GTA V Enhanced below;
  OptiScaler's menu has the same layout here, its DLSS 5 page and "Model tuning" expanded by hand
  once per game start) at Saint Denis, 14:00, sunny, Direct3D 12, 2026-11-22
  (`out/checks/upscaler_ab/rdr2_skin_sweep/`, `skin_faces_large.jpg`): smaller than in GTA V. In
  four face regions skin structure 0, 0.5 and 2 differ from the default (-1) by 2.0-3.2 levels of
  255, against 1.6-2.7 for skin 1 (which matches the default, as in GTA V). The default makes one
  face warmer and blotchy orange (red minus blue 27.6, against 24-25 at 0, 0.5 and 2); 0 and 0.5
  smooth skin; 2 keeps the even tone and adds wrinkle and pore detail. Nathan picked 2, which the
  install now sets. DLSS 5 off to on with DLAA and skin 2, same place
  (`out/checks/upscaler_ab/rdr2_dlaa_skin2/`): mean change 2.0-6.2 levels of 255 per view.
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

### On Linux (a Windows game under Proton)

The same command line runs on a Linux machine with an NVIDIA GPU and no desktop (`./capture.sh`
is `capture.ps1`'s twin): the game is the Windows one, under Proton in the Steam Linux Runtime
container, on a headless X display, and our in-game parts are the same files. Nothing needs root.
Cyberpunk 2077 and RDR2 pass `verify` and capture there (their sections below have the numbers);
GTA V Enhanced installs. Found and measured on CoreWeave Slurm nodes, 2026-11-23 (Ubuntu 22.04
image, NVIDIA 580.105.08 and 580.178.04, RTX PRO 6000; docs/LINUX_PORT.md).

```bash
./capture.sh host status                 # GPU and driver, Proton, its runtime, the display tools, NGX, ffmpeg
./capture.sh host setup                  # fetches, unpacks and builds what is missing into out/host (pinned: capture/host/linux.lock.json)
#   (its NVIDIA download and its build of wow64/tls32.c ran as written; Proton, the runtime and the display tools
#    were fetched by hand on 2026-11-23 and the command written from that: BACKLOG)
#   ...the game's Windows files into out/games/<game> (below), and a mods bundle from a Windows machine
./capture.sh install cyberpunk --mods capture-mods-cyberpunk.zip --dry-run
./capture.sh install cyberpunk --mods capture-mods-cyberpunk.zip
./capture.sh host prefix cyberpunk       # makes the game's Proton prefix; prints where saves and settings go
./capture.sh verify cyberpunk --launch   # as on Windows; then scout, submit, worker
# a game that only starts through a Steam client (RDR2, GTA V: Rockstar's launcher), once per prefix:
./capture.sh host steam rdr2 --client steam_client_windows.zip   # the Windows client into the prefix, its service, the game in its library
srun --exact --gres=gpu:1 -c 6 ./capture.sh host steam rdr2 --keep &   # the client, kept running, in a job step with one GPU
#   ...the owner signs in once in its window (and in Rockstar's launcher), through a remote view of the display
```

- **What differs is in one place.** `capture/host` (game-agnostic) answers what the rest asks of
  the machine: the game's processes, starting and stopping it, the game user's folders, and a path
  of this machine as the game sees it (drive `Z:`; `C:` inside the game's own prefix,
  `out/proton/<game>`). `adapters/common/window.py` and `mem.py` pick their Windows or Linux
  implementation (`window_x11.py`: xdotool and an X screen grab; `mem_linux.py`: `/proc/<pid>/mem`,
  same addresses as on Windows). An adapter's code is the same on both; what a game adds for Linux
  is its DLL overrides for Wine and where its files are.
- **Our two plug-ins come built.** The capture add-on and the clock plug-in are Windows DLLs; a
  Linux machine has no tools to build them. `capture mods bundle <game> [--with-supplied]` on a
  Windows machine that built them puts both in the bundle with a stamp of the sources they were
  built from, and `install --mods <bundle>` uses them when the stamp matches this checkout
  (line ends do not matter).
- **Ordinary programs come from one conda environment.** ffmpeg (and anything else of that kind a
  machine lacks) is looked for in `~/.conda/envs/game-capture` (`CAPTURE_ENV` or `host.env` in
  `out/config.json` name another) and run by its path, without activating the environment;
  `host setup` installs it there from conda-forge when none is found. Python stays with uv
  (`capture.sh`). Xvfb and xdotool are still the unpacked Ubuntu packages in `out/host/sysroot`.
- **The game's files** are not installed by Steam there (its client is a 32-bit program; the
  image had no 32-bit libraries). They were downloaded with DepotDownloader (SteamRE, a third-party
  tool, with the owner's own Steam login) for the Windows platform, pinned to the build the script
  layer supports: `-app 1091500 -depot 1091501 -manifest 3524634124112875626 -os windows`, 66.8 GB.
  A clean download plus `capture install` is the PC's install (all 155 depot files compared).
- **The game user's files** (saves; for Cyberpunk also `user.gls`, without which the first start
  stops at the user agreement) are copied by hand into the prefix's `Saved Games` folder
  (`host prefix` prints it). A game writes its settings file only when it exits by itself: start it
  once, close it (`python -m adapters.cyberpunk.launch`, then `--close`), and run `install` again
  for the settings step. A killed game writes none.
- **The display** is Xvfb at 2560x1440 (config `host.screen`): the game presents to it through
  NVIDIA's Vulkan driver and a grab of it shows the game. It is the game's alone, so nothing takes
  the window's focus. Where `/usr/bin/xkbcomp` is missing and cannot be installed, Xvfb is started
  in a private mount namespace that has it.
- **DLSS** needs NVIDIA's `nvngx.dll` and `_nvngx.dll` (from the driver package of the machine's
  driver version) in the prefix, and a registry value; `host setup` and the first start do both.
  DLSS 5 through OptiScaler is not tried there: it needs a newer driver than 580.
- **One GPU per game.** A game that sees several GPUs finds no display modes (Cyberpunk 2077 on
  a job with four: an empty resolution list, "Resolution is nil", its window at 320,180;
  2026-11-23). `capture/host` refuses to start one then. Under Slurm a job step gives one:
  `srun --exact --gres=gpu:1 -c 5 ./capture.sh worker --game cyberpunk`, and `CAPTURE_DISPLAY=:100`
  gives a second game its own display.
- **A Steam client for the games that need one.** Rockstar's launcher starts a Steam copy only
  with a Steam client running (without one it offers BUY NOW), and Proton's stand-in for the
  client needs the Linux one. `capture host steam <game>` puts the Windows client into the game's
  prefix (its files from a Windows machine's Steam folder without steamapps, userdata and config),
  installs its service, and links the downloaded game folder into its library with an app
  manifest written from the game's `STEAM` facts, so nothing is downloaded again. That client and
  the games it starts run through Wine itself (`host.wine_direct`: the environment Proton gives a
  game, `PROTON_DISABLE_LSTEAMCLIENT=1` so that Proton's Wine does not treat the real
  `steamclient64.dll` as its stand-in). RDR2 and GTA V share one prefix (`out/proton/rockstar`:
  one launcher, one sign-in each for Steam and Rockstar, remembered there). A game's own DLL
  overrides are per exe in the prefix's registry (an install step), since a game started by Steam
  does not get our environment. Seen on the way: Steam shows the game's EULA once; its first-time
  setup runs DXSETUP; Rockstar's launcher refuses a machine without a sound device ("Sound card
  check failed": `capture/host/alsa_null.conf` gives ALSA a silent default one); both games throw
  the settings file away when it names another graphics card (an install step writes this
  machine's); the client ends itself when a game it started is killed (`--keep` starts it again).
- **32-bit Windows programs where 32-bit system calls are forbidden.** The CoreWeave containers
  kill every `int $0x80` call (seccomp), and Wine sets each thread's 32-bit `%fs` segment with
  one (`set_thread_area`; the 64-bit table has none). So the Linux Steam client cannot run there
  at all, and under Wine no 32-bit program started: Steam's service (`bin\SteamService.exe`),
  DirectX's and Visual C++'s installers. `capture/host/wow64/tls32.c` is preloaded into Wine and
  replaces that one function: a short-lived child sets the thread's descriptor through ptrace
  (`PTRACE_SET_THREAD_AREA`), with `WINEARCH=wow64` so that 32-bit programs run in 64-bit
  processes. No forbidden call is made; it is still a way around a restriction of the cluster,
  which its owner should know about. Proton's own script cannot be used for such programs: its
  `files/bin/wine` starts the 32-bit preloader first and dies the same way.
- **A remote view for the sign-ins.** x11vnc on the game's display behind noVNC
  (`http://localhost:6080/vnc.html` through the editor's port forwarding, with a password); set
  up by hand on 2026-11-23 from Ubuntu's packages unpacked into `out/host/sysroot` (BACKLOG).
- **Not there yet:** GTA V Enhanced's start and capture (its launch code is ported, not run), The
  Witcher 3 (its exe starts under Proton; the adapter is being written on Windows), the scout
  overlay, `tools/` that press keys, and a download of the game's files by the
  command line. BACKLOG.md has the list.

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

# 3. worker: claim jobs, and wait for more when there are none (it does not exit; --once: one
#    job, then exit). One worker per game instance: two workers on one PC drive the same game
#    at once and spoil each other's takes (2026-11-23).
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
    capture_log.jsonl  per shot: clip frame, file, health, picture stats, rendered camera, game timer, attempts
                       (the adapter's own fields beside them; one with a name the take uses gets "adapter_")
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
file fresh. A claim whose lease is 15 minutes old is requeued (`capture queue requeue <job>`, or
`--all` for every such claim, and every worker on start). If the game goes away mid-take (a script fault closes it, a graphics
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

## Checking what a capture looks like

`docs/VISUAL_CHECKS.md` lists every visual and scene-consistency fault found so far (rendering:
noise, exposure, per-camera effects, temporal history; scene: a held instant that creeps, people
vanishing, gliding or reacting to the hidden player, cloth vibrating, detail popping, screens and
skies time-lapsing between clip frames), how to check each with a number, and how each game fixes
it. Its game-agnostic tools: `tools/hold_step_check.py` (live: held repeats, 1/fps steps, exposure
drift, a census of people), `tools/temporal_flicker.py` (a take's cameras over clip frames: flicker,
pops, exposure drift), `tools/sweep_flicker.py`, `tools/vignette_check.py` (live: the same patch at
the centre and near the corners), `tools/exposure_check.py`, `tools/clip_strip.py`.

## Adding a game

`AGENTS.md` is the full workflow (what a capture must be, what a finished game provides, the
order to build and prove it in, and the problems every game has had). In short:

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
- **Portable** (Nathan, 2026-11-22): an adapter is done only when a clean-slate install runs from
  the CLI, as RDR2's did: mod files moved out of the game folder, a plain `capture install <game>`,
  then `capture verify <game> --launch`, at least on the same machine, with nothing set up by hand.
  `capture mods bundle <game> --with-supplied` carries the files to another machine. Keep
  operating-system calls in the shared layers so the same works on another operating system once
  the repository is set up for one (`docs/LINUX_PORT.md`). Cyberpunk 2077 had its clean-slate run
  on Linux (2026-11-23); GTA V Enhanced has not had one yet (`AGENTS.md`, section 9).

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
  unchanged across the shots of a clip frame. The game's clock of day runs 30 times real time
  (2000 ms per game minute), so each step moved the sky and its light by a second and frames drifted
  3-11% over 30 clip frames; takes run it at real time (`clock_ms_per_minute` 60000, given back
  after): 0.1-0.7% (2026-11-24, docs/VISUAL_CHECKS.md A5). A take steps 3 times before clip frame 1
  (`preroll_steps`): shadows switched once on the first steps (D3).
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

### On Linux (measured 2026-11-23)

The same adapter, Lua and session job run under Proton on a headless display ("On Linux" under
Install), started by a Steam client that lives in the game's prefix. On a CoreWeave node (RTX PRO
6000, driver 580.178.04, GE-Proton11-12), from a clean slate: the game's depot download (128.5 GB,
the PC's build), `capture install rdr2 --mods <the PC's bundle> --no-optiscaler` (127 steps, then
nothing to do), the PC's saves and settings file copied in, `capture host steam rdr2`, the two
sign-ins. Then:

- `capture verify rdr2` passes: 60 to 64 frames/s at 2560x1440, a frame through the add-on
  (difference to a screen grab 0.6, with red and blue swapped 11.9), a frozen take of 8 cameras
  over 3 clip frames (24 shots in 54 s, none recaptured, the two 1/30 s steps within 2.18 ms) and
  its packaging. So the photo-mode freeze, the render camera written into the game's memory
  (`/proc/<pid>/mem`) and the exposure lock work there as they are.
- Start with nobody at the keyboard (`adapters/rdr2/launch.py`): Steam's request to the loader's
  heartbeat in 296 s (the game's window after 125 s; game and prefix on a network file system).
- Six takes by the worker, none with a recaptured shot: at the Lakeshore, in Saint Denis and in
  Rhodes a 345-pose near sweep (4.0, 5.1 and 5.5 min; 0.58 to 0.84 s per shot) and 30 clip frames
  of a moving and two fixed cameras (89 shots; 1.8 to 2.2 min). Saint Denis's sweep was taken
  three times: twice a camera stood inside something a game script owns (the obstacle policy).
- Different from the PC: no DLSS 5 (driver 580), so the game's own DLSS at Quality instead of
  DLAA through OptiScaler; Reality Redemption 2 loads, its picture was not compared.

### Research probes

`adapters/rdr2/probes/` holds the tools the method was found with (memory scans, the frozen
orbit, geometry and step checks). They are not part of the pipeline.

## GTA V adapter (Legacy and Enhanced)

GTA V Legacy (`gtav`: Steam app 271590, Direct3D 11, game build 1.0.3889.0) and GTA V Enhanced
(`gtave`: Steam app 3240220, Direct3D 12 with ray tracing, build 1.0.1158.13), story mode only.
Both run the same adapter, session script and freeze; what differs is under "GTA V Enhanced" below.

**Legacy is dropped** (Nathan, 2026-11-22): GTA V Enhanced is the GTA V capture target. `gtav`
still installs and runs as described here (Enhanced builds on its plan and adapter), but nothing
more is planned for it: no visual set, no DLSS 5, no further checks.

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
.\capture.ps1 install gtave --mods "C:\...\Grand Theft Auto V Enhanced" --dlss-nr "C:\...\nvngx_dlssnr.dll"
#   NaturalVision Enhanced, ray tracing and DLSS 5 (skin structure 2, DLAA) by default, no ReShade effects
#   (NVE's archive in out/mods or a --mods folder)
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
  OptiScaler hooks. The game's DLSS mode is pinned too (below: DLAA, so it renders the full
  2560x1440); DLSS 5 then runs on every 2560x1440 frame (2.2 ms). The game's DLSS sharpening
  (`dlssSharpen`) is pinned at 0.8, this machine's value, though DLSS itself is not asked to
  sharpen (OptiScaler logs SharpenEnabled false). Verify passes with it on. Measured in Quality
  mode (1706x960 in): `tools/upscaler_ab.py --game gtave` at
  Vinewood: off to on, mean FLIP 0.16 to 0.21 (RDR2: about 0.055), largest on faces and clothes;
  settle after a cut and the same pose twice are about as with it off (40 frames: 1.58 against
  1.45; twice: 0.87 against 0.66). OptiScaler's ini cannot be saved from its menu while the game
  runs (the folder lock); the install sets it beforehand.
- **DLAA, not Quality** (Nathan asked for the better of the two, 2026-11-22; `--dlss-mode`, default
  `dlaa`). The game's menu offers Quality, DLAA, Performance and Balanced; settings.xml
  `dlssQuality` holds them as 2, 3, 0, 1 (the menu's order, not NVIDIA's numbers: the game passes
  DLAA on as NVIDIA's 5, and a 5 in the file is reset to 2 at start). With DLAA the game renders
  2560x1440 and DLSS 5's depth and motion guides are full size as well (OptiScaler's log: guides
  2560x1440, against 1707x960 in Quality); the model takes DLAA (its own ratios list DLAA 1.0).
  `tools/preset_ab.py --game gtave --dlss-modes quality,dlaa --with-dlss5` at Vinewood, 14:00, 13
  views, one frozen instant (`out/checks/preset_ab/20261122_132123_gtave_dlss_modes/`): DLAA has
  more fine detail in every view (mean absolute Laplacian of the luma +4% to +16%, +7% on average,
  with DLSS 5 on or off); eyelids, lashes and window frames lose their stair-steps and skin pores
  are sharper; mean FLIP Quality to DLAA 0.047 with DLSS 5, 0.036 without. Frame rate is about the
  same (88-98 frames/s against 76-97 at three views; DLSS 5 dominates the frame time).
- **DLSS 5's white point held per take** (adapter setting `lock_white_point`, on; 2026-11-22). The
  install leaves the fork's white point on automatic (`WhitePointSource=3`), which meters every
  frame like an auto-exposure: over one frozen run at Vinewood the logged paper white went
  0.29-1.41x (261 changes in two minutes), and one view shot six times at one instant came out at
  102.3-104.7 mean luma, unrelated to the view before (`tools/exposure_check.py`). The adapter now
  holds the value the meter settled on for a take's first shot (`adapters/common/optiscaler_live.py`,
  from the Cyberpunk adapter: `WhitePointSource=0` and `WhitePointScale` written live through
  `dlssnr-set.txt`, which works despite Enhanced's folder lock) and releases it when the take ends;
  take.json records it under `render.dlss5`. With it the same check gave 102.01-102.06 settled and
  102.59-102.66 40 frames after a cut from the brightest or the darkest view alike (the settle,
  not the white point), and no white point change was logged between the first and the last shot.
- **DLSS 5's skin controls** (`tools/dlss5_skin_sweep.py`): Skin structure (-1, the default, follows
  local structure; 0 and above set skin on its own) and Auto skin mask (the model finds skin
  itself). OptiScaler's live settings file does not take them (only Passes, Style, PreSr), so the
  tool sets them through OptiScaler's menu, live, and runs `upscaler_ab.py` with them as variants.
  Vinewood, 14:00, one frozen instant: only skin changes (difference maps light faces and heads,
  nothing else). Skin structure 0 makes skin smoother and slightly lighter, nearer the game's own;
  2 adds pore and edge detail. In the portrait's face region the mean difference to the default is
  3.2 at 0, 2.1 at 0.5, 1.0 at 1 (the same as the default), 1.8 at 2, against about 0.9 between
  two shots of one pose. Auto skin mask off changes nothing at the default, where skin already
  follows the rest of the frame. Nathan picked skin structure 2 (2026-11-21): Enhanced's install
  sets it in OptiScaler.ini with `--optiscaler` (`optiscaler_settings` in install_enhanced.py).
- **Ray tracing switched live** (`settings_menu.py`, adapter capability `ray_tracing_switch`): the
  game applies "Enable Ray Tracing" from its pause menu without a restart, also while frozen, so
  `tools/preset_ab.py --game gtave --with-dlss5` compares neither / ray tracing / DLSS 5 / both at
  one frozen instant, as for RDR2. The adapter presses the keys, checks each step on screen (the
  lit tab and row, the list moving, "Apply Changes" appearing), confirms the result in
  settings.xml, and freezes the world again afterwards. Keys are sometimes dropped, so each one is
  confirmed before the next. Scripts do not run while the pause menu is open. About 25 s per
  switch. Vinewood at 14:00, extra sunny, 13 views: mean FLIP 0.172 for ray tracing, 0.174 for
  DLSS 5 over it, 0.259 for both (RDR2's Saint Denis: 0.055, 0.054, 0.069). The DLSS mode switches
  the same way (capability `dlss_mode_switch`, `set_dlss_mode`, `preset_ab.py --dlss-modes`): 19
  entries down, Right steps through the modes; its place was counted with ray tracing on, so the
  switch refuses with it off.
- **The capture default** (Nathan, 2026-11-21): NaturalVision Enhanced (`--graphics-mod`), the
  game's ray tracing and DLSS 5 (`--optiscaler`, skin structure 2, over the game's DLSS in DLAA
  mode since 2026-11-22), with no ReShade effects on top
  and the game's motion blur off. `capture install gtave` installs all of it; `--no-graphics-mod`,
  `--no-optiscaler` and `--preset` change it. Before NVE the default was the grade + Clarity
  preset; with NVE that would grade twice (NVE has its own tonemapping and day and night
  grading), so it went. Measured before that, with ray tracing and DLSS 5 on (Vinewood, 14:00, 13
  views, one frozen instant): mean FLIP 0.142 for the grade, 0.058 for Clarity on top of it, 0.096
  for MXAO and SSR on top of that. MXAO and SSR were never in the default: they double the
  ray-traced occlusion and reflections and depend on each camera's view.
- **Visual presets** (`--preset`, off by default; `adapters/gtav/visual/`,
  shaders pinned in the lockfile): F14 no effects, F15 the capture preset (the colour grade, qUINT
  Lightroom: contrast, softer highlights, saturation down, vibrance up, slightly cooler, plus
  AstrayFX Clarity for local contrast), F16 the grade plus screen-space MXAO, SSR and Clarity,
  F17 the depth buffer, F18 the grade alone. `--no-preset` goes back to no effects and leaves the
  presets on their keys. `tools/preset_ab.py --game gtave --presets
  plain:F14,grade:F15,grade_ss:F16 --with-dlss5 --restore F15` compares them at one frozen instant.
  Measured (Vinewood, 14:00, extra sunny, ray tracing on, 13 views): mean FLIP 0.14 for the grade,
  0.13 for the screen-space effects on top of it, with DLSS 5 off or on alike, and 0.18 for DLSS 5
  over all of it. The depth buffer reads right (reversed, not upside down, at the DLSS render
  size). Screen-space caveats: SSR puts glossy reflections on dry pavement and assumes one field
  of view (60 degrees here) for every camera; MXAO darkens edges by what each camera sees. prod80's
  colour effects were left out: they need noise textures and dither differently every frame.
- **NaturalVision Enhanced** (the default since 2026-11-21): free from razedmods.com (GoFile/
  PixelDrain links). The July 2026 build ("#2 Updated", 6.5 GB) is pinned: the latest (#3 V2, Nov
  2026) hangs build 1158.13 on "Initializing". It ships its own ASI loader (`xinput1_4.dll`),
  ReShade 6.7.3 with its own ReShade.ini, NVE.asi (a ReShade add-on that replaces 95 of the game's
  shaders, loaded from NVE.bin), the `onigiri` loader with its DLC packs, and photo-mode effects.
  The install copies only NVE's own 110 files straight from the archive
  (`capture/install/components/pack.py`: streamed and hashed, the archive left as downloaded); ours
  stay, and none overwrites a game file. NVE's ReShade effects are optional extras (colour presets,
  photo frames, experimental volumetric clouds), not part of its look. Off vs on at Vinewood (two
  starts, people and traffic cleared, same views): mean FLIP about 0.49, a different look
  throughout (darker, more contrast, cooler, a deeper blue sky). `tools/preset_ab.py
  --clear-people M` is what makes two starts comparable.
- **NVE's per-camera effects off.** NVE keeps its settings in `%APPDATA%\NVE\settings-gen9.json`
  (outside the locked game folder; read at start, written back on exit); its menu is a tab in
  ReShade's overlay (Home). The install turns off its lens effects (reflections and fringing
  around bright lights), lateral chromatic aberration (fringing towards the frame edges) and its
  screen-space ambient occlusion (VBAO; off in this build's defaults, on in a file a newer build
  left behind, and the ray tracing already does the occlusion): each depends on where a camera
  points, so neighbouring views would disagree. A settings file holding only these keys works on a
  fresh machine: NVE fills in its own defaults around them (checked 2026-11-21). Against the first
  NVE run (Vinewood, 14:00, 10 views, two starts; `out/checks/nve_default/`): mean FLIP 0.09,
  mostly foliage and shadow edges, which differ between any two starts; at the frame border the
  red and cyan fringes on window frames and wires are much reduced (the colour mismatch on strong
  edges dropped in 9 of 10 views), though some red fringing remains. Its motion blur
  setting (`mb_config`) has no label in this build, so the game's own motion blur goes to 0
  (`MotionBlurStrength`); under the freeze nothing moves anyway, and each shot waits for the
  picture to settle after the camera cut. Its day and night grading follows the clock, not the
  view. The game's auto-exposure does not re-adapt between poses while frozen (unlike Cyberpunk
  2077's, which re-adapts at every pose): `tools/exposure_check.py` at Vinewood, 14:00, shot one
  view after holding the darkest view (the sky, mean luma 82) and the brightest (the ground, 128)
  for 300 frames each. 40 frames after the cut, the view came out at 104.30 and 104.38 against
  103.41 settled. An adapting exposure would move the two in opposite directions; they moved
  together by about 1, which is the settle after a cut (DLSS and temporal history), and were back
  at 103.4 after 600 frames. So GTA V needs no exposure lock.
- **Speed.** About 158 frames/s at 2560x1440 with ray tracing at the Alamo Sea, 94 in Vinewood with
  DLSS 5; 0.30 s per shot, 0.53 s with a moving crowd.
- **Freeze**: the same minimum step, found the same way (a different address). Find it before
  freezing: at time scale 0 the value 1/3000 is copied into 321 other places.
- **A deliberate crash.** Four times in about 18 sessions (2026-11-21) the picture froze, scripts
  stopped, and about a minute later the game exited. Rockstar's crash handler wrote a dump each
  time (`%LOCALAPPDATA%\Rockstar Games\GTAV Enhanced\CrashLogs`). All four dumps fault at the same
  instruction, `GTA5_Enhanced.exe+0x13f8980`: `mov qword ptr [0], 0x621`, a crash on purpose with
  code 0x621, in code that is encrypted on disk. That makes it the game's protection, not a script
  fault. What sets it off is not known, and it is not the minimum-step write: the fourth came
  3.4 minutes after a start, before any freeze or memory write, during a teleport, the crowd and an
  obstacle scan. Each part of a take repeated alone did not set it off, and a 9.4-minute frozen
  take ran clean. The worker treats it like a closed game: a stale heartbeat ends the game and
  starts it again.

### GTA V Enhanced on Linux (measured 2026-11-23)

As RDR2 on Linux, in the same prefix (one Steam client, one Rockstar launcher). On the same
CoreWeave node, from a clean slate: the depot download (103.3 GB, the PC's build), `capture install
gtave --mods <the PC's bundle> --mods <NaturalVision's archive> --no-optiscaler` (23 steps after
the PC's user files were copied in, then nothing to do), `capture host steam gtave`. Then:

- `capture verify gtave` passes: 77 frames/s at 2560x1440, a frame through the add-on (3.0 against
  41.8 with red and blue swapped), a frozen take of 8 cameras over 3 clip frames (24 shots in
  74 s, none recaptured, both steps exact to 0.00 ms) and its packaging. So the minimum time step
  written into the game's memory (`timestep.py`) works there as it is.
- Start (`adapters/gtav/launch.py`, rewritten onto the shared window and host layers): Steam showed
  no launch-option dialog for `-applaunch`; the launcher starts `GTA5_Enhanced_BE.exe` (32-bit),
  which with `-nobattleye` starts the game; the landing page's tabs were answered as on Windows
  (E, then Enter on STORY). Steam's request to the heartbeat in 125 to 135 s.
- Takes by the worker, none with a recaptured shot: at the Alamo Sea (scouted on the node with
  `capture scout`) 30 clip frames in 2.8 min and the 345-pose near sweep in 5.8 min (0.85 s per
  shot); on Vinewood Boulevard 3.4 and 7.1 min. The solver declined Legion Square (no
  collision-free near ring). RedLua faulted in lua51.dll at the start of most sessions after the
  first (the fault described under "RedLua in GTA V"), so the worker restarted the game between
  takes.
- The game throws the PC's settings file away unless its four hardware lines are this machine's
  (BACKLOG: the game user's files), and on a display of exactly the capture size it needs
  `Windowed` 3 (an install step under Proton): set to windowed it opened 1920x1080.
- No DLSS 5 (driver 580): the game's own DLAA. NaturalVision Enhanced loads; its picture was not
  compared with the PC's.

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
  moved, appeared or went. The game's own people alone hold still without that. While the world
  steps between clip frames the multipliers at 0 still let it remove people (5 people and 2 cars
  within 150 m over 30 steps at Vinewood, 2026-11-23), so everyone within `keep_radius` (150 m) is
  made the session's own for the take (command `keep`) and given back after: none gone.
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
Not done yet: a full ST-DM take; the visual mods and DLSS 5 exist but are off by default (see
"Open" below).

### Setup

```powershell
.\capture.ps1 mods fetch cyberpunk            # Cyber Engine Tweaks, RED4ext, redscript, Codeware (GitHub, pinned)
.\capture.ps1 install cyberpunk --only mods --only scripts --only reshade --only addon --only clock --only settings   # game closed
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
  loader comes up in the main menu and loads the last save from a script, and Space ends the
  loading film, which otherwise waits on "press to continue" with the save loaded: 39 s to the
  world instead of 98 s (2026-11-22). Starting through Steam
  instead raised a Windows administrator prompt on every start (Steam's first-time setup), which
  nobody answers and which blanks every screen grab for two minutes. Started directly, Steam does
  not list the game as running: other sessions must look for `Cyberpunk2077.exe`.

### On Linux (measured 2026-11-23)

The same adapter, Lua and probes run under Proton on a headless display ("On Linux" under
Install; `adapters/cyberpunk/adapter.py` has every number). On a CoreWeave node with an RTX PRO
6000, from a clean slate: the game's depot download, `capture install cyberpunk --mods <the
PC's bundle>` (50 steps, then nothing to do), the saves copied in, one start and clean close, and
`install` again for the 11 game settings. Then:

- `capture verify cyberpunk --launch` passes: unattended start in 127 to 182 s (game and prefix
  on a network file system), scripts answer, a 2560x1440 frame through the add-on, a frozen take
  of 8 cameras over 3 clip frames (24 shots in 256 to 259 s, none recaptured, both 1/30 s steps
  exact to 0.00 ms) and its packaging into videos.
- Two queued takes at the Cherry Blossom Market, both without a health problem or a recapture:
  the near sweep (345 poses at one instant, 43.2 min, one simulation time throughout, poses
  within 0.1 mm of the Windows take's from the same solved rig, roughness 5.14 and brightness
  jitter 0.069 against 4.38 and 0.045 on Windows), and 30 clip frames of a moving and two fixed
  cameras (89 shots, 14.8 min, every step within 0.0017 ms of 1/30 s). Both were packaged
  afterwards with `capture package` (ffmpeg from the conda environment); the worker's own
  packaging and QC step has not run there.
- At Kabuki and in the Badlands the same two takes each, through the worker's own packaging
  and QC (run in a job step with one GPU): near sweeps in 43.5 and 36.6 min, the 30 clip frames
  in 14.1 min at Kabuki, none with a recaptured shot. Their exposure lock ended at its upper end
  (BACKLOG: the forced luminance has a floor).
- Speed depends on how the Slurm job asks for its CPUs: 7.28 s per shot and 17 to 18 frames/s
  with `--cpus-per-task=8` (the game ran on 4 cores), 5.59 s per shot and 28 frames/s with
  `--hint=nomultithread` added (8 cores), against 2.50 s on the PC (BACKLOG has the table).
- No DLSS 5 (driver 580), no visual set.

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
- **Time steps.** The game's frame time follows the clock our plug-in holds, so a step keeps the
  time dilation at 1 and slows that clock alone, every frame to cover an eighth of what is left
  (session command `step`): the world and everything on the real-time clock (screens, foliage,
  people's small motions) move by the same 1/30 s, steps 33.331-33.333 ms in about 70-90 frames.
  Until 2026-11-23 a step slowed only the world (a time dilation) and released the clock, which then
  moved 1.67 s per step: ads changed every clip frame, foliage thrashed, walkers moonwalked
  (docs/VISUAL_CHECKS.md A4; Badlands fixed cameras roughness 1.33/1.59 to 0.40/0.47).
- **Player and HUD.** The player's body cannot be hidden from scripts, so in the held world it is
  moved 12 m under the ground and the camera offset makes up for it; a time step lets it fall a
  little, so it is parked again after each. The UI's "Empty" game context removes the whole HUD.
- **Settle.** 120 frames per shot: after a cut the path-traced picture keeps changing for about
  that long (captures 40 frames apart differ by 3.7, 1.9, 1.5, 1.2 levels of 255, then 1.0 to 1.3
  for good; `probes/converge_probe.py`). 1.5 s per shot at 85 frames/s in the Badlands, more in the city.
- **Exposure.** Auto-exposure adapts to every view, so along the first near sweep the whole frame's
  brightness went up and down. A take is now locked to the exposure of its first shot through the
  engine option `Rendering/ForcedExposureAvgLum` (found by bisection; adapter setting
  `lock_exposure`). Along the same 345-pose sweep the jitter of the mean brightness fell from 2.12
  to 0.45 levels of 255; views of darker parts of the scene are now darker, as they should be.
- **Frames per shot.** A shot is the average of 8 frames 4 frames apart (`accumulate`,
  `accumulate_gap`): the path tracer's noise differs from frame to frame and showed as flicker
  between neighbouring sweep poses, most in reflections. 2.4 s per shot instead of 1.9 with 4
  frames (2026-11-22); 8 since 2026-11-24 (between clip frames at Badlands: roughness 0.54/0.44 to
  0.46/0.30, brightness jitter 0.05 to 0.02; 12% more frames per shot).
- **Real-time clock.** Video ads, holograms and blinking lights run on the clock the game's own code
  reads, not on the simulation's, so the freeze does not hold them. Our clock plug-in
  (`addons/clock`, `capture_clock.asi` in `bin\x64\plugins`, `install --only clock`) hooks the
  clock calls of the game's exe and of Bink, its video player (their import tables: the graphics
  driver, DLSS, ReShade and the script host keep the real clock), and the session slows that clock
  to 1/5,000 while a take is captured (adapter settings `hold_clock`, `clock_scale`;
  `probes/clock_probe.py`). Stopped outright the game shuts itself down at once, and at 1/100,000
  as well; at 1/10,000 the hanging screens and the blinking light under them stood still, and
  pixels varying by more than 12 of 255 across ten captures of one pose fell from 0.13% to 0.008%,
  frame rate unchanged. Holding Bink alone changed nothing. Near sweeps (345 poses at one instant,
  2026-11-22) against the same sweeps without it (`tools/sweep_flicker.py`: each pose against the
  average of its neighbours): Cherry Blossom Market, the billboard ad that played across the
  sweep now shows one frame throughout; brightness jitter 0.59 to 0.045 levels of 255, roughness
  4.80 to 4.38, pixels off by more than 12 10.1% to 9.2%. Kabuki Market's sweep scored the same
  with and without it (roughness 9.54 and 9.58, jitter 0.063 and 0.062).
- **DLSS 5** (`install cyberpunk --optiscaler`, off by default; `--dlss-nr <nvngx_dlssnr.dll>`):
  OptiScaler's DLSS 5 fork as `OptiScaler.asi` in `bin\x64\plugins`, running on the output of the
  game's own DLSS (DLAA with Ray Reconstruction, which stays on: the picture stays denoised).
  `tools/upscaler_ab.py --game cyberpunk` at the Cherry Blossom Market, noon, 8 views at one frozen
  instant (2026-11-22): it adds contrast, colour depth and local detail, mean FLIP 0.17-0.23
  between off and on (GTA V's range; RDR2 about 0.055). Its automatic white point (what the frame is
  divided by before the model sees it) is metered from every frame, since Cyberpunk hands the
  upscaler no exposure, so it moved from view to view (1.10x to 2.00x across the 8 views, the
  game's exposure locked), as an auto-exposure would. The adapter therefore holds it per take
  (`lock_white_point`; `adapters/common/optiscaler_live.py`, through OptiScaler's live settings
  file): the value the meter settles on for the first shot, fixed for every shot after; checked in
  OptiScaler's log (no change from the first capture to the last). With it held the mean change
  from DLSS 5 was 5.3 to 12.5 levels of 255 per view (8.3 to 13.1 before). A near sweep with it on
  (345 poses, white point held at 1.64x for the whole 20 min) flickered about as much as without
  it: roughness 4.49 against 4.38, brightness jitter 0.080 against 0.045 (`tools/sweep_flicker.py`).
  GTA V Enhanced and RDR2 meter it the same way (their logs: 0.34-0.48x and 13.1-21.5x within
  frozen runs). Skin controls (`tools/dlss5_skin_sweep.py --game cyberpunk --close-ups`: four
  people filmed from the front at their own 32-degree field of view, one frozen instant; OptiScaler's
  menu positions are the same as in GTA V at 2560x1440): DLSS 5 adds beard, pore and eye detail over
  the game's softer faces; skin structure 0 smooths skin, 2 gives the most pore and beard detail,
  1 looks like the default (-1), and the automatic skin mask off changes almost nothing, as in
  GTA V. `--optiscaler` sets skin structure 2 (Nathan, 2026-11-22), as for GTA V and RDR2.
- **Scouting by name.** `python -m adapters.cyberpunk.probes.scout_fast_travel --list` prints the
  fast-travel points the save knows; `... <record>=<name>` records a location a few metres from one.
- **Menus.** A game menu (pause, inventory) holds the world and shows its own camera; one was
  found open after a start and after the window lost focus. A session closes it with Esc before
  it starts, and a shot taken under one is retaken after Esc.
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
  (the market's two hanging screens, its hologram tree). Those are what the real-time clock hold
  (above) is for; the hologram tree still varies with it, as it does with nothing held.
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
- DLSS 5 (above) is installed with `--optiscaler` but off by default: whether captures use it is
  Nathan's call. Its settle after a cut starts higher than without it (5.4 against 4.0 levels at 3
  frames) and meets it by 80 frames; a take waits 120.
- No place titles, no scouting overlay, no visual set; `tests/test_install.py` has no Cyberpunk part.

## The Witcher 3 adapter

"The Witcher 3: Wild Hunt — Remastered" 5.01c (`witcher3`: Steam app 292030, Direct3D 12 only, exe
5.0.0.1090142, build 26238013), the 2026 update with path tracing and DLSS 4.5 Ray Reconstruction.
Everything below was set up and measured on 2026-11-23 on the Windows PC (RTX 5090);
`adapters/witcher3/adapter.py` has every number and `probes/` how each was found.

### Setup

```powershell
.\capture.ps1 install witcher3 --dlss-nr <nvngx_dlssnr.dll>   # game closed: script mod, debug console, ReShade + add-on, DLSS 5, settings
.\capture.ps1 verify witcher3 --launch
python -m adapters.witcher3.probes.scout_fast_travel --list                       # the loaded world's travel points
python -m adapters.witcher3.probes.scout_fast_travel poppystone=mulbrydale        # a location beside one
.\capture.ps1 submit --game witcher3 --location witcher3-mulbrydale-001 --provider ring --set count=8
.\capture.ps1 worker --game witcher3
```

- **No script extender, no ASI loader.** Our session script (`adapters/witcher3/ws/capture_mod.ws`)
  is a loose script mod (`<game>\mods\modCaptureMod\content\scripts\local`) that the game compiles
  with its own scripts at every start; a changed script needs a restart (40 to 60 s to a loaded
  save). WitcherScript cannot read or write files, so commands go in through the game's debug
  console (switched on in `bin\config\base\general.ini`; the key left of 1; pasted, 30,000
  characters at once) and answers come out through the scripts log
  (`Documents\The Witcher 3\scriptslog.txt`, written when the game is started with
  `-debugscripts`). 0.29 s per command. There is no eval: what an agent can try without a restart
  is every `cm_` command (`python -m adapters.witcher3.probes.repl state "pose 944 596 36 -20 60 0 60"
  "shot view1"`); a new one is a script change and a restart.
- **Frames.** ReShade as `dxgi.dll` beside the exe, no effects, and our add-on; the adapter asks
  the add-on for each frame itself (`adapters/common/frames.py`: the add-on now also counts frames
  and can save the n-th frame after a request, for any game).
- **Settings** written into `Documents\The Witcher 3\dx12user.settings` with the game closed and read
  back when a session opens: a 2560x1440 window, path tracing, DLAA with Ray Reconstruction, no
  frame generation, no motion blur, depth of field, chromatic aberration, vignette, lens effects or
  sharpening, no tutorial hints or welcome panels, no telemetry.
- **Unattended start** (`adapters/witcher3/launch.py`): the exe itself, no Steam client or launcher;
  Space through the intro films, Esc past the account screen, our script loads the last save
  (`theGame.LoadLastGameInit`) or, on a machine with no save, starts a Blood and Wine-only game
  (a ready character in Velen) and saves it. 40 to 60 s to the world.
- **Scouting** by name: `probes/scout_fast_travel.py --list` prints the road signs and harbours of
  the loaded world (115 in Velen and Novigrad), `<point>=<name>` records a location a few metres
  from one with the four previews; `capture scout --game witcher3 --at x,y,z` works as for every
  game. Titles are the nearest travel point within 400 m and the region ("Mulbrydale · Velen and
  Novigrad"). The game loads one world at a time; a location keeps its world and a take loads it
  first (`--world skellige` for the helper). No in-game overlay (BACKLOG).

- **Clean slate (2026-11-23, this PC).** Every file of ours moved out of the game folder (and the
  hand-made exploration setup with it, kept in `out\clean_slate_backup\20261123_witcher3`), then
  `capture install witcher3 --dlss-nr <file>` with every part but `machine`: 45 steps, the files
  found in `out\mods`, `ProgramData\ReShade` and the given model; a second run had nothing to do.
  `capture verify witcher3 --launch` then passed every check but that administrator step (the
  machine-wide Vulkan layer, the same for every game here): start to a loaded save in 58 s, 54
  frames/s with DLSS 5, a frozen take of 8 cameras over 3 clip frames (24 shots in 75 s, none
  recaptured, both steps exact to 0.00 ms, DLSS 5's white point held at 2.32x), packaging. Again
  after the method changed (17:50, Hierarch Square): every check but that step, 30 frames/s there,
  24 shots in 108 s, none recaptured, steps within 0.16 ms of 1/30 s.
  `capture mods bundle witcher3 --with-supplied` holds ReShade, OptiScaler with NVIDIA's model and
  our add-on (207 MB; never in git or anywhere shared).

### The Witcher 3 on Linux (CoreWeave, measured 2026-11-24)

The game under Proton (`capture host`; see "On Linux" above), installed from the PC's bundle with
`capture install witcher3 --no-optiscaler` (the cluster's driver cannot run DLSS 5; the game's own
DLAA with Ray Reconstruction and path tracing remain). `capture verify witcher3 --launch`: 55 frames/s,
a frozen take of 8 cameras over 3 clip frames (24 shots in 205 s, none recaptured, steps within
0.31 ms of 1/30 s), packaging; the install check counts OptiScaler's steps and the colour check does
not separate there (BACKLOG). What it took:

- **`[Hidden] HasSetup=true`** in `dx12user.settings` (`settings.py`): without it the game ran its
  first-start setup at every start and put path tracing and the detail settings back.
- **The console paste** needs `xclip` (the conda environment, `capture/host/linux.lock.json`), and
  Ctrl+V as four key events a key's hold apart (`adapters/common/window_x11.py`): sent at once, the
  console often got a plain "v", about every second 400-ray command missed its first try and one in
  about 50 missed all four, so every take failed in its scene raycast. Since: 40 such commands in
  51 s, none missed (60 took 263 s with 33 misses before). Keys are held at least 60 ms there.

### How a take is captured in The Witcher 3 (measured 2026-11-23)

- **Freeze.** A pause of our own: engine time 0.0000000 s over 480 held frames (9 real seconds),
  frames 30 to 480 later differing from the first by the renderer's noise only (1.45-1.63 levels of
  255, flat), none of 60 people moving. The wind in trees, grass and clouds follows engine time, so
  it holds too and moves with each step. Weather changes are paused and the game's keys taken away
  while held; saving is locked while a session is open. The game's photo mode is not used any more:
  switched off and on in a held world (as the first time steps did) it threw people into their
  arms-out reference pose, dropped their torches and started cloth over
  (`probes/cloth_step_probe.py`).
- **Camera.** The photo mode's camera, made the rendered camera without the photo mode (position,
  pitch and yaw, `SetTilt` for roll, vertical field of view): within 0.6% of a pinhole camera at
  40, 60 and 90 degrees (`probes/geometry_probe.py`, the same as with the photo mode); the rendered
  pose read back equals the pose asked to 0.1 mm, also 150 frames later and through steps. The
  game's own camera is no use (it adds its 3.4 m offset from the player and drifts while held).
- **Time steps.** Our pause off, the world run over 8 frames that each cover the same game time
  (the game's per-frame `CR4Game.OnTick`, wrapped with `@wrapMethod`), the pause on again. An even
  step lands within a share of a frame (32.77 to 33.59 ms for 33.33 asked) and the adapter adds the
  difference to the next step, so clip frames stay on the 1/30 s grid (29 steps 0.028 ms short in
  all). Dropped on the way, both 2026-11-23:
  - the photo mode's own tick advanced the clock, wind and grass but held people in place (0 of 57
    moved over 30 steps, against 10, up to 1.6 m, in a second of play);
  - steps whose frames each covered a quarter of what was left landed exactly, but ended on
    microsecond frames before the next step began at milliseconds, and the cloth solver turned that
    jump in time step into a kick at every step: an awning moved 9-12 levels of 255 per 1/30 s step,
    more with each step, the energy staying in the cloth (Nathan saw cloth "reset" and fall into a
    new place at every step). The kick did not depend on how many frames a step took (1 to 181) and
    grew with how long the world was held before it (`probes/cloth_rate_probe.py`).
  With even steps the awning moves 1.5-3.7 per step (mean 2.3) over 30 steps without growing,
  against 1.5 per frame for the world running unbroken at a tenth of its speed sampled every 45 ms
  of game time (`probes/cloth_clip_probe.py`, `side_by_side.mp4`): a small kick per step is left.
  People: 11 of 60 moved during 30 steps (up to 1.17 m), as 10 of 60 in a second of play, none
  while held (`probes/people_step_probe.py`).
- **Settle.** 60 frames after a cut (13 levels of 255 two frames after a 90 degree cut, 1.55 at 12,
  flat at 1.1 from 67), 120 on the first shot; about 0.8 s at 75 frames/s.
- **Exposure** does not re-adapt between views of the held world (under 0.5 of 255 after the
  bright sky or the dark ground; `tools/exposure_check.py`). No lock.
- **Player and HUD.** The player (and a horse it rides) made invisible, the HUD and hints hidden;
  the debug console slides out of the picture within 0.24 s of a command and no shot is taken
  sooner than 0.45 s after one (`probes/console_probe.py`).
- **The player does not exist for the scene.** For a take he stays where he stands as a ghost: not
  seen by people and without collisions, his horse the same (`cm_park`). He cannot be parked out of
  reach: the game puts a teleported player on the ground, with all collisions off he fell through
  the world, and 80 m away he took the crowd with him (59 people within 15 m of the spot became 7).
  `probes/npc_watch_probe.py` (Hierarch Square, a walker followed by handle, the player put 3 m
  ahead of them, then 3 s of steps): hidden but solid, as takes were before, no walker came within
  1.05 m of him and two walked around him; as a ghost one walked straight through his spot
  (0.13 m). Eight trials in a wandering market crowd: a direction, not a fine measurement.
- **Noise.** The path tracer with Ray Reconstruction varies evenly from frame to frame in a held
  world, most in grass (16% of pixels with a standard deviation over 4 across 16 frames); without
  Ray Reconstruction 6.4%, with ray tracing instead of path tracing 12.9%
  (`probes/settings_sweep.py`).
- **DLSS 5** (the default; `--no-optiscaler` leaves it out, `--dlss-nr <nvngx_dlssnr.dll>`):
  OptiScaler's DLSS 5 fork as `winmm.dll` beside the exe (the exe imports it; `dxgi.dll` is
  ReShade's), hooked into the game's own Streamline 2.14 and DLSS 4.5 (DLAA with Ray
  Reconstruction, which stays on), skin structure 2 as in the other games, its white point held per
  take. `tools/upscaler_ab.py --game witcher3` at Electors' Square, noon, 8 views at one held
  instant: more contrast, colour depth and material detail (metal, fabric weave, skin), mean
  change 6.8 to 9.8 levels of 255 per view; the same pose captured twice after a cut differs by
  2.2 with it and 1.8 without; settle curves alike (2.0 and 1.6 levels at 80 frames). The same
  near sweep at Electors' Square with it (345 poses, 16.4 min, white point held at 8.41x
  throughout): brightness jitter 0.18 against 0.10 without it, roughness 18.5 against 17.9
  (`tools/sweep_flicker.py`; different instants of the same crowd), about the rise DLSS 5 gave
  in Cyberpunk.
- **The game's menus.** A key that misses the console can open the game's hub menu, which pauses
  the world. A teleport made under it left the new spot without its grass: a near sweep at
  Mulbrydale had none in its first 72 poses and grass from pose 72 on (about 200 s into the held
  world; `probes/menu_grass_probe.py`, `arrival_probe.py`). The adapter now closes any menu
  before a teleport and before the freeze and lets the world run again if one turned up since;
  opened and closed in a held world a menu takes nothing away. The rerun at Mulbrydale with this
  (2026-11-23 13:04, 345 poses in 13.7 min) has grass from the first pose: brightness jitter 0.14
  against 0.87, its worst poses 251-255 at 19.1 against 22.4 at poses 71-72 (`tools/sweep_flicker.py`).
- **Scene and moving things.** Ray probes against the static scene (`StaticTrace`), people and
  animals as boxes from their capsules; quest characters (any with tags) are never removed.

### Takes (2026-11-23, all queued and run by `capture worker` with no one at the keyboard)

- **Ring over time, retaken with the method above** (held by our pause, no photo mode, even steps,
  the player a ghost), Hierarch Square (Novigrad), 2026-11-23 17:28: 8 cameras x 30 clip frames,
  240 shots in 12.8 min (3.02 s per shot), none recaptured, no health problems, one simulation
  time per clip frame; steps of 32.79 to 33.94 ms that leave clip frame 30 0.024 ms off the 1/30 s
  grid. Over the 30 clip frames people move and the shadows creep with the game's sun (1 s of world
  time, about 15 s of the game's clock); `sheets/ring_8_cameras_10fps.mp4`.
- **Ring over time, first take** (same place and rig, 11:01): 240 shots in 12.1 min, every step
  0.0333328 to 0.0333333 s. Taken with the photo mode's tick, so people animated where they stood
  instead of walking on (found afterwards; see Time steps): superseded by the retake.
- **Near sweep** (`--solver yiming_stdm --cameras H_near_sweep_t000`), Electors' Square (Novigrad,
  a crowd around the rig): 345 poses at one instant in 13.3 min (2.25 s per shot), one simulation
  time throughout, one shot retaken (a menu had opened before the first). `tools/sweep_flicker.py`:
  brightness jitter 0.10 levels of 255; roughness 17.9, which is camera motion past people a metre
  from the lens (the path turns about 1 degree and moves 5.6 cm per pose; shrunk to 60x34 pixels
  the second difference falls to 5.4), not flicker. The solver declined a spot beside the market
  stalls of Hierarch Square (no clear 2.4 m orbit): pick open spots for this rig.

## Kingdom Come: Deliverance adapter

Kingdom Come: Deliverance (`kcd`: Warhorse, CryEngine, Direct3D 11; Steam app 379430, the exe
1.9.7.0, the main menu 1.9.8-404). Set up and measured on 2026-11-23 on the Windows PC (RTX 5090);
`adapters/kcd/adapter.py` has every number and `probes/` how each was found.

### Setup

```powershell
.\capture.ps1 install kcd             # game closed: our mod, ReShade + add-on (dxgi.dll), user.cfg (every part but machine)
.\capture.ps1 verify kcd --launch
python -m adapters.kcd.probes.scout_places --list                                   # the developers' named places
python -m adapters.kcd.probes.scout_places "Rataje - pillory=rattay-pillory"         # a location at one
python -m adapters.kcd.probes.repl --reload "=state" "+return player:GetWorldPos().x"  # reload our script, any Lua
.\capture.ps1 submit --game kcd --location kcd-rattay-pillory-001 --provider ring --set count=8 --set last=30
.\capture.ps1 worker --game kcd --once
```

- **Script layer: the game's own Lua.** Our script (`adapters/kcd/lua/capture_mod.lua`) is a mod
  (`<game>\Mods\capture_mod`: a manifest with no version limits, and a pak holding
  `Scripts\Startup\capture_mod.lua`), which the game runs at the main menu. A manifest that named
  1.9.7 got the mod disabled ("doesn't support game version '1.9.8'").
- **In and out.** Commands go in through the console (`-devmode`; the key left of 1; Ctrl+V
  pastes; a line starting with `#` runs as Lua). Answers come out through `kcd.log` in the game
  folder (`System.LogAlways`, there at once).
- **Long commands.** A console line takes about 250 characters, so longer commands go in pieces.
- **Bulk input.** Rays and other bulk data go as Lua files written into `<game>\Data\capture_mod_in`.
  Our script runs them with `Script.LoadScript`, which reads loose files only while
  `sys_PakPriority` is 0. The game runs at 2 (paks only, `user.cfg`) and our script sets 0 for each
  such read and back (at 2 the same load gave nothing, with the switch the file; 2026-11-24). At 0
  or 1 every file the engine looks for and lacks (level-of-detail models and the like) is looked up
  on disk: free on the PC, but under Wine on CoreWeave's network folders each miss cost several
  round trips and the main menu's level did not load in 5 minutes. `ReloadScript` skipped a file
  it had run before. Lua has no `io` here.
- **Long answers.** Log lines are cut at about 3,900 characters, so long answers come in several
  lines.
- **Iterating.** There is a real eval (`+<lua>`) and a reload without a restart: `--reload` sends the
  script through the file route in 1.5 s. 2,000 rays take 0.68 s.
- **Unattended start** (`adapters/kcd/launch.py`): the exe with `-devmode`; Steam picks the game up
  on its own. `user.cfg` turns the intro films off. Enter at the main menu is Continue: 51 s to a
  loaded save (29 s to the menu). The first start on a machine shows the publisher's EULA, which E
  accepts.
- **A loaded save, not the menu.** The main menu is a view of the real Rattay level with a player in
  it, so a loaded save is told by the player standing away from the menu's spot.
- **Scouting** by name at the developers' named teleports (`places.py`, read from the game's
  `Scripts.pak`: 40 squares, pubs, castles, mills, camps). Locations get the nearest within 400 m as
  their title. Tried at the Rattay pillory, Talmberg, the Sasau bridge and Ledetchko.
  `capture scout --game kcd --at x,y,z` works as for every game. No in-game overlay (BACKLOG).

### Kingdom Come: Deliverance on Linux (CoreWeave, measured 2026-11-24)

The game under Proton in the RDR2/GTA V prefix, beside that prefix's Windows Steam client: its
licence check needs a running client that lists the game as installed (`capture host steam kcd`
links the downloaded folder into the client's library and writes the app manifest from
`install.STEAM`). `capture verify kcd --launch` passed every check: 103 s to the menu (most of it
the runtime container), a save loaded 22 s later, 54 frames/s, a frozen take of 8 cameras over 3
clip frames (24 shots in 136 s, none recaptured, steps exact to 0.00 ms), packaging; the colour
check does not separate there either (34.1 against 35.9). What it took, each in the code:

- **Only the job's processors shown** (`WINE_CPU_TOPOLOGY`, `host.start_beside_steam(limit_cpus=True)`):
  with all 128 of the node visible CryEngine's processor survey crashed at start.
- **`mod_status.xml`** in the game folder (`install.py`): without it the first start moved `Mods`
  away to `mods_old`.
- **`sys_PakPriority` 2** (Bulk input, above): with loose files looked up the menu's level did not
  load in 5 minutes from the network folder; now in seconds.
- **The app id for ProtonFixes**: a run without a game got `SteamAppId` 0, or ProtonFixes failed.
- **By hand, once:** the publisher's EULA accepted with E (as on the PC, on Nathan's word for this
  copy). Steam Cloud brought the account's own KCD saves into the prefix when the game first ran
  beside the client; Continue loads the newest (BACKLOG: keep closing the game by its window).
- One session crashed the game (0xC0000005) right after setting `sys_spec_Shading` 4 at run time,
  while the profile's `attributes.xml` was still empty (the same settings went through in verify
  and the next job). Since the install writes the capture values into `attributes.xml`, the game
  starts at them and the session's switch changes nothing (2026-11-24).

### How a take is captured in Kingdom Come: Deliverance (measured 2026-11-23)

- **Freeze.** CryEngine's time scale at 0 (`t_Scale`). Over 6.6 s none of 11 people moved, the game's
  timer and the world clock stood still, and frames kept rendering. The same view 20 and 300
  frames into a hold differs by 0.003 levels of 255.
- **Time steps.** `t_FixedStep` makes every frame advance exactly dt/n of game time. The world runs
  for n frames, counted by a per-frame script timer (script timers follow game time, so none
  fires while held), and is held again.
  - CryEngine smooths frame times, so coming out of a hold the first frames ramped up from 0: steps
    of 3.8 to 9.5 ms for 33.3 asked.
  - With `t_Smoothing 0`, every step of 1/30 s in 8 frames advanced 33.3330 ms, each frame exactly
    4.1666 ms. These are even frames by construction, which cloth needed in The Witcher 3.
- **Camera.** `CryAction.SetViewCameraByAngles` takes degrees as CryEngine's Ang3: pitch, roll, yaw,
  rotation Rz·Ry·Rx. The field of view is vertical. 20 random poses with roll read back within
  0.004 degrees and to the millimetre. A 2 degree turn measures 39.85, 59.48 and 89.44 degrees for
  40, 60 and 90, within 0.6%. A roll of 10 turns the picture 10.00 degrees.
- **The player does not exist for the scene.** For a take he is a ghost where he stands: body
  hidden, perceived by nobody, and without physics.
  - The "perceived by nobody" part is the developers' invisibility command, run through the game's
    own Haste, whose stale state is cleared first: a second command otherwise failed inside Haste.
  - Followed by entity id, with the player put 3 m ahead (`probes/npc_watch_probe.py`): both walkers
    went straight through his spot, 0.28 and 0.19 m from it.
  - Hidden only, one walker of four strayed 2.3 m around him. Ten trials: a direction, not a fine
    measurement.
- **Settle.** Without temporal anti-aliasing a settled frame matches to 0.003 levels of 255, and the
  first frame after a cut to 0.18. With SMAA 2TX, frames alternate between two sub-pixel offsets by
  0.2 to 0.75 with no trend after a cut. So: 20 frames per shot, and two frames in a row averaged.
- **Exposure** does not re-adapt between views in a held world. A view reads 80.21 of 255 after
  itself, 80.33 just after the sky (242) and 80.01 after the darkest view. The eye does adapt during
  time steps, which run on game time (below).
- **Arrival, before the hold** (2026-11-24). Grass bent by people and the eye's adaptation move on
  game time only, so a hold keeps their state.
  - In the first takes the grass where the player had stood was pressed flat in clip frame 1 and in
    the whole near sweep, and stood up in the first step. Every ring camera also grew 1.1-2.8%
    brighter over clip frames 2-11, the eye moving from the player's view to the rig's
    (`tools/temporal_flicker.py`, `tools/clip_strip.py`).
  - Now the camera goes to the take's first pose while the world runs. The world runs 2 s after the
    player becomes a ghost before the hold, and every time step renders the first pose.
  - The ring retaken at the same clock has the grass up in clip frame 1. Its first step changes
    0.79-1.27 times as much as the later ones (was up to 4.8). Its brightness stays within 0.4% over
    the 30 clip frames.
  - Not everywhere: at Sasau bridge (a CoreWeave node, noon) the fixed cameras still rose 2.75% and
    1.8%, almost evenly over the whole clip, while Talmberg's stayed within 0.2%. The eye adapts
    slowly, and 2 s were not enough there.
  - So the eye is now held from the hold to the end of the take (`r_HDREyeAdaptationSpeed 0`, setting
    `eye_lock`), as RDR2's photo-mode lock holds its exposure, and adapts at 10 times the game's speed
    in the 2 s before it (`eye_run_speed 30`). Measured at Sasau (2026-11-24): 2 s at the game's
    speed left the frame 15-25 levels of 255 from adapted, 2 s at 30 arrived (79.5 against 79.8 after
    15 s). Held at 0 through 30 steps, a view stayed within 0.1 levels, and a view still read the same
    after the sky and after the darkest view (118.17, 118.00 against 118.11).
- **Clock.** The game does not move its clock back: `Calendar.SetWorldTime` to an earlier time leaves
  it where it was. So the first takes asking for 12:00 ran in the afternoon (14:33 to 15:21). An hour
  already past is now that hour the next day.
- **The look.** The game's top settings:
  - Ultra High on every category, SMAA 2TX, object detail and view distances at the menu's
    maximum, no VSync (it capped the game at 60 frames/s);
  - lens effects, depth of field and motion blur off.

  The game's `attributes.xml` (the options its menu saves) overrides `user.cfg` at start, so the
  install writes them there with the game closed. The session still sets them through the console
  and reads them back: switching the specs at run time crashed the game once on a CoreWeave node,
  whose file had no saved options. Against the game's High at one held instant: softer, fuller shading
  and more grass and rocks, with a mean change of 2.5 to 7.0 levels of 255 per view
  (`probes/visual_probe.py`).
- **No DLSS 5.** The game has no upscaler for OptiScaler to hook. The free HD texture pack (a Steam
  DLC) is not installed here.
- **Scene and moving things.** Rays against terrain and static objects. People and animals come back
  as boxes from their own bounding boxes; none counts as owned, since saving is locked during a
  session and a removal never reaches a save.
- **The game's timer is not the world's time.** Held, the game's own timer (`System.GetCurrTime`, a
  float) creeps although nothing moves. One pose held 420 s gave the same frame at both ends (0.0038
  levels of 255), and none of 17 people moved 0.1 mm, while the timer moved 5.9 ms
  (`probes/creep_probe.py`).
  - The first takes logged that timer and saw it change by one float step within a clip frame.
  - The take log now carries the world's time as our script counts it: the exact sum of the steps,
    and the timer only while the world runs free.
- **Clean slate (2026-11-23, this PC).** Every file of ours was moved out of the game folder (kept in
  `out\clean_slate_backup\<stamp>_kcd`): the mod, `Data\capture_mod_in`, `user.cfg`, ReShade, its
  settings, the add-on and the install record.
  - `capture install kcd --mods out\bundles\capture-mods-kcd.zip`, with every part but `machine`:
    22 steps.
  - `capture verify kcd --launch` then passed every check but that administrator step: 84 frames/s,
    a frozen take of 8 cameras over 3 clip frames (24 shots in 64 s, none recaptured), steps exact
    to 0.00 ms, and packaging.

### Takes (2026-11-23, queued and run by `capture worker` with no one at the keyboard)

- **Ring over time**, Rattay pillory: 8 cameras x 30 clip frames, 240 shots in 8.6 min (2.07 s per
  shot), none recaptured, no health problems.
  - The solver's 66,000 rays went through the file inbox, and the ring shrank to 2 m to clear the
    stalls.
  - Every step was 33.3330 to 33.3340 ms.
  - One clip frame logged two values of the game's timer one float step apart: see above; the world
    did not move.
- **Near sweep** (`--solver yiming_stdm --cameras H_near_sweep_t000`), the same spot: 345 poses in
  7.8 min (1.32 s per shot), none recaptured.
  - `tools/sweep_flicker.py`: brightness jitter 0.055 levels of 255, roughness 9.86 (camera motion
    past people near the lens). Compare it only with sweeps at the same spot.
  - The first attempt failed after one shot: probes typed into the game while the worker ran and put
    the console out of step. The session now looks at a frame to tell whether the console is open
    (the solid black line at its bottom edge).

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
