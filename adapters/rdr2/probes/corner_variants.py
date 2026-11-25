"""Which of RDR2's graphics settings darkens the frame toward its corners? (BACKLOG; QC round 1,
rdr2-002/003/004 c3: the same patch of scene reads 0.3-0.6 of its centre brightness near a corner,
at every place.) For each variant: the game closed, the variant's values written into system.xml,
the game started, tools/vignette_check.py run live (the same patch at the centre and turned near each
corner, exposure held), the game closed again. system.xml is put back as it was at the end.

    uv run --project . python -m adapters.rdr2.probes.corner_variants --location rdr2-lakeshore-001
        [--variants base,ssdo_off,dss_off,probe_relight,ssao_full] [--view wide]

Writes out/probes/rdr2_corner_variants/<stamp>/report.json: per variant the four corners' live_ratio.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
from capture import paths as capture_paths  # noqa: E402
import vignette_check  # noqa: E402

from .. import install, launch  # noqa: E402

VARIANTS = {
    "base": {},
    "ssdo_off": {"ssdoSampleCount": "0"},                       # screen-space directional occlusion
    "dss_off": {"directionalScreenSpaceShadowQuality": "0.000000"},   # screen-space sun shadows
    "probe_relight": {"probeRelightEveryFrame": "true"},       # light probes relit every frame
    "ssao_full": {"ssaoFullScreenEnabled": "true"},
    "height_shadow_off": {"worldHeightShadowQuality": "0.000000"},
    "ssro_off": {"ssroSampleCount": "0"},
}


def set_values(path, values):
    text = open(path, encoding="utf-8").read()
    for k, v in values.items():
        new, n = re.subn(r'<%s value="[^"]*" />' % re.escape(k), '<%s value="%s" />' % (k, v), text)
        if not n:
            raise SystemExit("%s not in %s" % (k, path))
        text = new
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", default="rdr2-lakeshore-001")
    ap.add_argument("--variants", default="base,ssdo_off,dss_off,probe_relight,ssao_full")
    ap.add_argument("--view", default="wide")
    a = ap.parse_args(argv)
    out = os.path.join(capture_paths.OUT, "probes", "rdr2_corner_variants", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out)
    xml = install.settings_xml()
    backup = os.path.join(out, "system.xml.before")
    shutil.copyfile(xml, backup)
    game_dir = install.find_game_dir()
    report = {"location": a.location, "view": a.view, "variants": {}}
    try:
        for name in a.variants.split(","):
            launch.close_game()
            shutil.copyfile(backup, xml)
            set_values(xml, VARIANTS[name])
            launch.start(game_dir)
            vout = os.path.join(out, name)
            vignette_check.main(["--game", "rdr2", "--location", a.location, "--view", a.view, "--out", vout])
            rep = json.load(open(os.path.join(vout, "report.json"), encoding="utf-8"))
            report["variants"][name] = {"values": VARIANTS[name],
                                        "live_ratio": {k: v["live_ratio"] for k, v in rep.get("corners", {}).items()}}
            print(name, report["variants"][name], flush=True)
            json.dump(report, open(os.path.join(out, "report.json"), "w"), indent=1)
    finally:
        launch.close_game()
        shutil.copyfile(backup, xml)
    print("system.xml put back; wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
