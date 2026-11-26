"""The QC tools on made-up data (no game): tools/npc_tracks.py flags what it should and nothing else.

    uv run --project . python tests/test_qc_tools.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import npc_tracks  # noqa: E402


def thing(i, kind, x, y, z=0.0):
    return {"id": i, "kind": kind, "owned": False, "center": [x, y, z], "axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "half": [0.3, 0.3, 0.9]}


def main():
    tmp = tempfile.mkdtemp()
    take = os.path.join(tmp, "take")
    os.makedirs(take)
    rows = []
    for f in range(1, 31):
        things = [thing(1, "human", 0.05 * f, 0.0)]                         # walks 1.5 m/s, steady
        things.append(thing(2, "human", 5.0 + (3.0 if f >= 15 else 0.0), 5.0))   # jumps 3 m in one step
        if f < 20:
            things.append(thing(3, "human", -5.0, 0.0))                      # vanishes at 20
        x4 = 10.0 + 0.05 * min(f, 10)                                        # walks, then stops dead at the player
        things.append(thing(4, "human", x4, 0.0))
        things.append(thing(5, "vehicle", -10.0, 10.0, 0.0 if f < 25 else 1.2))   # a cart lifting off
        if f >= 10:
            things.append(thing(6, "human", 0.0, -7.6 + 0.05 * (f - 10)))  # walks in at the reach's edge (7.85 m)
        things.append(thing(7, "human", -3.0, -3.0))                     # two standing inside each other
        things.append(thing(8, "human", -3.1, -3.0))
        rows.append({"frame": f, "instant": 100 + f / 30.0, "things": things})
    with open(os.path.join(take, "npc_tracks.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    json.dump({"subject_position": [10.6, 0.5, 0.0]}, open(os.path.join(take, "take.json"), "w"))
    # a camera at (0.6, -1.5) looking +y at the walker id 1 (at about 0.6, 0 around clip frame 12), and one
    # looking away
    json.dump({"placement": {"rig_center_world": [0.0, 0.0, 0.0]}, "steps": [{"frame": f, "shots": [
        {"name": "t%03d_near_temporal_00_000" % f, "pos": [0.6, -1.5, 0.9], "fwd": [0.0, 1.0, 0.0], "vfov_deg": 60},
        {"name": "t%03d_near_temporal_16_000" % f, "pos": [0.6, -1.5, 0.9], "fwd": [0.0, -1.0, 0.0], "vfov_deg": 60}]}
        for f in range(1, 31)]}, open(os.path.join(take, "shots.json"), "w"))
    rep = npc_tracks.analyse(take)
    assert rep["tracks"] == 8, rep["tracks"]      # linked by position (ids are not trusted): one track each
    starts = {1: (0.05, 0.0), 2: (5.0, 5.0), 3: (-5.0, 0.0), 4: (10.05, 0.0), 5: (-10.0, 10.0), 6: (0.0, -7.6),
              7: (-3.0, -3.0), 8: (-3.1, -3.0)}
    by = {}
    for tr in rep["by_track"]:
        x, y = tr["path"][0]
        who = min(starts, key=lambda k: (starts[k][0] - x) ** 2 + (starts[k][1] - y) ** 2)
        by[who] = {f["flag"] for f in tr["flags"]}
    assert by[1] == set(), by
    assert "teleport" in by[2], by
    assert "pop" in by[3], by
    assert {"stop", "player"} <= by[4], by
    assert "lift" in by[5], by
    assert by[7] == {"overlap"} and by[8] == {"overlap"}, by
    assert len(rep["overlaps"]) == 30, len(rep["overlaps"])     # the one pair, every clip frame
    assert by[6] == set(), by                     # entering at the edge is not a pop ...
    ev = {(e["frame"], e["what"], e["at"]) for e in rep["events"]}
    assert (10, "enters", "edge") in ev and (20, "vanishes", "inside") in ev, rep["events"]   # ... but an event
    close = rep["close_to_camera"]
    assert close and all(c["camera"] == "near_temporal_00" and c["id"] == 1 for c in close), close   # id: the list position
    assert 12 in {c["clip_frame"] for c in close}, close
    npc_tracks.draw(rep, os.path.join(tmp, "map.png"))
    assert os.path.getsize(os.path.join(tmp, "map.png")) > 1000
    print("1 ok: npc_tracks flags a teleport, a vanishing person, a dead stop at the hidden player, a lift; "
          "a steady walker unflagged; the walker close in front of one camera, not the one looking away; one walking in at "
          "the reach's edge listed, not flagged; two people inside each other flagged (%s)" % rep["flag_counts"])


if __name__ == "__main__":
    main()
