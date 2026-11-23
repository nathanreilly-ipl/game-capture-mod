"""How far the forced average luminance moves the frame: the brightness of one view at a location
for a row of forced values, next to what auto-exposure gives, and with the engine's eye adaptation
switched off. For the exposure lock (adapter._lock_exposure), which did not reach auto-exposure's
brightness in sunlit places.

    uv run --project . python -m adapters.cyberpunk.probes.exposure_range --location cyberpunk-kabuki-market-001
"""
import argparse

from capture import adapters_registry
from capture import locations as locs
from capture import paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--location", default="cyberpunk-kabuki-market-001")
    ap.add_argument("--clock", default="12:00")
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
        for lum in (0.01, 0.1, 1, 10, 30, 60, 100, 150, 300, 1000, 10000, 1e6):
            opt("set Rendering ForcedExposureAvgLum %.6f" % lum)
            print("forced average luminance %-10g brightness %.2f" % (lum, ad._brightness(12)))
        opt("set Rendering ForcedExposureAvgLum -1.0")
        opt("set Rendering ForcedInstantAutoExposure false")
        ad.wait_frames(240)
        print("auto again:", round(ad._brightness(40), 2))
    finally:
        ad.close()


if __name__ == "__main__":
    main()
