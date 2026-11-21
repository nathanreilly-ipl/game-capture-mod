"""Which freeze holds GTA V's world at one instant while a script camera still renders?

Runs lua/jobs/freeze_probe.lua once per method (time scale 0, SET_GAME_PAUSED, both) and
compares its frames: the same pose captured at three moments of the freeze should match (only
render noise), a moved camera should differ, and moving back should match again.

    uv run --project . python adapters/gtav/probes/freeze_probe.py [--methods timescale,paused,both]
Results: out/probes/gtav_freeze/<time>/<method>/ (frames, job.log, result.txt) and summary.txt.
"""
import argparse
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, REPO)
from adapters.common import redlua  # noqa: E402
from adapters.gtav.adapter import EXCHANGE  # noqa: E402

JOB = os.path.join(os.path.dirname(HERE), "lua", "jobs", "freeze_probe.lua")


def diff(a, b):
    x = np.asarray(Image.open(a).convert("RGB"), dtype=np.float32)
    y = np.asarray(Image.open(b).convert("RGB"), dtype=np.float32)
    return float(np.abs(x - y).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="timescale,paused,both")
    ap.add_argument("--gap", type=int, default=120)
    a = ap.parse_args()
    root = os.path.join(REPO, "out", "probes", "gtav_freeze", time.strftime("%Y%m%d_%H%M%S"))
    lines = []
    for method in a.methods.split(","):
        res = redlua.run_job(EXCHANGE, JOB, timeout_s=180, method=method, gap=a.gap)
        out = os.path.join(root, method)
        shutil.copytree(res["job_dir"], out)
        lines.append("== %s: %s %s" % (method, res.get("status"), res.get("message", "")))
        for k in sorted(res):
            if k.endswith(("_m", "_ms", "_frames")):
                lines.append("   %-24s %s" % (k, res[k]))
        f = lambda n: os.path.join(out, n + ".bmp")  # noqa: E731
        if all(os.path.exists(f(n)) for n in ("frozen_a", "frozen_b", "frozen_c", "frozen_moved", "frozen_back")):
            for x, y, what in (("frozen_a", "frozen_b", "same pose, %d ticks apart" % a.gap),
                               ("frozen_b", "frozen_c", "same pose, %d ticks apart" % a.gap),
                               ("frozen_a", "frozen_moved", "camera moved a quarter turn (should differ)"),
                               ("frozen_a", "frozen_back", "camera moved back (should match)"),
                               ("live_before", "frozen_a", "live to frozen")):
                lines.append("   %-13s vs %-13s %6.2f  %s" % (x, y, diff(f(x), f(y)), what))
        print("\n".join(lines[-12:]), flush=True)
        time.sleep(3)
    with open(os.path.join(root, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("results in", root)


if __name__ == "__main__":
    main()
