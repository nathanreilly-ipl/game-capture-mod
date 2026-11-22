"""Scouts locations beside the game's fast-travel points: known spots on the ground all over the
map, by name, without anyone walking there.

    uv run --project . python -m adapters.cyberpunk.probes.scout_fast_travel --list
    uv run --project . python -m adapters.cyberpunk.probes.scout_fast_travel <record>=<name> [...] [--ahead 4]

--list prints the points the loaded save knows (record, name, district). Each <record>=<name>
(e.g. wat_kab_dataterm_01=kabuki-market) teleports to that point, steps --ahead metres the way
the player then faces (away from the terminal, so the terminal is not the subject) and records a
location there with the usual four previews, as `capture scout` does.
"""
import math
import sys

from capture import paths as capture_paths
from capture.scout import TooClose, scout

from ...common import redlua
from ..adapter import CyberpunkAdapter

LIST = """
local ft = Game.GetScriptableSystemsContainer():Get('FastTravelSystem')
for _, n in ipairs(ft.fastTravelNodes) do
  local id = n:GetPointRecord()
  local r = TweakDBInterface.GetFastTravelPointRecord(id)
  out((TDBID.ToStringDEBUG(id):gsub('^FastTravelPoints%.', '')) .. ' | ' .. (r and GetLocalizedText(r:DisplayName()) or '?')
    .. ' | ' .. tostring(r and r:District() and r:District():Type() or '?'))
end
"""
GO = """
local ft = Game.GetScriptableSystemsContainer():Get('FastTravelSystem')
for _, n in ipairs(ft.fastTravelNodes) do
  if TDBID.ToStringDEBUG(n:GetPointRecord()) == 'FastTravelPoints.%s' then
    Game.GetTeleportationFacility():TeleportToNode(Game.GetPlayer(), n:GetMarkerRef())
    return 'going'
  end
end
return 'no such point'
"""


def main(argv):
    ahead = float(argv[argv.index("--ahead") + 1]) if "--ahead" in argv else 4.0
    ad = CyberpunkAdapter()
    ad.ensure_ready(restart=True)
    ad.open()
    try:
        if "--list" in argv:
            print(ad.eval(LIST))
            return 0
        for spec in [a for a in argv if "=" in a]:
            record, name = spec.split("=", 1)
            if ad.eval(GO % record).strip() != "going":
                print("%s: not a fast-travel point this save knows" % record)
                continue
            ad.sess.cmd("wait", 120, timeout=120)
            st = ad.sess.cmd("state")
            p, yaw = redlua.vec(st["player"]), float(st["player_heading"])
            h = math.radians(yaw)
            at = [p[0] - math.sin(h) * ahead, p[1] + math.cos(h) * ahead, p[2] + 0.3]
            try:
                e = scout(ad, capture_paths.LOCATIONS, name=name, at=at, facing=yaw, clock="12:00", tags=["fast-travel", record])
                print("%s -> %s at %s" % (record, e["id"], ", ".join("%.2f" % v for v in e["position"])))
            except TooClose as err:
                print("%s: %s" % (record, err))
    finally:
        ad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
