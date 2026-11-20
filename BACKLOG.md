# Backlog

Work that is designed for but not built. Each item says what the current system does instead,
and what is already in place so the item can be added without reworking the pipeline.

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
  (window size, frame size, ReShade preset, settle ticks) in `take.json`.
- Adapters declare capabilities (`capture/adapter.py`); `snapshot` / `restore` are optional
  and nothing calls them yet.

## Rig solver format, solved per location

**Now:** a rig is a list of poses (`camrig/v1`), solved once by the rig repository on an open
floor. Locations are chosen by a person or an agent to be open enough for the rig as solved,
so no camera stands inside the scene.

**Goal:** a rig given as a solver and its settings, solved at each location against the scene
around the subject, so the rig's own rules (lift or shrink a ring, drop a blocked group, decline
the location) decide what fits. In the rig repository these rules are Python code
(`camrigs/rigs/<key>.py`, `solve(ctx, cfg)`), not data. A rig's input is the scene's triangles
(`--obj`, metres, +Y up), the performers' motion, a seed and a key; its output is a `camrig/v1`
file. A solver spec is therefore a reference to that code plus its settings:

```jsonc
{"schema": "camrig_solver/v1", "solver": "yiming_stdm", "repo": "gamecapture-camera-rigs-huixin@<commit>",
 "config": {}, "seed": 1234, "subject": {"height_m": 1.8, "motion": "static"}}
```

Needed:

- **Scene around the subject** from the game: a mesh within the rig's reach (12 m for ST-DM),
  in the rig's frame, from collision queries or depth captures. A game adapter capability.
- **A stand-in subject** for no-performer captures: the rigs size their rings from the subject's
  height and need a motion; a static figure of a fixed height.
- **Solve step** that runs the rig repository's solver for the location and stores the solved
  `camrig/v1` file with the take, along with the rig's record of what the scene changed.

**In place (2026-11-20):**

- A job names a *rig source* (`capture/rigs.py`). Today the only kind is a `camrig/v1` pose
  file (`"kind": "camrig"`); `"kind": "solver"` is reserved and raises until it is built.
  `resolve()` turns a source into a `camrig/v1` rig for the location before the shot list is
  built, so everything after it only ever sees poses.
- Locations have a `scene` field (null for now) for scene data captured once and reused by
  every rig solved there; adapters can declare a `scene_mesh` capability.
