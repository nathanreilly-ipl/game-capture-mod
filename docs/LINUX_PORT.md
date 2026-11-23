# Porting capture_mod to CoreWeave Linux: a survey

Surveyed 2026-11-22 from the code at master `416cab2`, from web research that day, and from a
read-only inspection of our CoreWeave machine. The first feasibility test ran there on 2026-11-23
and passed (section "Feasibility test, part A"), and the same day Cyberpunk 2077 was installed,
verified and captured there through the CLI (section "Cyberpunk through the CLI"); that code is
on master as `2d076b3`. RDR2, GTA V and DLSS 5 are still untested on Linux. Version-specific findings
(drivers, Proton builds, DLSS 5 support) change quickly: check them again before relying on them.

## Verdict

Feasible, through Proton (the games are Windows-only), but the largest unknowns are outside our
code: DLSS 5 on Linux, and Rockstar's launcher without a person at a screen. Estimate: a 3-5 day
feasibility test, then 4-6 weeks for all three games if the test finds no blocker; Cyberpunk 2077
alone about 2 weeks. Windows on CoreWeave is ruled out (Nathan, 2026-11-22), so Linux is the only
route there; the nodes have RTX PRO 6000 cards.

The machine we actually have there was inspected the same day (next section). It changes the
picture in three ways: we are an ordinary user in a Slurm job with no root and no way to install
packages, so everything has to arrive in user space; there is no display server and no `/dev/dri`,
so a headless display the NVIDIA driver can present to is the first thing to prove; and the driver
is 580, older than the DLSS 5 reports for Linux ask for, so DLSS 5 waits on the cluster's admins.

The first test passed on 2026-11-23: modded Cyberpunk 2077 runs there under Proton on a headless
display, with no root and no Steam client, and a 2560x1440 frame came out through our capture
add-on with path tracing, DLAA and Ray Reconstruction on. So the display, the mod loaders, ReShade
with our add-on and the clock plug-in are no longer unknowns for Cyberpunk. The same day our own
Python side followed for Cyberpunk: a clean-slate `capture install`, the full `capture verify`, a
345-shot near sweep and a 30-clip-frame take ran there through the unchanged adapter and worker.
A shot takes 5.6 s there against 2.5 s on the PC (7.3 s before the job was given one thread per
core). Still open: the rest of that gap, DLSS 5 (the driver), and the Rockstar launcher for the
other two games.

## The machine we have (inspected 2026-11-22)

Read-only checks by a Claude session running on the cluster; nothing was installed.

- **Where:** a Slurm job (partition `rtxp6000`) inside a fixed container image, Ubuntu 22.04,
  kernel 6.8. User `nathan.reilly`, no root (sudo asks for a password, no capabilities, a seccomp
  filter on). No docker, podman, apptainer or bubblewrap. Unprivileged user namespaces work
  (`unshare -Ur id` gives uid 0). The job has 1 of the node's 8 GPUs, 8 CPUs and 128 GB.
- **GPU:** RTX PRO 6000 Blackwell, 96 GB, driver 580.105.08. `/dev/nvidia*` nodes only: no
  `/dev/dri`, no `/dev/tty*`, no input devices.
- **Driver libraries present:** NVIDIA's Vulkan driver entry (`/etc/vulkan/icd.d/nvidia_icd.json`,
  API 1.4.312), its OpenGL, EGL, ray tracing and NGX libraries, and its Xorg modules
  (`nvidia_drv.so`, `libglxserver_nvidia.so`).
- **Missing:** the Vulkan loader (`libvulkan.so.1`); the Wine-side DLSS files (`nvngx.dll`,
  `_nvngx.dll`), nowhere on the filesystem; every display server (Xorg, Xvfb, Xwayland, gamescope,
  Sway, Weston); Wine, Steam, steamcmd; all 32-bit libraries; any compiler for Windows DLLs.
