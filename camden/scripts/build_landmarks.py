"""
Build the curated landmarks layer from Sophia's CSV.
====================================================
Geocodes the reporter-provided neighborhood landmarks and writes a stylized
GeoJSON into the handoff. This layer (plus the EJScreen demographic
choropleths) replaces the bulk OSM receptor layers per the 2026-06-05
editorial decision.

Coordinates: rows that already carry lat/long (decimal or DMS) are parsed
directly and flagged approximate where Sophia wrote "Roughly". Street
addresses are geocoded against the U.S. Census Bureau geocoder
(Public_AR_Current benchmark), with Nominatim (OSM) as fallback.

PRIVACY: the Biles/Allen home is generalized — coordinates rounded to
3 decimals (~100 m) and flagged. Exact address stays only in the source CSV.

    python camden/scripts/build_landmarks.py
"""

import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "data" / "raw" / "camden_landmarks.csv"
OUT_PATH = REPO / "handoff" / "02_receptors_demographics" / "landmarks_sophia.geojson"

# EMR shredder (1400 S. Front St) — site marker from the bundle maps
EMR_LAT, EMR_LON = 39.926309013731036, -75.12862946332181

# Camden-area sanity bbox for geocode results
BBOX = (-75.18, 39.88, -75.05, 39.98)  # lon_min, lat_min, lon_max, lat_max

# Normalized category -> marker styling (palette consistent with the handoff)
CATEGORIES = {
    "EMR": {"markerColor": "red", "icon": "industry", "hex": "#c60101"},
    "Industrial polluter": {"markerColor": "darkpurple", "icon": "cloud", "hex": "#5b3256"},
    "Sensitive receptor": {"markerColor": "blue", "icon": "child", "hex": "#2c5f7c"},
    "Neighborhood asset": {"markerColor": "green", "icon": "heart", "hex": "#5b8c5a"},
    "Resident home": {"markerColor": "gray", "icon": "home", "hex": "#888888"},
}


def normalize_category(type_raw):
    t = type_raw.strip().lower()
    if t == "emr":
        return "EMR"
    if "pollutor" in t or "polluter" in t:
        return "Industrial polluter"
    if "resident home" in t:
        return "Resident home"
    # mixed labels like "Neighborhood asset / sensitive receptor": first wins
    if t.startswith("sensitive receptor"):
        return "Sensitive receptor"
    if t.startswith("neighborhood asset"):
        return "Neighborhood asset"
    raise ValueError(f"unmapped Type: {type_raw!r}")


def parse_inline_coords(s):
    """Decimal 'lat, lon' or DMS like 39°56'09.6\"N 75°07'43.1\"W -> (lat, lon) or None."""
    m = re.search(r"(-?\d{2}\.\d+),\s*(-?\d{2,3}\.\d+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d+)°(\d+)'([\d.]+)\"([NS])\s+(\d+)°(\d+)'([\d.]+)\"([EW])", s)
    if m:
        lat = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
        lon = int(m.group(5)) + int(m.group(6)) / 60 + float(m.group(7)) / 3600
        if m.group(4) == "S":
            lat = -lat
        if m.group(8) == "W":
            lon = -lon
        return lat, lon
    return None


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def geocode_census(address):
    url = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?"
           + urllib.parse.urlencode({"address": address,
                                     "benchmark": "Public_AR_Current",
                                     "format": "json"}))
    matches = fetch_json(url)["result"]["addressMatches"]
    if matches:
        c = matches[0]["coordinates"]
        return c["y"], c["x"]
    return None


def geocode_nominatim(address):
    url = ("https://nominatim.openstreetmap.org/search?"
           + urllib.parse.urlencode({"q": address, "format": "json", "limit": 1}))
    res = fetch_json(url, headers={"User-Agent": "margin-2026-camden-story (ode.partners)"})
    time.sleep(1.1)  # Nominatim usage policy
    if res:
        return float(res[0]["lat"]), float(res[0]["lon"])
    return None


