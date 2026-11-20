"""RDR2 map zone names, for readable location titles.

ZONE::_GET_MAP_ZONE_AT_COORDS(x, y, z, type) returns the joaat hash of the zone's name
from mapzones.meta. The names below are from femga/rdr3_discoveries (zones/README.md),
checked 2026-11-20: the hashes listed there equal joaat(name), so only names are kept.

Zone types: 0 state, 1 town, 2 lake, 3 river, 5 swamp, 6 ocean, 7 creek, 8 pond,
10 district, 11 printed map label, 12 written map label.
"""
import re

NAMES = {
    0: "Ambarino Guarma Lemoyne LowerWestElizabeth NewAustin NewHanover NuevoParaiso UpperWestElizabeth "
       "WestElizabeth",
    1: "AguasdulcesFarm AguasdulcesRuins AguasdulcesVilla Annesburg Armadillo BeechersHope Blackwater Braithwaite "
       "Butcher Caliga cornwall Emerald lagras Manicato Manzanita Rhodes Siska StDenis Strawberry Tumbleweed "
       "valentine VANHORN Wallace wapiti",
    2: "WATER_AURORA_BASIN WATER_BARROW_LAGOON WATER_CALMUT_RAVINE WATER_ELYSIAN_POOL WATER_FLAT_IRON_LAKE "
       "WATER_HEARTLANDS_OVERFLOW WATER_LAKE_DON_JULIO WATER_LAKE_ISABELLA WATER_O_CREAGHS_RUN WATER_OWANJILA "
       "WATER_SEA_OF_CORONADO",
    3: "WATER_ARROYO_DE_LA_VIBORA WATER_BEARTOOTH_BECK WATER_DAKOTA_RIVER WATER_KAMASSA_RIVER "
       "WATER_LANNAHECHEE_RIVER WATER_LITTLE_CREEK_RIVER WATER_LOWER_MONTANA_RIVER WATER_SAN_LUIS_RIVER "
       "WATER_UPPER_MONTANA_RIVER",
    5: "WATER_BAYOU_NWA",
    6: "WATER_BAHIA_DE_LA_PAZ",
    7: "WATER_DEADBOOT_CREEK WATER_DEWBERRY_CREEK WATER_HAWKS_EYE_CREEK WATER_RINGNECK_CREEK WATER_SPIDER_GORGE "
       "WATER_STILLWATER_CREEK WATER_WHINYARD_STRAIT",
    8: "WATER_CAIRN_LAKE WATER_CATTIAL_POND WATER_HOT_SPRINGS WATER_MATTLOCK_POND WATER_MOONSTONE_POND "
       "WATER_SOUTHFIELD_FLATS",
    10: "BayouNwa bigvalley BluewaterMarsh ChollaSprings Cumberland DiezCoronas GaptoothRidge greatPlains "
        "GrizzliesEast GrizzliesWest GuarmaD Heartlands HennigansStead Perdido PuntaOrgullo RioBravo roanoke "
        "scarlettMeadows TallTrees",
    11: "p_2_bluewater_marsh P_3_AURORA_BASIN P_3_BAHIA_DE_LA_PAZ P_3_BARROW_LAGOON P_3_CAIRN_LAKE "
        "P_3_CATTAIL_POND P_3_DAKOTA_RIVER P_3_DEADBOOT_CREEK P_3_DEWBERRY_CREEK P_3_ELYSIAN_POOL P_3_ERIS_FIELD "
        "P_3_FLAT_IRON_LAKE P_3_HEARTLAND_OIL_FIELDS P_3_HEARTLAND_OVERFLOW P_3_LAKAY P_3_LAKE_DON_JULIO "
        "P_3_LANNAHECHEE_RIVER P_3_LITTLE_CREEK_RIVER P_3_LOWER_MONTANA_RIVER P_3_MATTOCK_POND P_3_MONTOS_REST "
        "P_3_MOONSTONE_POND P_3_MOUNT_HAGEN P_3_OCREAGHS_RUN P_3_OWANJILA P_3_ROANOKE_VALLEY P_3_SAN_LUIS_RIVER "
        "P_3_SEA_OF_CORONADO P_3_SOUTHFIELD_FLATS P_3_SPIDER_GORGE P_3_STILLWATER_CREEK P_3_UPPER_MONTANA_RIVER "
        "P_3_WHINYARD_STRAIT P_4_AGUASDULCES P_4_ARMADILLO P_4_ARROYO_DE_LA_VIBORA P_4_BACCHUS_BRIDGE "
        "P_4_BACCHUS_STATION P_4_BARDS_CROSSING P_4_BEARTOOTH_BECK P_4_BENEDICT_PASS P_4_BENEDICT_POINT "
        "P_4_BLACKWATER P_4_BOLGER_GLADE P_4_BRAITHWAITE_MANOR P_4_CALIBANS_SEAT P_4_CALIGA_HALL "
        "P_4_CALUMET_RAVINE P_4_CINCO_TORRES P_4_CITADEL_ROCK P_4_COTORRA_SPRINGS P_4_CUMBERLAND_FALLS "
        "P_4_DIABLO_RIDGE P_4_DONNER_FALLS P_4_EMERALD_RANCH P_4_FLATNECK_STATION P_4_FORT_MERCER "
        "P_4_FORT_WALLACE P_4_GRANITE_PASS P_4_HAWKS_EYE_CREEK P_4_JORGES_GAP P_4_KAMASSA_RIVER P_4_LA_CAPILLA "
        "P_4_LAGRAS P_4_LAKE_ISABELLA P_4_MACFARLANES_RANCH P_4_MANTECA_FALLS P_4_MANZANITA_POST "
        "P_4_MERCER_STATION P_4_MOUNT_SHANN P_4_OWANJILA_DAM P_4_PLAINVIEW P_4_QUAKERS_COVE "
        "P_4_RATHSKELLER_FORK P_4_RHODES P_4_RIGGS_STATION P_4_RINGNECK_CREEK P_4_RIO_DEL_LOBO_ROCK "
        "P_4_SAINT_DENIS P_4_SISIKA_PENITENTIARY P_4_TEMPEST_RIM P_4_THIEVES_LANDING P_4_THREE_SISTERS "
        "P_4_TUMBLEWEED P_4_TWIN_ROCKS P_4_TWIN_STACK_PASS P_4_VALENTINE P_4_VAN_HORN_TRADING_POST "
        "P_4_WALLACE_STATION P_4_WINDOW_ROCK P_5_BRANDYWINE_DROP P_5_EMERALD_STATION P_5_STRAWBERRY "
        "P_5_WAPITI_INDIAN_RESERVATION P_6_ANNESBURG",
    12: "W_4_ABANDONED_MISSION W_4_ABANDONED_TRADING_POST W_4_ABERDEEN_PIG_FARM W_4_ADLER_RANCH "
        "W_4_APPLESEED_TIMBER_COMPANY W_4_BAYGALL_EDGE W_4_BEAR_CLAW W_4_BEECHERS_HOPE W_4_BRITTLEBRUSH_TRAWL "
        "W_4_BUTCHER_CREEK W_4_CAIRN_LODGE W_4_CANEBREAK_MANOR W_4_CARMODY_DELL W_4_CASTORS_RIDGE "
        "W_4_CATFISH_JACKSONS W_4_CENTRAL_UNION_RAILROAD_1 W_4_CENTRAL_UNION_RAILROAD_2 "
        "W_4_CENTRAL_UNION_RAILROAD_3 W_4_CHEZ_PORTER W_4_CLAWSONS_REST W_4_CLEMENS_POINT W_4_CLINGMAN "
        "W_4_COCHINAY W_4_COLTER W_4_COMPSONS_STEAD W_4_COOTS_CHAPEL W_4_COPPERHEAD_LANDING "
        "W_4_CORNWALL_KEROSENE_TAR W_4_CRAWDAD_WILLIES W_4_CUEVA_SECA W_4_DODDS_BLUFF W_4_DORMIN_CREST "
        "W_4_DOVERHILL W_4_DOWNES_RANCH W_4_EL_NIDO W_4_EVELYN_MILLER_CAMP W_4_EWING_BASIN W_4_FACE_ROCK "
        "W_4_FAIRVALE_SHANTY W_4_FIRE_LOOKOUT_TOWER W_4_FIRWOOD_RISE W_4_FLATTENED_CABIN "
        "W_4_FORT_RIGGS_HOLDING_CAMP W_4_GAPTOOTH_BREACH W_4_GILL_LANDING W_4_GRANGERS_HOGGERY "
        "W_4_GREENHOLLOW W_4_GUTHRIE_FARM W_4_HAGEN_ORCHARDS W_4_HANGING_DOG_RANCH W_4_HANIS_BETHEL "
        "W_4_HILL_HAVEN_RANCH W_4_HORSESHOE_OVERLOOK W_4_HOUSEBOAT W_4_LAKE_DON_JULIO_HOUSE W_4_LARNED_SOD "
        "W_4_LONE_MULE_STEAD W_4_LONNIES_SHACK W_4_LUCKYS_CABIN W_4_MACLEANS_HOUSE W_4_MACOMBS_END "
        "W_4_MANITO_GLADE W_4_MARTHAS_SWAIN W_4_MERKINS_WALLER W_4_METEOR_HOUSE W_4_MICAHS_HIDEOUT "
        "W_4_MILLESANI_CLAIM W_4_MOSSY_FLATS W_4_NEKOTI_ROCK W_4_ODDFELLOWS_REST W_4_OIL_DERRICK "
        "W_4_OLD_GREENBANK_MILL W_4_OLD_HARRY_FEN W_4_OLD_TOMS_BLIND W_4_OLD_TRAIL_RISE W_4_OSMAN_GROVE "
        "W_4_PAINTED_SKY W_4_PIKES_BASIN W_4_PLANTERS_BAWN W_4_PLEASANCE W_4_PLEASANCE_HOUSE W_4_PRINZ_CO "
        "W_4_PRONGHORN_RANCH W_4_RATTLESNAKE_HOLLOW W_4_REPENTANCE W_4_RIDGE_VIEW W_4_RIDGEWOOD_FARM "
        "W_4_RILEYS_CHARGE W_4_RIO_DEL_LOBO_HOUSE W_4_ROADSIDE_BROTHEL W_4_ROBARD_FARM W_4_SAWBONE_CLEARING "
        "W_4_SCRATCHING_POST W_4_SHADY_BELLE W_4_SHEPHERDS_RISE W_4_SILENT_STEAD W_4_SILTWATER_STRAND "
        "W_4_SIX_POINT_CABIN W_4_SOLOMONS_FOLLY W_4_STILLWATER_CABIN W_4_STILT_SHACK W_4_SWADBASS_POINT "
        "W_4_TANNERS_REACH W_4_TAXIDERMIST_HOUSE W_4_THE_HANGING_ROCK W_4_THE_LOFT W_4_THE_OLD_BACCHUS_PLACE "
        "W_4_TRADING_POST W_4_TRAPPERS_CABIN W_4_TWO_CROWS W_4_UTOPIAN_COLONY_BUILDING W_4_VAN_HORN_MANSION "
        "W_4_VENTERS_PLACE W_4_VETERANS_HOMESTEAD W_4_WALLACE_OVERLOOK W_4_WATSONS_CABIN W_4_WILLARDS_REST "
        "W_4_WITCHES_CAULDRON W_5_ARGIL_RISE W_5_BEAVER_HOLLOW W_5_BERYLS_DREAM W_5_BLACK_BALSAM_RISE "
        "W_5_BLACK_BONE_FOREST W_5_BROKEN_TREE W_5_CHADWICK_FARM W_5_DEER_COTTAGE W_5_FISHINGSPOT "
        "W_5_FORT_BRENNAND W_5_GRAND_KORRIGAN_DOCKED W_5_GRAND_KORRIGAN_SEA W_5_HURON_GLEN W_5_LENORA_VIEW "
        "W_5_LIMPANY W_5_RADLEYS_PASTURE W_5_VALLEY_VIEW W_5_VETTERS_ECHO W_6_RADLEYS_HOUSE W_6_REED_COTTAGE",
}

