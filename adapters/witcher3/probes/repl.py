"""Sends commands of our session script (ws/capture_mod.ws) to the running game and prints the answers.

The Witcher 3 has no eval: its scripts are compiled when the game starts. What can be tried
without a restart is every cm_ command the script already has; a new one needs the script
changed, `capture install witcher3 --only scripts` and a restart (python -m adapters.witcher3.launch).

    uv run --project . python -m adapters.witcher3.probes.repl state "pose 944 596 36 -20 60 0 60" "wait 60" "shot view1"

    <op> <args...>     cm_<op>(seq, args...)       e.g.  freeze | unfreeze | step 0.0333333 | hud 0
    wait <frames>      let frames pass (counted by the capture add-on)
    shot <name>        a frame through the add-on, saved under out/probes/witcher3/repl/<name>.png
    fps                the frame rate over one second
"""
import os
import sys

from capture import paths as capture_paths

from ...common import frames
from .. import paths
from ..session import Session


def main(argv):
    s = Session()
    ex = paths.exchange()
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "repl")
    for line in argv:
        parts = line.split()
        op, args = parts[0], parts[1:]
        if op == "wait":
            print("> wait %s: %.1f frames/s" % (args[0], frames.wait(ex, int(args[0]))))
        elif op == "fps":
            print("> %.1f frames/s" % frames.frame_rate(ex, 1.0))
        elif op == "shot":
            from PIL import Image
            a = frames.shoot(ex, "repl/" + args[0])
            os.makedirs(out, exist_ok=True)
            dst = os.path.join(out, args[0] + ".png")
            Image.open(a["path"]).save(dst)
            os.remove(a["path"])
            print("> shot %s (%dx%d, frame %d)" % (dst, a["width"], a["height"], a["frame"]))
        else:
            def num(v):
                if "_" in v:          # a packed list ("1_2_3"), which int() would read as one number
                    return v
                try:
                    return int(v)
                except ValueError:
                    try:
                        return float(v)
                    except ValueError:
                        return v
            r = s.cmd(op, *[num(a) for a in args], check=False)
            print("> %s  ->  %s %s" % (line, "ok" if r.ok else "ERROR", r.text))
            for d in r.data:
                print("    " + (d if len(d) < 400 else d[:400] + " ..."))
            if r.state:
                print("    " + " ".join("%s=%s" % kv for kv in r.state.items()))
    if s.resent:
        print("(%d commands had to be sent again)" % s.resent)


if __name__ == "__main__":
    main(sys.argv[1:])
