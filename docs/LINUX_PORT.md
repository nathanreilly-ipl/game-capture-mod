# Porting capture_mod to CoreWeave Linux: a survey

Surveyed 2026-11-22 from the code at master `416cab2` and from web research that day. Nothing here
was built or tested on Linux. Version-specific findings (drivers, Proton builds, DLSS 5 support)
change quickly: check them again before relying on them.

## Verdict

Feasible, through Proton (the games are Windows-only), but the largest unknowns are outside our
code: DLSS 5 on Linux, and Rockstar's launcher without a person at a screen. Estimate: a 3-5 day
feasibility test, then 4-6 weeks for all three games if the test finds no blocker; Cyberpunk 2077
alone about 2 weeks. Windows on CoreWeave is ruled out (Nathan, 2026-11-22), so Linux is the only
route there; the nodes have RTX PRO 6000 cards.

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
   for add-ons with DLSS under Proton (above) matter directly.
5. **Untested under Proton:** NaturalVision Enhanced (its own plug-in, 95 shader replacements, a
   DLC loader), Reality Redemption 2 (RDR2's hardware ray tracing, a ReShade add-on), our clock
   plug-in (it patches the import tables of the game's exe and its video player, which should
   behave the same under Wine), GTA V Enhanced's protection that crashes the game on purpose, and
   RedLua's faults.
6. **The driver's libraries inside a container.** A headless Steam image has an open report of
   DLSS becoming unavailable because Proton could not find the driver's DLSS libraries in the
   container. Whether CoreWeave's pods get the driver's graphics and DLSS libraries needs asking.

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
| Game memory | `adapters/common/mem.py`, `adapters/rdr2/mem.py`; used by `gtav/timestep.py`, `rdr2/render_camera.py` | `/proc/<pid>/maps` and `/proc/<pid>/mem` (same addresses); the container needs ptrace permission | 1-2 days |
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

1. **Ask CoreWeave** (no work): do pods get the NVIDIA driver's graphics, display and DLSS
   libraries; can our RTX PRO 6000 node pool run the 615 driver branch.
2. **Feasibility test, 3-5 days.** One RTX PRO 6000 GPU on the 615 driver, one container with
   Proton and a headless display. Cyberpunk 2077 from its exe with Cyber Engine Tweaks, RED4ext, ReShade and
   our add-on: get one frame out with path tracing, DLAA and Ray Reconstruction; then try DLSS 5
   through the OptiScaler fork. Then RDR2 and GTA V Enhanced: do they start, does the Rockstar
   launcher log in and stay logged in, do Script Hook, RedLua and ReShade load.
3. **Port, 2-3 weeks.** The table above, a container image, and `capture verify` passing for each
   game.
4. **Scale, 1-2 weeks.** Worker pods on the folder queue with shared storage, restarts, accounts,
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