# Names the generic rule below gets wrong.
READABLE = {
    "StDenis": "Saint Denis", "VANHORN": "Van Horn", "BeechersHope": "Beecher's Hope", "Butcher": "Butcher Creek",
    "Emerald": "Emerald Ranch", "Wallace": "Wallace Station", "Siska": "Sisika", "Caliga": "Caliga Hall",
    "bigvalley": "Big Valley", "roanoke": "Roanoke Ridge", "GuarmaD": "Guarma", "HennigansStead": "Hennigan's Stead",
    "WATER_CATTIAL_POND": "Cattail Pond", "WATER_MATTLOCK_POND": "Mattock Pond", "WATER_CALMUT_RAVINE": "Calumet Ravine",
}

# Most specific first: written label, printed label, town, water body, district, state.
TITLE_ORDER = (12, 11, 1, "water", 10, 0)


def joaat(text):
    h = 0
    for c in text.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def readable(name):
    if name in READABLE:
        return READABLE[name]
    base = re.sub(r"^(?:[PpWw]_\d_|WATER_)", "", name)
    if "_" in base or base.isupper():
        return " ".join(w.capitalize() for w in base.split("_") if w)
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    return spaced[:1].upper() + spaced[1:]


def name_table():
    """unsigned hash -> readable name, for every known zone."""
    return {joaat(n): readable(n) for names in NAMES.values() for n in names.split()}


_TABLE = None


def title(hashes):
    """A readable place title from zone hashes by type ({12: h, 11: h, 1: h, "water": h, 10: h, 0: h};
    0 or None where there is no zone), most specific first, e.g. "Saint Denis · Bayou Nwa · Lemoyne"."""
    global _TABLE
    if _TABLE is None:
        _TABLE = name_table()
    parts = []
    for key in TITLE_ORDER:
        h = hashes.get(key)
        if not h:
            continue
        name = _TABLE.get(int(h) & 0xFFFFFFFF)
        if name and name not in parts:
            parts.append(name)
    return " · ".join(parts[:3]) or None
