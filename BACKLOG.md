# Backlog

Work that is designed for but not built. Each item says what the current system does instead,
and what is already in place so the item can be added without reworking the pipeline.

## Next: per-game mod sets and an install CLI

**Now:** RDR2's mods (Script Hook RDR2 and its ASI loader, ReShade 6.8 with the capture add-on,
RedLua, Native Trainer) were installed by hand on one machine; the repository builds and deploys
only the add-on and the Lua scripts.

**Goal:** clone the repository on a fresh PC, install a legal copy of the game, run one command
for that game, then launch it and scout, run a worker, or open an agent session and iterate.

- **A mod set per game**, kept under `adapters/<game>/`: what to install, where, and which version,
  including visual mods chosen for capture quality.
- **OptiScaler with DLSS** for RDR2 (https://github.com/Skynizz/optiscaler-dlss5), loaded as an
  ASI by Script Hook's loader, with test images comparing the picture with and without it.
- **An install CLI** (`capture install <game> --game-dir ... --mods ...`): installs the set,
  including vendored files (Script Hook, ReShade and its add-ons, RedLua, Native Trainer,
  OptiScaler), builds and deploys the add-on and scripts, applies settings (RedLua autorun,
  natives patch, ReShade output folder), and runs checks (the loader's heartbeat, a test frame,
  colours against a screen grab). Third-party files whose licences do not allow redistribution
  are pointed to or downloaded instead of committed.

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

## Solved rigs: what is still approximate

Rigs are now solved per location (README: Rigs solved per location). Left open:

- **The scene is sampled by rays** from 11 points around the location: surfaces no ray reaches
  (behind a wall, inside a closed room) are missing, so the solver may think space behind them is
  free. Rays from more points, or from the solved cameras themselves before capture, would close
  most gaps.
- **Performers**: the solve uses a static stand-in box (the demo performer's size). With a real
  performer, its SMPL-X motion (and the SMPL-X model files) would replace the stand-in.
- **The player's own horse** (or anything else a game script owns) standing on a camera is never
  deleted, so the take is retaken until it moves or the retakes run out; moving such entities
  away instead of deleting them would avoid that.
