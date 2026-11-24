"""Do people move during the held world's time steps?

    uv run --project . python -m adapters.witcher3.probes.people_step_probe [--location <id>] [--steps 30]

At a place with people walking: their positions with the world running (two looks 1 s apart, for
scale), then the world held, positions, `steps` steps of 1/30 s, positions again. Prints how many
people moved and how far, in each case, and the engine time the steps added.
"""
import argparse
import time

import numpy as np

from capture import locations as locs
from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session, parse_kv, vec


def positions(s, centre, radius=25.0):
    out = []
    for line in s.cmd("ents", centre[0], centre[1], centre[2], radius, timeout=20).data:
        head = line.partition(" tags=")[0]
        e = parse_kv(head)
        if e.get("kind") in ("npc", "actor"):
            out.append(np.array(vec(e["pos"])))
    return out


def moved(a, b):
    """For each person in b, the distance to the nearest person in a (people are not named)."""
    if not a or not b:
        return []
    return [min(float(np.linalg.norm((p - q)[:2])) for q in a) for p in b]


def report(label, d, seconds):
    d = np.array(d)
    if not len(d):
        print("%-28s nobody" % label)
        return
    print("%-28s %d people: %d moved more than 5 cm, median %.3f m, max %.3f m (%.2f s)"
          % (label, len(d), int((d > 0.05).sum()), float(np.median(d)), float(d.max()), seconds))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="witcher3-hierarch-square-centre-001")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--op", default="stepe", help="stepe (the world runs between holds, even frames: the capture method), stepw (the same, shrinking frames) or step (the photo mode's tick)")
    ap.add_argument("--nophoto", action="store_true", help="hold with our pause alone, photo mode off")
    a = ap.parse_args()
    loc = next(l for l in locs.load(capture_paths.LOCATIONS)["locations"] if l["id"] == a.location)
    c = loc["position"]
    s = Session()
    ex = paths.exchange()
    s.close_menu()
    s.cmd("savelock", 1)
    s.cmd("unfreeze")
    s.cmd("teleport", c[0], c[1], c[2] + 0.1, loc.get("facing_deg", 0.0))
    time.sleep(12)
    try:
        p0 = positions(s, c)
        time.sleep(1.0)
        p1 = positions(s, c)
        report("world running, 1 s apart", moved(p0, p1), 1.0)
        frame_s = round(1.0 / max(1.0, frames.frame_rate(ex, 0.5)), 5)
        s.cmd("hide", 1)
        if a.nophoto:
            s.cmd("pause", 1)        # our pause alone, no photo mode
        else:
            s.cmd("freeze")
        frames.wait(ex, 30)
        t0 = s.state()
        h0 = positions(s, c)
        time.sleep(2.0)
        h1 = positions(s, c)
        report("held, 2 s apart, no step", moved(h0, h1), 0.0)
        each = []
        for _ in range(a.steps):
            e0 = s.state()
            mark = s.log_size()
            if a.op == "stepe":
                r = s.cmd("stepe", 1.0 / 30, 8, frame_s)
            else:
                r = s.cmd(a.op, 1.0 / 30)
            if a.op in ("stepw", "stepe"):
                done = s.wait_line("t", r.seq, mark, timeout=30.0)
                if done is None:
                    raise SystemExit("a step did not end")
            frames.wait(ex, 2)
            e1 = s.state()
            each.append((float(e1["engine_base"]) + float(e1["engine_rel"])) - (float(e0["engine_base"]) + float(e0["engine_rel"])))
            if e1.get("held") != "1":
                raise SystemExit("the world is not held after a step")
        t1 = s.state()
        h2 = positions(s, c)
        dt = (float(t1["engine_base"]) + float(t1["engine_rel"])) - (float(t0["engine_base"]) + float(t0["engine_rel"]))
        report("held, after %d %s steps" % (a.steps, a.op), moved(h1, h2), dt)
        e = np.array(each) * 1000
        print("each step: %.4f to %.4f ms (mean %.4f) for %.4f asked" % (e.min(), e.max(), e.mean(), 1000.0 / 30))
        h3 = positions(s, c)
        time.sleep(2.0)
        h4 = positions(s, c)
        report("held again, 2 s apart", moved(h3, h4), 0.0)
    finally:
        s.cmd("pause", 0)
        s.cmd("unfreeze")
        s.cmd("hide", 0)
        s.cmd("savelock", 0)


if __name__ == "__main__":
    main()