- **Memory access:** `ptrace_scope` is 1 and cannot be changed, so one process may read or write
  another's memory only if it is an ancestor of it or the target allows it.
- **Storage:** node-local `/` and `/tmp` have 6.5 TB free but should be assumed gone when the job
  ends; the shared home (`/mnt/home`, where the repo is cloned) is NFS with 2.0 TB free, 97% full.
- **Internet** works (GitHub answers).

What follows from it:

- **Software comes in without root:** `.deb` files unpacked into a user folder (Vulkan loader, a
  display server), Proton as a download, the Wine-side DLSS files taken from the 580.105.08 driver
  package and put into the prefix by hand. Proton normally runs inside the Steam Linux Runtime,
  which also brings the 32-bit libraries and needs user namespaces; whether the seccomp filter
  lets that through is untested.
- **The game is copied, not installed.** steamcmd and the Steam client are 32-bit programs, so
  Cyberpunk's installed folder (with its mods) would be copied from the Windows PC; it starts from
  its exe.
- **The display was the open question, and Xvfb answered it** (part A below). With no root and no
  `/dev/dri`, the candidates were Xvfb, then Xorg run as a user with NVIDIA's own driver modules,
  then gamescope's headless backend; the first one worked, against this survey's expectation.
- **DLSS 5 cannot be tested here yet.** One Linux project asks for driver 610 or newer; the
  partition has 580, and a job cannot change it.
- **Memory access must be designed for `ptrace_scope` 1:** our Python starts the game and stays
  its ancestor, or the access runs inside Wine, where reading another process's memory goes
  through Wine's own server. Not needed for Cyberpunk.

## Feasibility test, part A: passed (2026-11-23)

Run by the Claude session on the cluster: no root, driver 580.105.08, one RTX PRO 6000 Blackwell
Server Edition, 8 cores. The game and the Proton prefix sit on the shared NFS disk.

**What worked**

