"""No-game test of the QC loop's reviewing side (capture/qc.py), with a stand-in reviewer
(tests/qc_fake_agent.py) and folders instead of S3, all in a temporary CAPTURE_OUT.

    uv run --project . python tests/test_qc.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="qc_test_")
os.environ["CAPTURE_OUT"] = os.path.join(TMP, "out")
sys.path.insert(0, REPO)

from capture import qc  # noqa: E402
from capture.util import read_json  # noqa: E402

FAKE = '"%s" "%s"' % (sys.executable, os.path.join(HERE, "qc_fake_agent.py"))
checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok)))
    print("%s  %s %s" % ("ok  " if ok else "FAIL", name, detail))


def fake_round(game, rnd):
    d = os.path.join(TMP, "sent", game, qc.round_name(rnd))
    os.makedirs(os.path.join(d, "t1", "frames"), exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"game": game, "round": rnd, "takes": ["t1"]}, f)
    with open(os.path.join(d, "t1", "capture_log.jsonl"), "w") as f:
        f.write(json.dumps({"name": "t001_c00", "frame": 1, "instant": 0.0}) + "\n")
    open(os.path.join(d, "t1", "frames", "t001_c00.jpg"), "wb").close()
    return d


try:
    # round 1 of three games, queued in this order; at most two reviewers at once
    for g in ("alpha", "beta", "broken"):
        qc.pull(g, 1, src=fake_round(g, 1))
    check("queue is first in first out", qc.queue() == ["alpha", "beta", "broken"], qc.queue())
    p = qc.prompt("alpha", 1, qc.settings(model="sonnet"))
    check("prompt fully filled", "{{" not in p and "**NPC accuracy.**" in p and qc.round_dir("alpha", 1) in p)
    qc.run(agent_cmd=FAKE, max_agents=2)
    runs = [json.loads(l) for l in open(os.path.join(qc.ROOT, "agent_runs.jsonl"))]
    starts = [r["game"] for r in sorted(runs, key=lambda r: r["start"])]
    most = max(sum(1 for o in runs if o["start"] <= r["start"] < o["end"]) for r in runs)
    check("three reviewers ran, alpha and beta first", sorted(starts) == ["alpha", "beta", "broken"] and starts[:2] in
          (["alpha", "beta"], ["beta", "alpha"]), starts)
    check("never more than two at once", most <= 2, "most at once: %d" % most)
    check("prompt reached the reviewer", all(r["prompt_has_definitions"] and r["prompt_has_round"] for r in runs))
    st = qc.load_state()["games"]
    check("states after the run", (st["alpha"]["state"], st["beta"]["state"], st["broken"]["state"]) ==
          ("reviewed", "reviewed", "failed"), {g: v["state"] for g, v in st.items()})

    f1 = read_json(os.path.join(qc.feedback_dir("alpha", 1), "findings.json"))
    ids = [f["id"] for f in f1["findings"]]
    check("ids given in the reviewer's order, sorted by confidence then extent",
          ids == ["alpha-002", "alpha-003", "alpha-001"], ids)
    md = open(os.path.join(qc.feedback_dir("alpha", 1), "report.md"), encoding="utf-8").read()
    check("report groups by category, a finding under each of its categories",
          md.count("### alpha-002") == 2 and "## npc_accuracy (1)" in md and "an NPC track log" in md)

    dest = os.path.join(TMP, "back")
    qc.push("alpha", 1, dest=dest)
    check("push copies the feedback, the game is in fixes",
          os.path.exists(os.path.join(dest, "alpha", "round-01", "feedback", "report.md")) and
          qc.game_state("alpha")["state"] == "fixes")

    # round 2: an earlier finding still present keeps its id, one is gone, ids carry on
    qc.pull("alpha", 2, src=fake_round("alpha", 2))
    p2 = qc.prompt("alpha", 2)
    check("round 2's prompt points at round 1's findings", os.path.join(qc.feedback_dir("alpha", 1), "findings.json") in p2)
    qc.run(agent_cmd=FAKE, max_agents=2)
    f2 = read_json(os.path.join(qc.feedback_dir("alpha", 2), "findings.json"))
    check("still present keeps its id", [(f["id"], f["status"]) for f in f2["findings"]] == [("alpha-002", "still present")],
          [(f["id"], f["status"]) for f in f2["findings"]])
    check("ids carry on", qc.game_state("alpha")["next_id"] == 4, qc.game_state("alpha")["next_id"])

    # a review with no coverage note is flagged; a redo moves the feedback aside and gives the ids again
    fb1 = read_json(os.path.join(qc.feedback_dir("beta", 1), "findings.json"))
    check("missing coverage flagged for every category", sum("coverage of" in p for p in fb1["problems"]) == len(qc.CATEGORIES),
          fb1["problems"])
    try:
        qc.enqueue("beta", 1)
        check("refuses to review a round again without --redo", False)
    except SystemExit:
        check("refuses to review a round again without --redo", True)
    qc.enqueue("beta", 1, redo=True)
    qc.run(agent_cmd=FAKE, max_agents=2)
    again = [f["id"] for f in read_json(os.path.join(qc.feedback_dir("beta", 1), "findings.json"))["findings"]]
    check("redo keeps the first try and gives the same ids", os.path.isdir(qc.feedback_dir("beta", 1) + ".try1") and
          sorted(again) == ["beta-001", "beta-002", "beta-003"], again)

    # an earlier finding reported at two places keeps its id once; the second gets a new id
    dup = os.path.join(qc.feedback_dir("alpha", 2), "findings.json")
    d2 = read_json(dup)
    d2["findings"].append(dict(d2["findings"][0]))
    with open(dup, "w") as f:
        json.dump(d2, f)
    d2 = qc.report("alpha", 2)
    pairs = sorted((f["id"], f.get("same_as")) for f in d2["findings"])
    check("a repeated earlier id becomes a new id, marked the same fault", pairs == [("alpha-002", None), ("alpha-004", "alpha-002")],
          pairs)

    # a note saying a take was only partly looked at is a gap, as a missing one is
    cov = {c: {"t1": "strips of every camera, full frames at clip frames 1, 15 and 30",
               "t2": "ten poses and the flagged ones at full size; other poses not opened"} for c in qc.CATEGORIES}
    full = qc.uncovered({"coverage": cov}, ["t1", "t2"])
    cov["geometry_accuracy"]["t1"] = "strip only"
    cov["lighting_continuity"]["t2"] = "metrics only (jitter 0.06)"
    cov["npc_accuracy"]["t1"] = "npc_tracks; not checked against the player's spot"
    cov["npc_continuity"]["t1"] = "strip of camera 00; near_moving not opened"
    cov["lighting_accuracy"]["t2"] = "sweep sheet; flagged poses 175-179 not opened at full size"
    thin = qc.uncovered({"coverage": cov}, ["t1", "t2"])
    check("thin notes are gaps, other poses not opened is not", full == {} and thin == {
        "geometry_accuracy": ["t1"], "lighting_continuity": ["t2"], "npc_accuracy": ["t1"], "npc_continuity": ["t1"],
        "lighting_accuracy": ["t2"]}, (full, thin))
    try:
        qc.resume("alpha", 1)
        check("continue refuses a round that is not reviewed", False)
    except SystemExit:
        check("continue refuses a round that is not reviewed", True)

    # one state at a time: no new round while one is being reviewed
    qc._update("beta", state="reviewing")
    try:
        qc.enqueue("beta", 2)
        check("refuses to queue a game under review", False)
    except SystemExit:
        check("refuses to queue a game under review", True)
    print(qc.status_text())
finally:
    shutil.rmtree(TMP, ignore_errors=True)

failed = [n for n, ok in checks if not ok]
print("%d checks, %d failed" % (len(checks), len(failed)))
sys.exit(1 if failed else 0)
