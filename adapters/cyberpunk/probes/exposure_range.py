"""How far the forced average luminance moves the frame: the brightness of one view at a location
for a row of forced values, next to what auto-exposure gives, and with the engine's eye adaptation
switched off. For the exposure lock (adapter._lock_exposure), which did not reach auto-exposure's
brightness in sunlit places.

    uv run --project . python -m adapters.cyberpunk.probes.exposure_range --location cyberpunk-kabuki-market-001
        [--option ForcedPreExposure --values 0.05,0.1,0.2,0.5,1,2]
        [--category DLSS --option ExposureScale --values 0.5,1,2 --hold 1000]

--category: the option's group (Rendering, DLSS, Developer/FeatureToggles, ...); --hold: the
forced average luminance kept while another option is swept (the lock's floor, to see whether
that option takes the frame further down).
"""
import argparse

from capture import adapters_registry
from capture import locations as locs
from capture import paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="cyberpunk-kabuki-market-001")
    ap.add_argument("--clock", default="12:00")
    ap.add_argument("--option", default="ForcedExposureAvgLum",
                    help="the Rendering option swept: ForcedExposureAvgLum, or ForcedPreExposure")
    ap.add_argument("--values", help="comma-separated values (default: a row from 0.01 to 1e6)")
    ap.add_argument("--category", default="Rendering")
    ap.add_argument("--hold", type=float, help="ForcedExposureAvgLum held while --option is swept")
    a = ap.parse_args()
    ad = adapters_registry.get("cyberpunk")()
    ad.ensure_ready(restart=False)
    ad.open()
    try:
        loc = locs.get(paths.LOCATIONS, a.location)
        ad.go_to(loc["position"], loc["facing_deg"])
        ad.set_clock(a.clock)
        ad.wait_frames(240)
        opt = lambda text: ad.sess.cmd("option", text)
        auto = [round(ad._brightness(40), 2) for _ in range(3)]
        print("auto-exposure, three readings 40 frames apart:", auto)
        opt("set Rendering ForcedInstantAutoExposure true")
        if a.hold is not None:
            opt("set Rendering ForcedExposureAvgLum %.6f" % a.hold)
            print("held at ForcedExposureAvgLum %g: brightness %.2f" % (a.hold, ad._brightness(12)), flush=True)
        if a.values and all(v in ("true", "false") for v in a.values.split(",")):
            values = a.values.split(",")
        else:
            values = [float(v) for v in a.values.split(",")] if a.values else (0.01, 0.1, 1, 10, 30, 60, 100, 150, 300, 1000, 10000, 1e6)
        for v in values:
            print("%s/%s %-10s -> %s brightness %.2f" % (a.category, a.option, v,
                  opt("set %s %s %s" % (a.category, a.option, v if isinstance(v, str) else "%.6f" % v)).get("option"),
                  ad._brightness(12)), flush=True)
        if a.category == "Rendering" and a.option in ("ForcedExposureAvgLum", "ForcedPreExposure"):
            opt("set Rendering %s -1.0" % a.option)
        opt("set Rendering ForcedInstantAutoExposure false")
        ad.wait_frames(240)
        print("auto again:", round(ad._brightness(40), 2))
    finally:
        ad.close()


if __name__ == "__main__":
    main()
