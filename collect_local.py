#!/usr/bin/env python3
"""Collect small local businesses in Stillwater, Cushing, Perry, and Morrison OK.

Source: OpenStreetMap via the Overpass API (public data, ODbL).
Writes local_candidates.json: one record per business, chains and
non-businesses filtered out, bucketed into Kit-facing categories.
Scoring happens later in build_leads.py --local.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
OVERPASS = "https://overpass-api.de/api/interpreter"
STILLWATER = (36.1156, -97.0584)

# center lat, center lon, half-height deg, half-width deg (OSM place nodes)
TOWNS = {
    "Stillwater": (36.1156, -97.0586, 0.085, 0.10),
    "Cushing": (35.9849, -96.7674, 0.05, 0.06),
    "Perry": (36.2907, -97.2884, 0.045, 0.055),
    "Morrison": (36.2973, -97.0081, 0.025, 0.03),
    "Pawnee": (36.3384, -96.8032, 0.03, 0.04),
}

# (osm key, value regex) -> category. First match wins, so order matters.
CATEGORY_RULES = [
    (("healthcare", r"dentist"), "Medical & Dental"),
    (("amenity", r"dentist"), "Medical & Dental"),
    (("amenity", r"veterinary"), "Veterinary & Animal"),
    (("shop", r"pet_grooming|pet"), "Veterinary & Animal"),
    (("healthcare", r"physiotherapist|chiropractor|optometrist|psychotherapist|counselling|doctor|clinic|alternative|audiologist|speech_therapist|occupational_therapist|podiatrist|laboratory|rehabilitation"), "Medical & Dental"),
    (("amenity", r"doctors|clinic"), "Medical & Dental"),
    (("shop", r"optician|hearing_aids|medical_supply"), "Medical & Dental"),
    (("office", r"lawyer|notary"), "Legal"),
    (("office", r"accountant|tax_advisor|financial_advisor|financial"), "Accounting & Finance"),
    (("office", r"insurance"), "Insurance"),
    (("office", r"estate_agent|property_management"), "Real Estate & Property"),
    (("shop", r"storage_rental"), "Real Estate & Property"),
    (("craft", r"electrician|plumber|hvac|roofer|carpenter|builder|painter|hvac|metal_construction|welder|stonemason|tiler|glaziery|window_construction|floorer|insulation|plasterer|gardener|landscaper"), "Trades & Contractors"),
    (("office", r"construction_company|engineer|architect|surveyor"), "Trades & Contractors"),
    (("shop", r"car_repair|tyres|car_parts|motorcycle_repair"), "Auto & Equipment"),
    (("amenity", r"car_repair|car_wash|vehicle_inspection"), "Auto & Equipment"),
    (("shop", r"car|motorcycle|trailer|agrarian|farm|tractor"), "Auto & Equipment"),
    (("craft", r"car_repair|agricultural_engines|small_engine"), "Auto & Equipment"),
    (("shop", r"hairdresser|beauty|massage|tattoo|cosmetics|nails"), "Salon & Personal Care"),
    (("amenity", r"childcare|kindergarten|driving_school|music_school|language_school|dancing_school|prep_school"), "Childcare & Education"),
    (("leisure", r"fitness_centre|sports_centre|dance"), "Fitness & Recreation"),
    (("amenity", r"fitness_centre"), "Fitness & Recreation"),
    (("tourism", r"hotel|motel|guest_house|hostel|bed_and_breakfast"), "Lodging & Events"),
    (("amenity", r"events_venue|funeral_hall|conference_centre"), "Lodging & Events"),
    (("shop", r"funeral_directors"), "Lodging & Events"),
    (("amenity", r"restaurant|cafe|bar|pub|fast_food|ice_cream|biergarten|food_court"), "Food & Drink"),
    (("shop", r"bakery|butcher|deli|coffee|confectionery|alcohol|wine|beverages|pastry"), "Food & Drink"),
    (("office", r"it|telecommunication|advertising_agency|consulting|employment_agency|marketing|graphic_design|company|yes|association|ngo|research|logistics|moving_company|courier"), "Professional Services"),
    (("shop", r"copyshop|printing|photo|computer|electronics|mobile_phone|repair"), "Professional Services"),
    (("craft", r".+"), "Trades & Contractors"),
    (("shop", r".+"), "Retail"),
]

# Not businesses Marzipan sells to, or public-sector buyers.
SKIP_TAGS = {
    "amenity": r"place_of_worship|school|university|college|library|parking.*|bench|shelter|toilets|post_office|townhall|police|fire_station|courthouse|prison|social_facility|grave_yard|fountain|drinking_water|atm|bicycle_parking|waste_.*|recycling|charging_station|community_centre|social_centre|public_bookcase|vending_machine|telephone|letter_box|hospital|fuel|bank|marketplace|arts_centre|theatre|cinema|nightclub|studio|loading_dock|boat_rental|dojo|bus_station|taxi",
    "leisure": r"park|pitch|playground|garden|commons|stadium|golf_course|track|swimming_pool|nature_reserve|picnic_table|dog_park|recreation_ground|sports_hall|ice_rink|marina|slipway|disc_golf_course|bleachers|outdoor_seating|firepit|common",
    "tourism": r"information|museum|attraction|artwork|picnic_site|viewpoint|camp_site|caravan_site|gallery|zoo",
    "office": r"government|educational_institution|religion|political_party|diplomatic|quango",
    "shop": r"vacant|charity|money_lender|pawnbroker|cannabis|e-cigarette|tobacco|lottery|ticket",
}

# National/regional chains and franchises (lowercased substring match on name).
CHAINS = [
    "mcdonald", "sonic", "taco bell", "taco bueno", "wendy", "burger king", "arby", "subway",
    "chick-fil-a", "chickfila", "kfc", "popeyes", "braum", "starbucks", "dunkin", "domino",
    "pizza hut", "papa john", "little caesar", "sonic drive", "whataburger", "carl's jr",
    "jimmy john", "chipotle", "panda express", "panera", "applebee", "chili's", "ihop",
    "denny", "buffalo wild", "freddy", "raising cane", "dairy queen", "cicis", "olive garden",
    "golden corral", "zaxby", "wingstop", "jersey mike", "firehouse subs", "qdoba", "schlotzsky",
    "mazzio", "hideaway", "hideaway pizza", "eskimo joe", "rib crib", "andy's frozen",
    "walmart", "target", "lowe's", "home depot", "atwoods", "tractor supply", "dollar general",
    "dollar tree", "family dollar", "walgreens", "cvs", "o'reilly", "autozone", "napa auto",
    "advance auto", "aldi", "sprouts", "hobby lobby", "tj maxx", "ross dress", "marshalls",
    "kohl's", "jcpenney", "old navy", "academy sports", "petsmart", "petco", "harbor freight",
    "big lots", "staples", "office depot", "best buy", "gamestop", "ulta", "sally beauty",
    "great clips", "supercuts", "sport clips", "fantastic sams", "t-mobile", "verizon", "at&t",
    "cricket", "boost mobile", "metro by", "sherwin", "edward jones", "h&r block", "jackson hewitt", "liberty tax", "aaron's", "rent-a-center",
    "planet fitness", "anytime fitness", "snap fitness", "orangetheory", "hampton inn",
    "holiday inn", "best western", "super 8", "motel 6", "comfort inn", "comfort suites",
    "quality inn", "la quinta", "days inn", "fairfield inn", "courtyard", "candlewood",
    "home2", "hilton", "marriott", "microtel", "americinn", "econo lodge", "sleep inn",
    "jiffy lube", "valvoline", "take 5", "firestone", "goodyear", "midas", "meineke",
    "discount tire", "big o tires", "u-haul", "public storage", "extra space", "cubesmart",
    "fedex", "ups store", "kinder care", "kindercare", "goddard", "primrose", "sylvan",
    "mathnasium", "aspen dental", "heartland dental", "banfield", "vca ", "concentra",
    "lenscrafters", "visionworks", "america's best", "great harvest", "casey's", "love's",
    "quiktrip", "qt ", "on cue", "oncue", "7-eleven", "circle k", "shell", "phillips 66",
    "conoco", "valero", "murphy usa", "kum & go", "cherokee casino", "first bank",
    "bank of america", "arvest", "bancfirst", "chase", "wells fargo", "rcb bank",
    "tinker federal", "simmons bank", "regions", "redbud", "gnc", "vitamin shoppe",
    "foot locker", "bath & body", "victoria's secret", "buckle", "maurices", "rue21",
    "claire's", "spencer", "kirkland", "sam's club", "cato", "goodwill", "salvation army",
    "harps", "reasor", "homeland", "united supermarket", "crest foods", "warehouse market",
    "buff city soap", "tropical smoothie", "smoothie king", "nothing bundt", "crumbl",
    "insomnia cookies", "scooter's", "7 brew", "dutch bros", "swig", "sweetfrog",
    "marble slab", "orange leaf", "pinkberry", "jamba", "wing stop", "ihop", "waffle house",
    "cracker barrel", "red lobster", "outback", "texas roadhouse", "longhorn", "logan's",
    "mexican restaurant chain", "el chico", "on the border", "mcalister", "zoe's kitchen",
    "potbelly", "which wich", "five guys", "smashburger", "steak n shake", "back yard burgers",
    "del taco", "taco mayo", "pizza inn", "marco's", "hungry howie", "cici's", "sbarro",
    "ocean state", "kwik", "atwood", "orscheln", "rural king", "bomgaars", "aaa ",
    "progressive", "geico", "mobile home", "massage envy",
    "hand & stone", "european wax", "drybar", "regis", "smartstyle", "cost cutters",
]

# Owner-run local shops whose names collide with a chain entry.
LOCAL_OK = ["direct discount tire"]

# Captive insurance agents (State Farm, Allstate, Shelter, Farm Bureau...) are kept
# on purpose: each is a locally owned small office with its own admin load.

TYPE_KEYS = ["shop", "office", "craft", "healthcare", "amenity", "tourism", "leisure"]


def haversine_miles(a, b) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def fetch_town(name: str, la: float, lo: float, dla: float, dlo: float) -> list[dict]:
    bb = f"{la - dla},{lo - dlo},{la + dla},{lo + dlo}"
    q = (
        f"[out:json][timeout:90][bbox:{bb}];"
        "(nwr[shop][name];nwr[office][name];nwr[craft][name];nwr[healthcare][name];"
        "nwr[amenity][name];nwr[tourism][name];nwr[leisure][name];);out center tags;"
    )
    last_err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(
                OVERPASS,
                data=urllib.parse.urlencode({"data": q}).encode(),
                headers={"User-Agent": "LeadRadar/0.1 (Marzipan Solutions)"},
            )
            with urllib.request.urlopen(req, timeout=150) as resp:
                d = json.loads(resp.read().decode())
            if d.get("remark") and not d.get("elements"):
                raise RuntimeError(d["remark"])
            return d["elements"]
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last_err = e
            time.sleep(10)
    raise SystemExit(f"Overpass failed for {name}: {last_err}")


def primary_type(tags: dict) -> str:
    for k in TYPE_KEYS:
        if k in tags:
            return f"{k}={tags[k]}"
    return "?"


def is_skipped(tags: dict) -> bool:
    for k in TYPE_KEYS:
        if k in tags:
            pat = SKIP_TAGS.get(k)
            return bool(pat and re.fullmatch(pat, tags[k]))
    return True


def is_chain(tags: dict) -> bool:
    if (tags.get("brand") or tags.get("brand:wikidata")) and tags.get("office") != "insurance":
        return True
    n = tags.get("name", "").lower()
    if any(ok in n for ok in LOCAL_OK):
        return False
    return any(c in n for c in CHAINS)


def categorize(tags: dict) -> str | None:
    for (k, pat), cat in CATEGORY_RULES:
        if k in tags and re.fullmatch(pat, tags[k]):
            return cat
    return None


def address(tags: dict) -> str | None:
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    return street or None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
ZIPS = {"Stillwater": "74074", "Cushing": "74023", "Perry": "73077", "Morrison": "73061", "Pawnee": "74058"}


def geocode(street: str, town: str, cache: dict) -> tuple[float, float] | None:
    """US Census one-line geocoder (free, no key). Cached in sources/geocode_cache.json."""
    addr = f"{street}, {town}, OK {ZIPS.get(town, '')}".strip()
    if addr in cache:
        return tuple(cache[addr]) if cache[addr] else None
    q = urllib.parse.urlencode({"address": addr, "benchmark": "Public_AR_Current", "format": "json"})
    try:
        with urllib.request.urlopen(f"{GEOCODER}?{q}", timeout=30) as resp:
            matches = json.loads(resp.read().decode())["result"]["addressMatches"]
    except Exception:  # noqa: BLE001 - geocoding is best effort
        return None  # not cached, so a later run retries
    hit = (matches[0]["coordinates"]["y"], matches[0]["coordinates"]["x"]) if matches else None
    cache[addr] = list(hit) if hit else None
    time.sleep(0.2)
    return hit


def jitter(town: str, name: str) -> tuple[float, float]:
    """Deterministic spread around the town center so unaddressed pins don't stack."""
    la, lo = TOWNS[town][:2]
    h = sum(ord(c) * (i + 1) for i, c in enumerate(name))
    return round(la + ((h % 97) - 48) * 0.00012, 5), round(lo + (((h // 97) % 97) - 48) * 0.00015, 5)


def same_business(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 6 and long_.startswith(short)


def merge_directories(out: list[dict], dropped: dict) -> int:
    """Add hand-curated directory listings from sources/*.tsv, skipping OSM duplicates."""
    cache_path = ROOT / "sources" / "geocode_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    existing = [(slug(r["name"]), r["town"]) for r in out]
    added = 0
    for tsv in sorted((ROOT / "sources").glob("*.tsv")):
        header_seen = False
        source_url = None
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if line.startswith("# http"):
                source_url = line[2:].strip()
                continue
            if not line.strip() or line.startswith("#"):
                continue
            if not header_seen:
                header_seen = True
                continue
            name, street, town, cat = (line.split("	") + ["", "", "", ""])[:4]
            name, street, town, cat = name.strip(), street.strip(), town.strip(), cat.strip()
            if town not in TOWNS:
                continue
            sl = slug(name)
            if any(t == town and same_business(sl, s) for s, t in existing):
                dropped["duplicate"] += 1
                continue
            existing.append((sl, town))
            latlon = geocode(street, town, cache) if street else None
            located = "address" if latlon else "town center (approx.)"
            lat, lon = latlon or jitter(town, name)
            out.append(
                {
                    "id": f"L-{tsv.stem[:2]}-{sl[:24]}",
                    "name": name,
                    "industry": cat,
                    "osm_type": None,
                    "city": town,
                    "town": town,
                    "state": "OK",
                    "address": street or None,
                    "website": None,
                    "lat": lat,
                    "lon": lon,
                    "located": located,
                    "miles_from_stillwater": round(haversine_miles(STILLWATER, (lat, lon)), 1),
                    "source_link": source_url,
                    "source": tsv.stem.replace("_", " ").title(),
                }
            )
            added += 1
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return added


def main() -> None:
    cache = ROOT / "local_osm_raw.json"
    raw = {}
    if cache.exists() and "--refresh" not in sys.argv:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        print("Using cached local_osm_raw.json (pass --refresh to refetch)")
    missing = [n for n in TOWNS if n not in raw]  # new towns get fetched on their own
    for name in missing:
        raw[name] = fetch_town(name, *TOWNS[name])
        print(f"{name}: {len(raw[name])} OSM elements", flush=True)
        time.sleep(3)
    if missing:
        cache.write_text(json.dumps(raw), encoding="utf-8")

    seen: set[str] = set()
    out: list[dict] = []
    dropped = {"non_business": 0, "chain": 0, "uncategorized": 0, "duplicate": 0}
    for town, elements in raw.items():
        for e in elements:
            t = e.get("tags") or {}
            if is_skipped(t):
                dropped["non_business"] += 1
                continue
            if is_chain(t):
                dropped["chain"] += 1
                continue
            cat = categorize(t)
            if not cat:
                dropped["uncategorized"] += 1
                continue
            key = slug(t["name"]) + "|" + town
            if key in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(key)
            lat = e.get("lat") or (e.get("center") or {}).get("lat")
            lon = e.get("lon") or (e.get("center") or {}).get("lon")
            out.append(
                {
                    "id": f"L-{e['type'][0]}{e['id']}",
                    "name": t["name"].strip(),
                    "industry": cat,
                    "osm_type": primary_type(t),
                    "city": t.get("addr:city") or town,
                    "town": town,
                    "state": "OK",
                    "address": address(t),
                    "website": t.get("website") or t.get("contact:website"),
                    "lat": lat,
                    "lon": lon,
                    "miles_from_stillwater": round(haversine_miles(STILLWATER, (lat, lon)), 1) if lat else None,
                    "source_link": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
                    "source": "OpenStreetMap",
                }
            )

    added = merge_directories(out, dropped)
    print(f"Directory listings added: {added}")

    out.sort(key=lambda r: (r["town"], r["industry"], r["name"]))
    (ROOT / "local_candidates.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    by_town: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for r in out:
        by_town[r["town"]] = by_town.get(r["town"], 0) + 1
        by_cat[r["industry"]] = by_cat.get(r["industry"], 0) + 1
    print(json.dumps({"kept": len(out), "dropped": dropped, "by_town": by_town, "by_industry": by_cat}, indent=1))


if __name__ == "__main__":
    main()
