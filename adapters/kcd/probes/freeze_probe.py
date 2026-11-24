"""Which of the game's switches holds the world still while frames keep rendering?

    uv run --project . python -m adapters.kcd.probes.freeze_probe [--hold 5] [--candidates scale0,scale1e-6,pause]

For each candidate: people within 30 m of the player, where they are, the game's timer
(System.GetCurrTime), the world clock (Calendar.GetWorldTime) and the frame counter, then the same
--hold real seconds later; the world let go again between candidates. Candidates:
    scale0      t_Scale 0
    scale1e-6   t_Scale 0.000001
    pause       CryAction.PauseGame(true)
    worldtime   Calendar.SetWorldTimePaused(true) alone (the clock only)
Reported: how many people moved more than 1 cm and the most any moved, timer and clock change,
frames rendered meanwhile.
"""
import argparse
import json
import time

import numpy as np

from ..session import Session, parse_kv, vec


def people(s, centre, r=30.0):
    out = {}
    for line in s.cmd("people", centre[0], centre[1], centre[2], r).data:
        parts = line.split()
        out[parts[0]] = np.array(vec(parts[1]))
    return out


def snap(s, centre):
    st = s.cmd("state").state
    return {"people": people(s, centre), "time": float(st.get("time", 0)), "gt": float(st.get("gt", 0)),
            "frame": int(st.get("frame", 0))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=5.0)
    ap.add_argument("--candidates", default="scale0,scale1e-6,pause,worldtime")
    a = ap.parse_args()
    s = Session()
    centre = vec(s.cmd("state").state["player"])
    rows = []
    on = {"scale0": "System.SetCVar('t_Scale', 0)", "scale1e-6": "System.SetCVar('t_Scale', 0.000001)",
          "pause": "CryAction.PauseGame(true)", "worldtime": "Calendar.SetWorldTimePaused(true)"}
    off = {"scale0": "System.SetCVar('t_Scale', 1)", "scale1e-6": "System.SetCVar('t_Scale', 1)",
           "pause": "CryAction.PauseGame(false)", "worldtime": "Calendar.SetWorldTimePaused(false)"}
    try:
        for c in a.candidates.split(","):
            s.eval(on[c])
            time.sleep(0.5)
            a0 = snap(s, centre)
            t0 = time.time()
            time.sleep(a.hold)
            a1 = snap(s, centre)
            real = time.time() - t0
            s.eval(off[c])
            moved = [float(np.linalg.norm(a1["people"][k] - p)) for k, p in a0["people"].items() if k in a1["people"]]
            row = {"candidate": c, "people": len(moved), "moved_over_1cm": sum(m > 0.01 for m in moved),
                   "max_moved_m": round(max(moved), 4) if moved else None, "timer_s": round(a1["time"] - a0["time"], 6),
                   "clock_s": round(a1["gt"] - a0["gt"], 2), "frames": a1["frame"] - a0["frame"], "real_s": round(real, 2)}
            rows.append(row)
            print(json.dumps(row))
            time.sleep(2.0)
    finally:
        for c in on:
            s.eval(off[c])
    return rows


if __name__ == "__main__":
    main()