- **Proton:** GE-Proton11-12 inside Steam Linux Runtime 4 (GE-Proton11 needs it; the older
  "sniper" runtime fails on its Python), started with the runtime's entry point and `proton
  waitforexitandrun`. The runtime's container starts with unprivileged user namespaces despite the
  seccomp filter. No Steam client anywhere: the game starts from its exe without one.
- **Display:** Xvfb at 2560x1440, taken from Ubuntu's `.deb` and unpacked into a folder. It needs
  `/usr/bin/xkbcomp`, given to it through a private mount namespace (`unshare -Urm` with bind
  mounts). NVIDIA's Vulkan driver presents to it: the game's picture is in the X root window, so
  screen grabs work as well as the add-on.
- **The game:** downloaded with DepotDownloader pinned to the PC's build (depot 1091501, manifest
  3524634124112875626); 66,818,683,782 bytes and the exe's SHA-256 match the PC's.
- **Mods:** the PC's non-Steam files copied over the download (55 files; the OptiScaler and DLSS 5
  files left out), with `WINEDLLOVERRIDES="winmm,version=n,b"`. RED4ext 1.31.1 with Codeware,
  redscript's compiler, Cyber Engine Tweaks 1.38.1, ReShade 6.8.0 hooking Wine's `d3d12.dll`
  (VKD3D-Proton) with a 2560x1440 swap chain, our capture add-on registered, our clock plug-in
  hooked into the exe and the video player, our loader's heartbeat about once a second.
  `d3dcompiler_47` from winetricks was not needed.
- **DLSS files:** `nvngx.dll` and `_nvngx.dll` from the 580.105.08 driver package, copied into the
  prefix's `system32`, plus the registry value `HKLM\Software\NVIDIA Corporation\Global\NGXCore`
  `FullPath`. Proton's log shows them and the game's DLSS and Ray Reconstruction DLLs loading.
- **Three config files rewritten** to the game folder as Wine sees it (`Z:\mnt\data\...`): the two
  `ReShade.ini` and `capture_clock.ini`.
- **Settings and saves** from the PC, under `drive_c/users/steamuser`. `UserSettings.json` stayed
  byte-identical, and with `user.gls` from the PC the user agreement screen did not appear.
- **Our scripts, unchanged:** `adapters/common/redlua.py` ran `continue_game.lua` and the session
  job; `adapters.cyberpunk.probes.repl` works with `CYBERPUNK_DIR` set. Keys go in with xdotool.

**Numbers**

- To a loaded save: 64 s from the main menu, about 100 s from process start (on NFS; 39 s on the
  PC from a local disk).
- In the world: about 42 frames/s (frame time 0.0236 s) at night in the Badlands; GPU load 38-77%,
  up to 9.7 GB of its memory. Not compared with the PC on the same scene.
- `shoot 120`: a 2560x1440 frame through the add-on in 4.1 s, colours matching a grab of the X
  screen. Live settings read back as path tracing on, DLAA, Ray Reconstruction on, windowed
  2560x1440.

**Measured the same day through the scripts, with no port**

- **Freeze:** 480 held frames in 15.2 real seconds moved the simulation 0.000000000 s.
- **Clock hold** at the adapter's 1/5,000: the plug-in reports both modules hooked and holding.
  Five captures of one pose 4 frames apart: neighbours differ by 1.99 levels with 4.01% of pixels
  off by more than 12 with the clock running, 0.95 levels and 0.24% with it held.
- **Memory access:** with `ptrace_scope` 1, a Python that is not an ancestor of the game read
  `/proc/<pid>/maps`, opened `/proc/<pid>/mem` for reading and writing and read the exe's header;
  `process_vm_readv` worked too. So Wine processes there can be read from outside without
  starting them ourselves. A write was not exercised.
- Frame rate: 8 frames/s right after the save loaded, 32 over the 480 held frames.

**Not measured in part A**

- Whether DLSS and Ray Reconstruction really engage, beyond their DLLs loading and the settings
  reading true (the picture is clean, not noisy).
- DLSS 5 (needs a newer driver), and writing the game's memory from outside.
- The 1/30 s steps, the exposure lock, pose accuracy, a take and `capture verify` were not
  measured in part A, because the adapter and the CLI did not run there. They are measured in the
  next section.

The scripts that did part A are on the cluster under `out/tools/scripts`, outside the repository.

## Cyberpunk through the CLI on CoreWeave (2026-11-23)

Reported by the Claude session on the cluster, which ported the installer and the shared layers
that day on Nathan's instruction. The code is on master (`a660617`, merged in `2d076b3`). The
numbers from the cluster were not checked from the PC; the comparison numbers are from the PC's
take records at the same place (`cyberpunk-cherry-blossom-market-001`, 2026-11-22).

**What was added (game-agnostic unless noted)**

- **`capture/host`:** `windows.py` and `proton.py` (Proton in Steam Linux Runtime 4, Xvfb, one
  prefix per game under `out/proton/<game>`, paths as the game sees them, start, stop, process
  ids), `capture host status|setup|prefix <game>|stop <game>`, its downloads pinned in
  `capture/host/linux.lock.json`, and `capture.sh` beside `capture.ps1`.
- **`adapters/common/window.py` and `mem.py`** pick an implementation: the old files as
  `window_win32.py` and `mem_win32.py`, new `window_x11.py` and `mem_linux.py`.
- **Installer:** a Proton system beside the Windows one; ini values that hold a path can be
  written as the game sees it (`Z:\...`); the clock plug-in installs from a prebuilt file with a
  source stamp, as the capture add-on does, and `capture mods bundle` now carries it; the source
  stamp no longer depends on line endings (it differed between two checkouts of the same commit
  on the PC).
- **Cyberpunk only:** the DLL overrides, the game folder's default on Linux, the settings path,
  the start through the host layer, and closing the game through its window.
- **Tests:** `tests/test_install.py` parts A and P pass on Linux, and a new part F covers the
  Cyberpunk plan with both path styles.

**Clean-slate install**

- The game folder was reset to exactly the download's 155 files (109 others removed) with a fresh
  prefix. `capture install cyberpunk --mods capture-mods-cyberpunk.zip` applied 50 steps; a second
  run had nothing to do.
- A killed game leaves no `UserSettings.json`. Closed through its window it exits in 5 s and
  writes the file; the install then set 11 settings (resolution, path tracing, DLAA, the
  transformer model, Ray Reconstruction, the six lens effects) and a third run had nothing to do.
- To a loaded save: 182 s on the first start of a fresh prefix, 155 s on the second, 146 s in
  `verify`.

**`capture verify cyberpunk --launch --quick`: passed**

- Scripts answer, a 2560x1440 frame comes through the add-on, 20 frames/s (in the city, afternoon).
- The colour check passed only just (51.5 against 51.8 with red and blue swapped), because
  `verify` grabs the screen after the world has been let go, so it compares two different
  pictures. At one held instant the add-on frame and the screen grab differ by 0.19 levels (11.22
  swapped). This weakness is not specific to Linux.
- Held world through the adapter: rendered pose 0.02 mm and 0.000 degrees off the asked pose;
  five 1/30 s steps of 0.033332000 to 0.033332500 s, worst error 0.0013 ms; the clock held; no
  health problems.

**Near sweep at one instant** (`H_near_sweep_t000`, 345 shots, settle 120, 4 frames averaged, clock
held at 0.0002)

| | CoreWeave | PC |
|---|---|---|
| Shots, recaptured, health problems | 345, 0, 0 | 345, 0, 0 |
| Seconds per shot | 7.28 (2,594 s in all) | 2.50 (903 s in all) |
| Game clock over the take | one value over 43.2 min | one value over 15 min |
| Exposure lock (forced luminance / auto / locked) | 0.620824 / 49.52 / 49.47 | 0.642121 / 51.19 / 51.02 |
| `tools/sweep_flicker.py` roughness | 5.14 | 4.38 |
| Share of pixels off by more than 12 | 10.57% | 9.18% |
| Brightness jitter | 0.069 | 0.045 |

- The rig is the same by its solve record (147 cameras, far ring dropped for the same reason,
  near radius 2.5743 m), and the rendered poses agree with the PC's within 0.1 mm.
- The flicker numbers are higher on CoreWeave and the cause is not found. Clock and weather were
  the same (12:00 from the location, the adapter's default sunny weather on both machines). The
  crowd differs, and the PC never repeated a take with identical settings, so the spread between
  two runs on one machine is not known. One candidate scales with the frame rate: a shot takes
  2.9 times as long there, so at the clock scale of 0.0002 the real-time animations move 1.5 ms
  between neighbouring poses against 0.5 ms on the PC. The flicker map has no hot spot. Not
  pursued until the frame rate is fixed.

**30 clip frames over time** (`H_near_moving` and two temporal cameras, `--last-frame 30`)

- 89 of 89 shots, none recaptured, no health problems, 885 s.
- 29 steps: worst error 0.0017 ms, mean 0.0013 ms; every clip frame's shots share one game clock
  value. The time sheet shows people walking steadily.

**Frame rate and the job's CPUs** (same place, 2560x1440, path traced)

| Slurm job | CPUs the game used | Frames/s running | Frames/s held | GPU | Seconds per shot |
|---|---|---|---|---|---|
| `--cpus-per-task=8` | 4 (ids 24, 25, 27, 28) | 17-18 | 25-26 | 40-50%, 220-250 W | 7.28 (345-pose sweep) |
| the same with `--hint=nomultithread` | 8 cores (ids 2, 3, 8-13) | 28.1 | 36.3 and 38.5 | 71%, 290 W | 5.59 (every 8th sweep pose, 44 shots) |
| the PC, for comparison | | 50 or more in the sweep | | | 2.50 |

- **Cause of the first row:** the job's 8 CPUs were four cores with both threads (the node has 2
  sockets of 32 cores with 2 threads each, and Slurm counts a thread as a CPU). The second thread
  of each core has an id of 64 or more, which Wine did not use, so about 22 runnable threads
  shared 4 cores. `WINE_CPU_TOPOLOGY` changed nothing.
- **Asking for one thread per core** gives eight ids under 64 and all 82 game threads run on them.
  Slurm still counts 8 CPUs for the job.
- **Still 2.2 times the PC's shot time,** with the GPU at 71%. More cores are untried (the
  partition's default is 12 CPUs per GPU). Presenting to Xvfb is not the limit: a Vulkan test
  program runs at about 360 frames/s at 2560x1440.

**Packaging and the full `verify`**

- ffmpeg comes from a conda environment on the cluster (`~/.conda/envs/game-capture`, ffmpeg 9.1
  with libx264); the host layer looks there. `capture package` then packaged both earlier takes,
  which had ended "failed: ffmpeg not found".
- The full `capture verify cyberpunk --launch` passes on Linux: start in 127-182 s, a 2560x1440
  frame, a frozen take of 8 cameras over 3 clip frames (24 shots in 256-259 s, none recaptured),
  both 1/30 s steps 0.00 ms off, and 8 cameras packaged.

**On master, and checked on Windows**

- The port is on master as `a660617`, merged in `2d076b3` (2026-11-23).
- On the PC after the pull, with no game started: `tests/test_install.py` parts A, P, B, C, D, E
  and F pass with the three mod bundles as `--mods`, the two other test files and the Lua check
  pass, and `capture install cyberpunk --dry-run` reports the game's settings as already right.
  `capture verify` was not run on Windows after the pull, and `capture/host/windows.py` has not
  started a game yet.
- Found there: the game stores its resolution with a list index that depends on the display (14
  on the headless display, 12 on the PC), so the settings check now accepts the right value with
  the game's own index.

**Open on CoreWeave after this**

- **Frame rate:** 5.59 s per shot against the PC's 2.50 (above).
- **The exposure lock's range**, found through this comparison and present on the PC too: at
  Kabuki and the Badlands the lock ends at the top of its search range (98.88) with the picture 9
  to 12 levels brighter than auto-exposure had chosen. The session on the cluster is fixing it.
- **A stale heartbeat** once, when `verify` started within about 10 s of another session's end;
  fine 30 s later.
- **RDR2 and GTA V Enhanced:** being started 2026-11-23 from clean-slate installs, the games
  downloaded with DepotDownloader pinned to the PC's builds, the Rockstar launcher sign-in done
  by Nathan. Nothing measured yet.
- DLSS 5 (the driver), and more than one game per node.

## What CoreWeave offers

- **Linux containers on bare metal.** The current platform (CKS) runs Kubernetes directly on
  bare-metal nodes with no hypervisor; its docs say customer clusters do not run virtual
  machines. Windows GPU VMs existed in the older Virtual Servers product (its docs are on the v1
  site); Nathan confirmed there is no Windows for us (2026-11-22).
- **Our nodes have RTX PRO 6000 cards** (Nathan, 2026-11-22). CoreWeave lists that node type as
  `rtxp6000-8x`: 8 x RTX PRO 6000 Blackwell Server Edition, 96 GB each, so one node could run
  eight game instances, one per GPU. A node pool picks its driver branch: 580 is the listed
  default, 595 and 615 the alternatives.

## How the games would run

Each game runs under Proton (Wine, with Direct3D 12 translated to Vulkan by VKD3D-Proton) in a
container with one GPU and its own headless display. Our in-game parts run inside the game process
as they do on Windows; the Python side drives the game from outside.

| Part | Status on Linux | Source |
|---|---|---|
| Script Hook RDR2 + ASI loader | Reported working with the override `dinput8=n,b` | ProtonDB reports |
| GTA V Enhanced ASI loader as `xinput1_4.dll` | Reported working with `xinput1_4=n,b`; story mode only | a GTA V Enhanced ASI plug-in's notes |
| Cyber Engine Tweaks, RED4ext | Documented: `winmm,version=n,b`, plus `d3dcompiler_47` through protontricks | RED modding wiki |
| ReShade with add-ons, Direct3D 12 | Runs; crashes with an add-on and DLSS both on were fixed, then reported again for Cyberpunk with ReShade 6.7.3 | ReShade forum |
| OptiScaler | Supports Linux (wiki, an installer script) | OptiScaler wiki |
| DLSS Super Resolution, DLAA, Ray Reconstruction | Supported under Proton through DXVK-NVAPI | NVIDIA driver guide |
| DLSS 5 | Experimental community projects only; see below | several GitHub projects |
| Ray tracing, path tracing | VKD3D-Proton supports DXR on NVIDIA; speed against Windows not measured | VKD3D-Proton |
| A game in a container with no monitor | Done by community projects (a headless Steam image, gamescope's headless backend, headless Sway); none on Kubernetes | see Sources |

## Unknowns that could block it

1. **DLSS 5 on Linux.** The card should not be the problem: DLSS 5 is reported as needing the
   Blackwell generation's tensor cores, and the RTX PRO 6000 is that generation (NVIDIA's list
   names only GeForce RTX 50 cards, so this is expected, not confirmed, until it runs). What is
   unproven is the Linux side. DLSS 5 runs under Proton only through experimental community
   projects: one says it is verified in one game, another that it has not yet run in a game, and
   one reports that hardware optical flow does not initialise under Proton. Ours goes through the
   OptiScaler fork with `nvngx_dlssnr.dll`, which nobody is reported to have run on Linux.
   NVIDIA's own driver guide does list a neural-rendering override from DXVK-NVAPI 0.9.3. One
   community installer for Linux asks for driver 610 or newer, so the node pool would need the
   615 branch, not the default 580. Without DLSS 5, cloud captures would not match the look
   captured on the Windows machine.
2. **Rockstar Games Launcher** (RDR2, GTA V). Under Proton, login failures are common in user
   reports; the offline switch (`-scofflineonly`) was reported failing; no source describes a
   login without a person at a screen. The login would have to be done once per machine image and
   kept, and repeated when it expires.
3. **Accounts and copies.** One Steam or Rockstar account runs one game on one machine at a time,
   so N parallel workers need N accounts and N copies. Whether each game's licence allows this use
   on cloud machines is a question for whoever handles that; this survey did not look into it.
4. **Our frame capture.** Every frame comes out through our ReShade add-on, so the crash reports
   for add-ons with DLSS under Proton (above) matter directly. In part A the add-on, DLAA and Ray
   Reconstruction ran together in Cyberpunk without a crash (2026-11-23); with OptiScaler and
   DLSS 5 it is untried.
5. **Untested under Proton:** NaturalVision Enhanced (its own plug-in, 95 shader replacements, a
   DLC loader), Reality Redemption 2 (RDR2's hardware ray tracing, a ReShade add-on), GTA V
   Enhanced's protection that crashes the game on purpose, and RedLua's faults. Our clock plug-in
   is no longer on this list: under Proton it hooks the exe and the video player and holds the
   clock (2026-11-23: 4.01% of pixels changing with it running, 0.24% held).
6. **The driver's libraries inside a container.** A headless Steam image has an open report of
   DLSS becoming unavailable because Proton could not find the driver's DLSS libraries in the
   container. On our machine the same files are missing (`nvngx.dll`, `_nvngx.dll`), while the
   driver's graphics libraries are there; the files would come from the driver package, untried.

## Per game

| Game | Difficulty | Why |
|---|---|---|
| Cyberpunk 2077 | Easiest | Starts from its exe with no launcher; its mods have Linux instructions; the capture path writes no game memory (only finds the process and window, and grabs the window); DLSS 5 is optional there |
| RDR2 | Medium | Rockstar launcher; the camera pose is written into game memory for every shot; five PowerShell scripts and its own window and memory modules to replace; Reality Redemption 2 untested |
| GTA V Enhanced | Hardest | Rockstar launcher and Steam's launch dialog; NaturalVision Enhanced; the protection crash; the minimum time step written into game memory; settings-menu navigation by screenshots |

## Our code

About 5,400 lines of Python, 4,700 of Lua and 350 of PowerShell under `adapters/`, plus the
game-agnostic `capture/`.

**Unchanged**

- The in-game Lua (loaders and session jobs) and the file protocol between Python and the game.
  The exchange folders move inside the Proton prefix, but they are ordinary files.
- `capture/` outside the installer: rigs, scene, placement, shot lists, the take loop, per-shot
  checks, packaging, QC, the folder queue and the worker. The queue is already shareable between
  machines, which suits a pool of worker pods on shared storage.
- Our two plug-in DLLs (`addons/capture`, 257 lines; `addons/clock`, 332 lines) run inside the game
  under Wine as they are. They must be built on Windows or cross-compiled and shipped as files:
  today the installer builds them on the machine with Visual Studio's tools.

**Needs a Linux version** (about 20 files)

| Part | Files | On Linux | Effort |
|---|---|---|---|
| Game memory | `adapters/common/mem.py`, `adapters/rdr2/mem.py`; used by `gtav/timestep.py`, `rdr2/render_camera.py` | `/proc/<pid>/maps` and `/proc/<pid>/mem` (same addresses), from a process that started the game and stays its ancestor, or from inside Wine (`ptrace_scope` is 1 on our machine) | 1-2 days |
| Window, keys, screenshots | `adapters/common/window.py`, `adapters/rdr2/window.py`, `rdr2/scripts/game_input.ps1`; used by `gtav/settings_menu.py`, `tools/dlss5_skin_sweep.py` | X11 calls on the game's own display (key events, screenshots, window size) | 2-3 days |
| Launchers | `adapters/gtav/launch.py`, `adapters/cyberpunk/launch.py`, `rdr2/scripts/restart_game.ps1` | Start through Proton with the DLL overrides; Steam's and Rockstar's screens differ and need new handling | about 1 week |
| Installer | `capture/install/plan.py` (process list, registry, administrator prompt), `prereqs.py`, `components/addon.py` and `clock.py` (builds), `components/reshade.py`, each `adapters/*/install.py` (Steam's folder from the registry, settings under Documents and AppData) | Paths resolved inside the prefix, overrides written for the launch, prebuilt DLLs, prerequisites through protontricks, no machine-wide step. The step engine (copies, ini/json/xml edits, records, lockfiles) is portable | about 1 week |
| RDR2's PowerShell | `adapters/rdr2/scripts/*.ps1` (restart, input, reload, run a job, Lua check) and `capture.ps1` | Python and a shell wrapper; move RDR2 onto `adapters/common` | 2-3 days |
| Tools | `tools/upscaler_sweep.py` and a few others (process list and kill) | Through the layers above | under a day |

One thing gets easier: each game has its own display with nothing else on it, so the "window lost
focus" failures and their recovery code have no cause there.

**A shortcut for the feasibility test.** Running our Python inside the game's Wine prefix (the
Windows build of Python under Proton) should make the existing Win32 calls for memory, windows and
keys work as they are, since Wine implements them for processes in one prefix. Screenshots of a
Vulkan-rendered window probably would not work that way. This is an inference from how Wine works,
not something tried; it suits a quick test, not the final shape.

## Plan and estimate

Estimates assume one person who knows the code and has GPU access; they are judgement, not
measurement.

1. **Ask the cluster's admins** (no work): can the `rtxp6000` partition, or one node, run the 615
   driver; can jobs get `/dev/dri` and the driver's Wine-side DLSS files; can we run our own
   container image, or have a display server, a Vulkan loader and 32-bit libraries added; is
   there a way to run a pod with our image outside Slurm.
2. **Feasibility test, part A: done, passed 2026-11-23** (it took a day, not 3-5). In user space on driver
   580, cheapest checks first: the Vulkan loader and `vulkaninfo` see the RTX PRO 6000; a display
   server runs and a Vulkan test program presents to it; Proton starts a trivial exe; then
   Cyberpunk 2077 from its exe with Cyber Engine Tweaks, RED4ext, ReShade and our add-on, the goal
   one frame out with path tracing, DLAA and Ray Reconstruction. Needs downloads (Proton, a few
   `.deb` files, the driver package for the DLSS files) and the game folder copied over.
3. **Feasibility test, part B, after the admins' answer.** DLSS 5 through the OptiScaler fork on
   a 615 driver. Then RDR2 and GTA V Enhanced: do they start, does the Rockstar launcher log in
   and stay logged in, do Script Hook, RedLua and ReShade load.
4. **Port, 2-3 weeks.** The table above, a container image or a user-space bundle, and `capture
   verify` passing for each game. Done for Cyberpunk on 2026-11-23 (master `2d076b3`): the host
   layer, the window and memory layers, the installer and Cyberpunk's launcher, with the full
   `verify`, a near sweep, a short take over time and packaging passing on the cluster. Left for
   Cyberpunk: the frame rate. RDR2 and GTA V Enhanced were started the same day.
5. **Scale, 1-2 weeks.** Worker jobs on the folder queue with shared storage, restarts, accounts,
   monitoring.

## Sources

- CoreWeave: [CKS introduction](https://docs.coreweave.com/products/cks),
  [RTX PRO 6000 Blackwell instances](https://docs.coreweave.com/platform/instances/gpu/rtxp6000-8x),
  [GPU instances](https://docs.coreweave.com/platform/instances/gpu-instances),
  [Virtual Servers, v1 docs](https://v1.docs.coreweave.com/virtual-servers/getting-started)
- NVIDIA: [driver guide, DLSS under Proton](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/latest/gaming.html)
- DLSS 5: [supported cards](https://www.dlss5.net/dlss-5-supported-cards),
  [DLSS5VKLayer](https://github.com/bmitch87/DLSS5VKLayer),
  [dlss5-linux](https://github.com/pantsoftime/dlss5-linux),
  [DLSS5-Reshade-Linux-Steam](https://github.com/24high/DLSS5-Reshade-Linux-Steam)
- [OptiScaler manual installation](https://github.com/optiscaler/OptiScaler/wiki/Manual-Installation)
- [ReShade forum: add-on and DLSS crash under Proton](https://www.reshade.me/forum/troubleshooting/10203-solved-games-crash-when-reshade-addon-and-dlss-are-enabled-under-proton-linux)
- [VKD3D-Proton](https://github.com/HansKristian-Work/vkd3d-proton)
- [RED modding wiki: modding on Linux](https://wiki.redmodding.org/cyberpunk-2077-modding/for-mod-users/users-modding-cyberpunk-2077/modding-on-linux)
- [GTA V Enhanced ASI plug-in notes on Proton](https://github.com/newgenjalisco/GTA5Enhanced-UnlockRadioStations-ASI-Plugin),
  [ProtonDB: GTA V Enhanced](https://www.protondb.com/app/3240220)
- [ProtonDB: RDR2](https://www.protondb.com/app/1174180),
  [CachyOS forum: RDR2 Social Club error](https://discuss.cachyos.org/t/red-dead-redemption-2-using-proton-cachyos-wayland-shows-social-club-error-17/9659)
- Headless containers: [steam-headless](https://github.com/Steam-Headless/docker-steam-headless),
  [its DLSS report](https://github.com/Steam-Headless/docker-steam-headless/issues/268),
  [project-vulcan](https://github.com/CleveTok3125/project-vulcan)
