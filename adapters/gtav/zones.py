"""Readable place titles for GTA V from the map zone's code.

The game names a point's zone with a short code (GET_NAME_OF_ZONE: "LEGSQU"), but RedLua hands
strings back as raw pointers that are unsafe to read from Lua (README: RedLua in GTA V). The
session passes that pointer straight back into GET_HASH_KEY, so only the code's hash leaves the
game; this table turns the hash into the zone's map name.
"""

ZONES = {
    "AIRP": "Los Santos International Airport", "ALAMO": "Alamo Sea", "ALTA": "Alta", "ARMYB": "Fort Zancudo",
    "BANHAMC": "Banham Canyon Dr", "BANNING": "Banning", "BEACH": "Vespucci Beach", "BHAMCA": "Banham Canyon",
    "BRADP": "Braddock Pass", "BRADT": "Braddock Tunnel", "BURTON": "Burton", "CALAFB": "Calafia Bridge",
    "CANNY": "Raton Canyon", "CCREAK": "Cassidy Creek", "CHAMH": "Chamberlain Hills", "CHIL": "Vinewood Hills",
    "CHU": "Chumash", "CMSW": "Chiliad Mountain State Wilderness", "CYPRE": "Cypress Flats", "DAVIS": "Davis",
    "DELBE": "Del Perro Beach", "DELPE": "Del Perro", "DELSOL": "Puerto Del Sol", "DESRT": "Grand Senora Desert",
    "DOWNT": "Downtown", "DTVINE": "Downtown Vinewood", "EAST_V": "East Vinewood", "EBURO": "El Burro Heights",
    "ELGORL": "El Gordo Lighthouse", "ELYSIAN": "Elysian Island", "GALFISH": "Galilee",
    "GOLF": "GWC and Golfing Society", "GRAPES": "Grapeseed", "GREATC": "Great Chaparral", "HARMO": "Harmony",
    "HAWICK": "Hawick", "HORS": "Vinewood Racetrack", "HUMLAB": "Humane Labs and Research",
    "JAIL": "Bolingbroke Penitentiary", "KOREAT": "Little Seoul", "LACT": "Land Act Reservoir",
    "LAGO": "Lago Zancudo", "LDAM": "Land Act Dam", "LEGSQU": "Legion Square", "LMESA": "La Mesa",
    "LOSPUER": "La Puerta", "MIRR": "Mirror Park", "MORN": "Morningwood", "MOVIE": "Richards Majestic",
    "MTCHIL": "Mount Chiliad", "MTGORDO": "Mount Gordo", "MTJOSE": "Mount Josiah", "MURRI": "Murrieta Heights",
    "NCHU": "North Chumash", "NOOSE": "N.O.O.S.E.", "OCEANA": "Pacific Ocean", "PALCOV": "Paleto Cove",
    "PALETO": "Paleto Bay", "PALFOR": "Paleto Forest", "PALHIGH": "Palomino Highlands",
    "PALMPOW": "Palmer-Taylor Power Station", "PBLUFF": "Pacific Bluffs", "PBOX": "Pillbox Hill",
    "PROCOB": "Procopio Beach", "RANCHO": "Rancho", "RGLEN": "Richman Glen", "RICHM": "Richman",
    "ROCKF": "Rockford Hills", "RTRAK": "Redwood Lights Track", "SANAND": "San Andreas",
    "SANCHIA": "San Chianski Mountain Range", "SANDY": "Sandy Shores", "SKID": "Mission Row", "SLAB": "Stab City",
    "STAD": "Maze Bank Arena", "STRAW": "Strawberry", "TATAMO": "Tataviam Mountains", "TERMINA": "Terminal",
    "TEXTI": "Textile City", "TONGVAH": "Tongva Hills", "TONGVAV": "Tongva Valley", "VCANA": "Vespucci Canals",
    "VESP": "Vespucci", "VINE": "Vinewood", "WINDF": "Ron Alternates Wind Farm", "WVINE": "West Vinewood",
    "ZANCUDO": "Zancudo River", "ZP_ORT": "Port of South Los Santos", "ZQ_UAR": "Davis Quartz",
}


def joaat(text):
    """RAGE's string hash (Jenkins one-at-a-time over the lower-cased bytes), as an unsigned 32-bit int."""
    h = 0
    for c in text.lower().encode("ascii"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


BY_HASH = {joaat(code): name for code, name in ZONES.items()}


def title(zone_hash):
    """The zone's name for the hash of its code (signed or unsigned), or None."""
    try:
        return BY_HASH.get(int(zone_hash) & 0xFFFFFFFF)
    except (TypeError, ValueError):
        return None
