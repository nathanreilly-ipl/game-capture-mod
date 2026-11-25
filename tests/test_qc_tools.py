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
        rows.append({"frame": f, "instant": 100 + f / 30.0, "things": things})
    with open(os.path.join(take, "npc_tracks.jsonl"), "w") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    json.dump({"subject_position": [10.6, 0.5, 0.0]}, open(os.path.join(take, "take.json"), "w"))
    rep = npc_tracks.analyse(take)
    by = {tr["track"]: {f["flag"] for f in tr["flags"]} for tr in rep["by_track"]}
    assert by["id:1"] == set(), by
    assert "teleport" in by["id:2"], by
    assert "pop" in by["id:3"], by
    assert {"stop", "player"} <= by["id:4"], by
    assert "lift" in by["id:5"], by
    npc_tracks.draw(rep, os.path.join(tmp, "map.png"))
    assert os.path.getsize(os.path.join(tmp, "map.png")) > 1000
    print("1 ok: npc_tracks flags a teleport, a vanishing person, a dead stop at the hidden player, a lift; "
          "a steady walker unflagged (%s)" % rep["flag_counts"])


if __name__ == "__main__":
    main()
