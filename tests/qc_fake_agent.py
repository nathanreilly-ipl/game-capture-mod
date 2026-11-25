"""A stand-in reviewer for tests/test_qc.py: reads the prompt on stdin, logs when it ran, writes
findings.json the way a reviewer would (none for the game "broken")."""
import json
import os
import sys
import time

prompt = sys.stdin.read()
game, rnd, fb = os.environ["QC_GAME"], int(os.environ["QC_ROUND"]), os.environ["QC_FEEDBACK_DIR"]
log = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(fb))), "agent_runs.jsonl")
t0 = time.time()
time.sleep(1.5)
with open(log, "a") as f:
    f.write(json.dumps({"game": game, "round": rnd, "start": t0, "end": time.time(),
                        "prompt_has_definitions": "**Lighting continuity.**" in prompt,
                        "prompt_has_round": os.environ["QC_ROUND_DIR"] in prompt}) + "\n")
if game == "broken":
    sys.exit(1)
findings = [
    {"categories": ["npc_accuracy"], "confidence": 1, "take": "t1", "cameras": ["c00"], "clip_frames": [3],
     "what": "a walker turns towards the parked player's spot"},
    {"categories": ["lighting_continuity", "geometry_continuity"], "confidence": 3, "take": "t1",
     "cameras": ["c00", "c16"], "clip_frames": [1, 2, 3], "what": "shadows flicker",
     "evidence": {"images": ["x.jpg"], "tool_runs": [{"command": "tools/temporal_flicker.py t1", "output": "pops 2"}]}},
    {"categories": ["lighting_accuracy"], "confidence": 3, "take": "t1", "cameras": ["c00"], "clip_frames": [1],
     "what": "screen-space reflections cut off at the frame's edge"},
]
gone = []
if rnd > 1:
    findings = [dict(findings[1], previous_id="%s-002" % game)]
    gone = [{"previous_id": "%s-001" % game, "why": "the walker no longer turns"}]
with open(os.path.join(fb, "findings.json"), "w") as f:
    json.dump({"reviewer": {"model": "fake"}, "findings": findings, "gone": gone,
               "requests": [{"kind": "tool", "what": "an NPC track log", "why": "to see the turn"}]}, f)
print(json.dumps({"result": "done", "is_error": False}))
