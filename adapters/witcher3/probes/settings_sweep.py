"""Render settings compared at one pose of one held instant: the picture, its noise, the frame rate.

    uv run --project . python -m adapters.witcher3.probes.settings_sweep --pose x,y,z,pitch,yaw [--only pt_rr,rt_rr] [--gap 2]

The game reads its settings when it starts, so each variant is written into dx12user.settings with
the game closed, the game started, the save loaded and the noise probe run at the pose (the player
is where the save put it; the world's clock and weather are set the same for each). The settings
file is put back as it was at the end and the game started once more. Results under
out/probes/witcher3/settings/<variant>/ (frame.png, sd_x8.png, report.json) and a table at the end.
"""
import argparse
import json
import os
import shutil

from capture import paths as capture_paths
from capture.install.plan import Ini

from ...common import frames
from .. import launch, paths
from ..session import Session
from . import noise_probe

RT, PT, PP = "Rendering/RT", "Rendering/RT/PathTracer", "PostProcess"
FULL_RT = {(RT, "EnableRT"): "true", (RT, "RTGIPreset"): "true", (RT, "EnableRtRadiance"): "true", (RT, "Shadows"): "2",
           (RT, "RTAOEnabled"): "true"}
VARIANTS = {
    "pt_rr":     {**FULL_RT, (PT, "PTEnable"): "true", (PP, "EnableDLSSRR"): "true"},
    "pt":        {**FULL_RT, (PT, "PTEnable"): "true", (PP, "EnableDLSSRR"): "false"},
    "rt_rr":     {**FULL_RT, (PT, "PTEnable"): "false", (PP, "EnableDLSSRR"): "true"},
    "rt":        {**FULL_RT, (PT, "PTEnable"): "false", (PP, "EnableDLSSRR"): "false"},
    "raster":    {(RT, "EnableRT"): "false", (RT, "RTGIPreset"): "false", (RT, "EnableRtRadiance"): "false", (RT, "Shadows"): "0",
                  (RT, "RTAOEnabled"): "false", (PT, "PTEnable"): "false", (PP, "EnableDLSSRR"): "false"},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", required=True)
    ap.add_argument("--only", default=",".join(VARIANTS))
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--gap", type=int, default=2)
    ap.add_argument("--settle", type=int, default=180)
    ap.add_argument("--clock", default="17:00")
    ap.add_argument("--crop", default="1300,450,1600,650")
    a = ap.parse_args()
    pose = [float(v) for v in a.pose.split(",")]
    crop = [int(v) for v in a.crop.split(",")]
    h, m = [int(v) for v in a.clock.split(":")]
    out = os.path.join(capture_paths.OUT, "probes", "witcher3", "settings")
    os.makedirs(out, exist_ok=True)
    user = paths.user_settings()
    keep = os.path.join(out, "dx12user.settings.before")
    launch.close_game()
    shutil.copyfile(user, keep)
    rows = []
    try:
        for name in a.only.split(","):
            ini = Ini(user)
            for (section, key), value in VARIANTS[name].items():
                ini.set(section, key, value)
            ini.save()
            launch.start()
            s = Session()
            ex = paths.exchange()
            s.close_menu()
            s.cmd("hud", 0)
            s.cmd("clockrate", 0)
            s.cmd("clock", h, m)
            s.cmd("weather", "WT_Clear", 0)
            frames.wait(ex, 300)
            after = Ini(user)                 # what the game kept of what was asked
            kept = {"%s %s" % k: after.get(*k) for k in VARIANTS[name]}
            report, one, two = noise_probe.measure(s, ex, pose, a.n, a.gap, a.settle)
            report["settings"] = kept
            noise_probe.save(os.path.join(out, name), report, one, two, crop)
            print("== %s ==\n%s" % (name, noise_probe.text(report)))
            rows.append((name, report))
            launch.close_game()
    finally:
        launch.close_game()
        shutil.copyfile(keep, user)
        launch.start()
    print("\n%-8s %8s %12s %12s %10s %10s %10s" % ("variant", "frames/s", "sd>4 %", "sd>12 %", "1 frame", "avg of 4", "avg of 16"))
    for name, r in rows:
        av = r["average_of"]
        print("%-8s %8.1f %12.3f %12.3f %10.3f %10.3f %10.3f" % (name, r["frames_per_s"], r["sd_over_4_pct"], r["sd_over_12_pct"],
                                                              av.get(1, 0), av.get(4, 0), av.get(16, 0)))
    with open(os.path.join(out, "table.json"), "w") as f:
        json.dump({name: r for name, r in rows}, f, indent=1)


if __name__ == "__main__":
    main()
