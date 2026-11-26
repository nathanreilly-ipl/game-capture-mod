# The QC loop: agent review of every game's captures, in rounds

Agreed with Nathan, 2026-11-24. Two machines, each with its own agent session:

- **CoreWeave** (the Linux node, the capturing machine): owns visual iteration for every game since
  2026-11-24. It fixes faults in a game's captures, retakes them, and sends their previews and QC
  data.
- **Windows** (the PC, the reviewing machine): brings new games to a working first worker capture,
  scouting, iteration tools and an initial set of photorealism mods, and runs the QC reviews:
  `capture qc` spawns reviewer agents and collects their findings.

For now the Windows session mediates every exchange:
- it runs the S3 transfers on its side and its own commits and pushes;
- it talks to the CoreWeave session through Claude's cross-session messages.

Automatic back-and-forth, with no session in the middle, is in BACKLOG.

## Goal

Each game Nathan picks goes through its own loop:
1. The CoreWeave session fixes faults in the game's captures and sends their previews and QC data
   over S3.
2. A reviewer agent on Windows goes through them for every fault in six categories, and for plausibility, using the
   repository's QC tools, and its findings go back over S3.
3. CoreWeave fixes, retakes and sends new previews.

Each game repeats this for the number of rounds Nathan sets for it, independently of the other
games. Round 1 of every game is its state when the loop started: the previews of the takes that
existed then.

## The categories

The three aspects (geometry, lighting, NPCs) each split into continuity and accuracy; a seventh
category, plausibility, stands on its own.

| | Continuity (frames over time, and frames of one instant) | Accuracy (each frame against itself and the game) |
|---|---|---|
| **Geometry** (NPC rigs included) | meshes changing shape abruptly, flickering in and out, appearing or disappearing, cloth vibrating, objects flung by physics | floating objects, missing meshes, implausible deformation |
| **Lighting** | exposure changes, shadow, light or texture flicker, lighting changing faster than real light could | incorrect or missing shadows, unlit sources, mislit surfaces, cut-off screen-space reflections, noise, washed-out colours, wrong exposure |
| **NPC** (people, animals, vehicles) | abrupt stops, animation or pathfinding glitches, implausible motion (a cart lifting off) | behaviour with no plausible reason, especially reacting to the hidden player |