def haversine_mi(lat1, lon1, lat2, lon2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main():
    rows = [r for r in csv.DictReader(CSV_PATH.open()) if r["Name"].strip()]
    features = []
    for row in rows:
        name = row["Name"].strip()
        loc_raw = row["Address or lat/long"].strip()
        type_raw = row[[k for k in row if k.startswith("Type")][0]].strip()
        category = normalize_category(type_raw)

        props = {
            "name": name,
            "category": category,
            "type_raw": type_raw,
            "significance": row["Significance"].strip() or None,
            "address_raw": loc_raw,
            "icon": {"markerColor": CATEGORIES[category]["markerColor"],
                     "icon": CATEGORIES[category]["icon"],
                     "iconColor": "white"},
            "color_hex": CATEGORIES[category]["hex"],
        }

        coords = parse_inline_coords(loc_raw)
        if coords:
            props["geocode_source"] = "coordinates provided in reporter CSV"
            props["approximate"] = "roughly" in loc_raw.lower() or "Roughly" in loc_raw
        else:
            # strip parentheticals like "(also ID'd as 100 Atlantic Ave.)"
            alt = re.search(r"\((also[^)]*)\)", loc_raw)
            if alt:
                props["alt_address_note"] = alt.group(1)
            address = re.sub(r"\s*\([^)]*\)", "", loc_raw).strip()
            coords = geocode_census(address)
            if coords:
                props["geocode_source"] = "US Census Bureau geocoder (Public_AR_Current)"
            else:
                coords = geocode_nominatim(address)
                if coords:
                    props["geocode_source"] = "Nominatim/OSM geocoder — verify before publication"
        if not coords:
            print(f"  !! NO GEOCODE: {name} ({loc_raw}) — emitting null geometry")
            features.append({"type": "Feature", "geometry": None,
                             "properties": {**props, "needs_geocoding": True}})
            continue

        lat, lon = coords
        assert BBOX[0] < lon < BBOX[2] and BBOX[1] < lat < BBOX[3], \
            f"{name}: geocode outside Camden bbox: {lat}, {lon}"

        if category == "Resident home":
            lat, lon = round(lat, 3), round(lon, 3)  # ~100 m generalization
            props["location_treatment"] = (
                "GENERALIZED — coordinates rounded to ~100 m. Do not publish a "
                "more precise location; masking approach pending sign-off from "
                "reporter and sources (per reporter CSV note).")
            props.pop("address_raw")  # keep the exact address out of shared files

        props["distance_mi_from_emr_shredder"] = round(
            haversine_mi(lat, lon, EMR_LAT, EMR_LON), 2)
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": props})
        flag = " (approx)" if props.get("approximate") else ""
        print(f"  {name:42s} {category:21s} {lat:.5f},{lon:.5f}{flag}"
              f"  {props['distance_mi_from_emr_shredder']:5.2f} mi"
              f"  [{props['geocode_source'].split(' ')[0]}]")

    fc = {
        "type": "FeatureCollection",
        "name": "landmarks_sophia",
        "x_description": ("Curated neighborhood landmarks for the Camden EMR map, provided "
                          "by the reporter (2026-06-05): EMR sites, major air permittees, "
                          "sensitive receptors, neighborhood assets, narrative locations. "
                          "This layer + EJScreen demographics replace the bulk OSM receptor "
                          "layers. The resident home is generalized — see location_treatment."),
        "x_sources": ["Reporter-provided landmarks CSV (Sophia, 2026-06-05): "
                      "'Camden story items for Ode - Landmarks in the neighborhood.csv' — "
                      "DRAFT; significance text and evacuation claims trace to her sourcing.",
                      "Geocoding: US Census Bureau geocoder (Public_AR_Current benchmark); "
                      "Nominatim/OSM fallback where noted per-feature."],
        "x_built_by": "camden/scripts/build_landmarks.py",
        "features": features,
    }
    OUT_PATH.write_text(json.dumps(fc, ensure_ascii=False, indent=1))
    print(f"\n{OUT_PATH.name}: {len(features)} features, "
          f"{OUT_PATH.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