The full definitions, which every reviewer gets word for word, are in `docs/qc/reviewer.md` (the
reviewer's prompt), the one place they are kept. In findings the categories are written
`geometry_continuity`, `geometry_accuracy`, `lighting_continuity`, `lighting_accuracy`,
`npc_continuity`, `npc_accuracy`, `plausibility`.

**Plausibility** (Nathan, 2026-11-25): anything in the scene hyper-specific to the game's world
that does not exist, or is very uncommon, in real life (Death Stranding: chiral growths with black
particles, beacons of light into the sky, holograms, the game's signs). The captures stand in for
real footage, so such things are cut from them where the game allows (AGENTS.md section 1,
"Plausible"); reviewers report what is still in view.

## Roles

- **Nathan:** chooses which games take part, their starting order, and the number of rounds per
  game.
- **CoreWeave session:**
  - surveys and builds QC tools;
  - captures, fixes, commits and pushes (pushes are part of the loop: Nathan, 2026-11-24);
  - chooses and uploads each game's QC data;
  - triages findings.
- **Windows session (orchestrator):**
  - pulls the repository and each game's round;
  - keeps the QC queue and runs the reviewers (`capture qc`);
  - uploads each game's feedback as soon as its QC ends, and tells CoreWeave;
  - adds round summaries to the work-docs page.
- **Reviewers:** agents started by `capture qc` as separate processes, one per game QC.
  - By default headless Claude Code (`claude -p`) on Sonnet, at most two at once. The model, the
    number at once and the command are this machine's settings (`capture qc config`).
  - Each covers all seven categories over every previewed take of its game in that round, and all the
    QC data sent for it.
  - They read images and logs and run the QC tools under `tools/` on that data. They never touch a
    game.

## Games, queues and order

- **Each game is in exactly one state at a time:** in QC (queued or running on Windows) or in fixes
  (on CoreWeave). That is the only lock. A game in fixes is never in QC, and the reverse.
- **Games are independent.** Each has its own round counter, its own S3 folder and its own
  feedback. Different games can be in different rounds at the same moment.
- **Nathan's starting order** is the order games enter the loop. CoreWeave starts their first fixes
  in that order, and the first QCs queue on Windows in that order.
- **After the start, events drive the order:**
  - a game enters the QC queue when its previews arrive;
  - it leaves QC, and its feedback goes back, the moment its reviewer finishes;
  - CoreWeave takes up a game's fixes when its feedback arrives, in whatever order it judges best
    (the node runs one game at a time on the shared Steam account).
- **The Windows QC queue** is first in, first out, with `max_agents` reviewer slots (2 by default).
  A game whose previews arrive while every slot is busy waits for the first free one.

Example, with the starting order RDR2 → GTA V:

```
RDR2:  fixes1 ─► QC1 ──────────────────► fixes2 ...
GTAV:     fixes1 ─► QC1 ─► fixes2 ─► QC2 ─► ...
```

A valid sequence of events: GTA V QC1 done, GTA V fixes1 done, RDR2 QC1 done, GTA V QC2 done, RDR2
fixes2 done. GTA V can run ahead of RDR2 because nothing ties their rounds together.

## The loop (per game)

```
CoreWeave: 0. QC tool survey and build (once for all games, before the first fixes)
           1. fixes for this game (any tools built along the way go under tools/ too)
           2. commit, push
           3. this game's previews and QC data to S3, then a message to the Windows session
Windows:   4. git pull (new tools) + capture qc pull <game> <round>
           5. capture qc run: one reviewer for this game, with its data and the tools
           6. capture qc push <game> <round> as soon as its QC ends, then a message to CoreWeave
CoreWeave: 7. triage -> back to 1 for this game
```

### 0. QC tool survey and build (CoreWeave, once)

Before the first fixes, the CoreWeave session reviews what reviewers will need and builds it: new
tools under `tools/`, or improvements to existing ones (`temporal_flicker.py`, `sweep_flicker.py`,
`clip_strip.py`, `hold_step_check.py`, `compare_sheets.py`, ...). Candidates:

- an **NPC track log**: per clip frame, each person, animal and vehicle near the rig by id, with
  position, heading and bounding box (the adapters' `obstacles()` already returns these). It is
  recorded at capture time; the tool reads it and flags speed and acceleration outliers, stops,
  flying, and paths bending around the parked player's spot;
- an **evidence tool**: time strips of one camera across clip frames, difference maps between
  neighbouring clip frames, same-instant pairs from the near sweep, crops where metrics flag
  something, and a timestamp table per take;
- whatever else the survey finds useful for the categories.

Every QC tool must run on a take's transferred data alone, with no game, on Windows as well as
Linux. Each has a one-line entry in `docs/VISUAL_CHECKS.md` ("The tools") saying what it finds and
which categories it serves.

### 1. Fixes (CoreWeave)

CoreWeave fixes the game's faults from its own checks and, from round 2 on, from the triaged
findings. It retakes the same locations and rigs (the fixed comparison set, below), so rounds
compare like with like. Any tool it builds to find or check a fix goes under `tools/` and is
available to every reviewer from the next QC run, whatever the game.

### 2. Commit and push (CoreWeave)

Fixes and tools are committed and pushed, so the Windows session gets the tools with a git pull.

### 3. Previews and QC data to S3 (CoreWeave)

Upload to `s3://data-interns/nathan.reilly/transfer-qc/<game>/round-NN/<take>/` (NN two digits:
`round-01`), then message the Windows session naming the game and round.

**Always sent, per take:**

- the timestamped frames: full-resolution frames of every fixed camera at every clip frame and a set
  of near-sweep poses;
- `capture_log.jsonl` and `steps.jsonl`, which carry each frame's clip frame and game time.

**CoreWeave's choice, per round:** any other data it judges would help QC, added or dropped from
round to round. For example:

- preview videos and sheets (sweep, time, ring);
- `shots.json`, `take.json`, the NPC track log;
- metric reports, tool outputs it has already run, close-ups of a known problem spot.

It also uploads `s3://.../transfer-qc/<game>/round-NN/manifest.json` listing:

- the game, the round number, the takes, and the commit they were made with (`"commit"`);
- what data is included per take, and what was added or dropped since the last round and why;
- what changed since the last round;
- the tools added or changed, so the reviewer knows what is new.

From round 2 on it adds its triage of the last round's findings as `triage.json` beside the
manifest.

### 4. Pull (Windows)

```powershell
git pull origin master                 # the manifest's commit: the new tools
.\capture.ps1 qc pull <game> <round>   # S3 -> out\qc\<game>\round-NN\, then the S3 copy is deleted
```

`qc pull` warns when the checkout lacks the manifest's commit. The game joins the QC queue
(`capture qc status`).

### 5. QC run (Windows)

```powershell
.\capture.ps1 qc run                   # reviewers for the queue, first in first out, max_agents at once
.\capture.ps1 qc continue <game> <round>   # a reviewed round's reviewer resumed where its coverage is thin
```

When a slot is free, the game at the head of the queue gets a reviewer. A game queued while `run`
is going (a pull in another terminal) is picked up, and `run` returns once the queue is empty and
every reviewer has finished. The reviewer's prompt is `docs/qc/reviewer.md` with the game's round
filled in (`capture qc prompt <game> <round>` prints it). It gets:

- all seven category definitions;
- `docs/VISUAL_CHECKS.md`, as "known faults: check whether they're still there";
- every take of its game in the round, with all the QC data sent for them, and the manifest;
- the list of QC tools and what each finds, with permission to run them on the data;
- the game's findings from its last round, and CoreWeave's triage of them, to mark as still
  present or gone.

The reviewer is told to:
- go through all seven categories, one at a time, over every take of the game;
- report every possible fault (a missed fault is worse than a false one);
- report lower-confidence suspicions too (guessing is allowed);
- rate each finding's confidence from 1 to 3:
  - 1: possible, worth a look;
  - 2: likely;
  - 3: certain, with the evidence showing it plainly;
- note any tool or data it wished it had. These go into the feedback as requests for steps 1 and 3.

A reviewer may read anything and run `uv run` (the repository's tools); it may write only its
feedback. It runs with no MCP servers (`--strict-mcp-config`). The tools it may use are this
machine's setting `allowed_tools`.

**Passes.** A reviewer writes, per category and take, what it did (`coverage`). When it stops while
a take is missing there or its note is thin, `qc` resumes the same Claude session
(`claude -p --resume`) with the list of what is left, up to `max_passes` passes (6). Only then does
the review end. A note is thin when it says "not checked" or "not examined", that only a sheet, a
strip or metrics were looked at, or that flagged poses, cameras or full-size frames were not opened
(`THIN` in `capture/qc.py`); "other poses not opened" is not thin, since a sweep's minimum is ten
poses and the flagged ones. `capture qc continue <game> <round>` gives a round that is already
reviewed the passes it is owed, for instance after the rule changed.

Each pass's output is kept: `agent_output.json`, then `agent_output_pass2.json` and so on. The first
reviews of 2026-11-25 stopped after 1.2 to 1.7 minutes and 22 to 37 turns, even with the coverage
minimum in the prompt, and said themselves what they had skipped. That is why the passes exist.
Until the thin-note rule (2026-11-25 evening), only a missing take or a note starting "not checked"
counted: 44 of the 360 notes of the first ten rounds were thin and went back to CoreWeave as they
were (GTA V's round 2: 6 of 36, in one pass of 40 turns).

### 6. Feedback (Windows, as soon as the game's QC ends)

The reviewer writes `out\qc\<game>\round-NN\feedback\findings.json`. When it ends, `qc run` (or
`capture qc report <game> <round>`):
- gives each finding an id that persists across the game's rounds (`<game>-NNN`);
- sorts the findings by confidence, then by how much of the take each touches (cameras × clip
  frames);
- writes a readable `report.md`, grouped by category. A finding with more than one category appears
  under each.

Then:

```powershell
.\capture.ps1 qc push <game> <round>   # feedback -> s3://.../transfer-qc/<game>/round-NN/feedback/
```

`qc push` sends `findings.json`, `report.md` (with the reviewer's tool and data requests), the
reviewer's evidence (`work/`: strips, crops and scripts the findings point to, about 30 MB a game
in round 1), the prompt and the agent's output, and the game is in fixes. The Windows session then messages the
CoreWeave session naming the game and round, with the summary line `qc push` prints.

### 7. Triage (CoreWeave)

Reviewers are allowed false positives, so CoreWeave checks each finding against its data. It marks
each one fixed, not a fault (with the reason) or open. The game's next round goes back to step 1,
with the open findings and the tool and data requests as input. Its triage travels with the next
round (`triage.json`).

## One finding

Each finding records:

- id, game, round, categories, confidence 1–3;
- take, cameras, clip frames, game times;
- what is wrong, in one or two sentences;
- evidence: image paths, tool runs (command and output) and the numbers that support it;
- suspected cause (optional);
- status: new or still present (the reviewer gives `previous_id`). Earlier findings that are gone
  are listed under `gone`. CoreWeave's triage adds fixed, not a fault or open.

## Rounds and stopping

- Nathan sets the number of rounds per game.
- Optionally, a game stops early when a round has no confidence-3 findings and no confidence-2
  finding survives triage.
- A game that has finished its rounds leaves the loop; the others carry on.
- Each game's round summaries (counts per category and confidence, what was fixed, what is open,
  tools and data added) go on the work-docs page.

## Fixed comparison set

Per game, a fixed set of locations and rigs that every round retakes:

- dense city with screens or signs;
- an interior or covered market;
- open land with grass and foliage;
- water;
- night.

Each gets a 30-clip-frame ring or moving-camera take plus a near sweep.

## Settings on the Windows machine

`capture qc config` shows them; options set them in `out/config.json` (section `qc`):

| setting | default | what |
|---|---|---|
| `--max-agents` | 2 | reviewers running at once |
| `--model` | `sonnet` | the reviewers' model |
| `--claude` | on PATH, else `~/.local/bin/claude(.exe)` | the Claude Code command |
| `--agent-cmd` | none | any other reviewer command instead: it gets the prompt on stdin and `QC_GAME`, `QC_ROUND`, `QC_ROUND_DIR`, `QC_FEEDBACK_DIR` in its environment, and must write `findings.json` there (one pass only) |
| `--max-passes` | 6 | passes of one reviewer while its coverage has gaps |
| `--s3-root` | `s3://data-interns/nathan.reilly/transfer-qc` | where rounds are exchanged |
| `--s3-endpoint` | none (the aws configuration's) | the S3 endpoint |

`run` and `review` take `--max-agents`, `--model`, `--claude` and `--agent-cmd` for one run without
changing the settings. A reviewer that runs longer than `timeout_min` (240) is stopped. A game
whose reviewer writes no usable `findings.json` is marked failed. `capture qc enqueue <game>
<round>` queues it again.

A review that stopped short is caught before its feedback goes back. Its `coverage` must name, for
each category, every take of the round (or say "all takes") with a note that is not thin, and
`report.md` lists every category that does not as a problem. `capture qc enqueue <game> <round> --redo` reviews the round again:
- the first try is kept as `feedback.try1`;
- the round's ids are given out again from the same number.

The first reviews of round 1 (2026-11-25) were short: 1.2 to 1.7 minutes, 22 to 27 turns and about
$0.60 each, mostly from the sheets. The prompt now sets the least each review covers: every take's
evidence (`tools/qc_evidence.py`), metrics and known spots; a time strip of every camera; full
frames at set clip frames and wherever a metric points; ten sweep poses; every person followed. It
also tells the reviewer to expect a long review, and the passes above see it through.

## Cost

- One reviewer per game per round, at most `max_agents` at a time.
- A reviewer covers seven categories over every take of its game, so images are the main cost. It
  starts from the tools' outputs, strips and difference maps, and opens full frames only where
  those point.
- If a game's data is too much for one reviewer, CoreWeave can send less per round (its choice in
  step 3), or the game's takes can be split over consecutive reviewers (BACKLOG). That still keeps
  at most `max_agents` running at once.
