"""
Build dev-team handoff bundle for the Camden EMR story.
========================================================
Extracts the inlined data out of the two Folium/Leaflet maps in the
reviewed visualization bundle and writes stylized GeoJSONs (Leaflet style
options baked into feature properties), plus copies the rendered files
as visual references:

  1. HYSPLIT exposure map      — 01b_hysplit_still_2026-03-10_corrected.html
  2. Receptors + demographics  — 03_receptors_and_demographics_map.html
  3. All-fires PM2.5 grid      — 09b_all_fires_pm25_grid_adjusted.png (reference only)

All outputs land in: camden/handoff/<n>_<topic>/

The bundle HTMLs are the authoritative data carriers here (the analysis
pipeline that produced them inlines every feature into the HTML).

    python camden/scripts/build_handoff.py
"""

import html as html_mod
import json
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO
BUNDLE = REPO / "bundle"
HANDOFF = REPO / "handoff"

METERS_PER_MILE = 1609.344

# Style keys worth carrying over from Leaflet options (drop event/render noise)
STYLE_KEYS = ("color", "weight", "opacity", "fill", "fillColor", "fillOpacity",
              "dashArray", "radius")


def loads_js(s):
    """json.loads tolerant of Folium's trailing commas."""
    return json.loads(re.sub(r",\s*([}\]])", r"\1", s))


# ──────────────────────────────────────────────────────────────────────
# Generic Folium-HTML parsers
# ──────────────────────────────────────────────────────────────────────
def parse_overlays(html):
    """Layer-control overlay name -> feature_group var name."""
    block = re.search(r"overlays :  \{(.*?)\},\s*\};", html, re.S).group(1)
    return {json.loads(name): var
            for name, var in re.findall(r'("(?:[^"\\]|\\.)*") : ([a-z_0-9]+),', block)}


def parse_geojson_layers(html):
    """All geo_json_<hash> layers: data, styler, parent, tooltip."""
    layers = {}
    for h, data in re.findall(r"geo_json_([a-f0-9]+)_add\((\{.*?\})\);\n", html, re.S):
        layers[h] = {"fc": json.loads(data), "styler": None, "parent": None, "tooltip": None}
    for h, key, body in re.findall(
            r"function geo_json_([a-f0-9]+)_styler\(feature\) \{\s*"
            r"switch\(feature\.properties\.(\w+)\) \{(.*?)\}\s*\}\s*"
            r"function geo_json_\1_onEachFeature", html, re.S):
        cases = []
        for case_group, style in re.findall(r'((?:case "[^"]*":\s*)+)return (\{[^;]*\});', body):
            values = re.findall(r'case "([^"]*)":', case_group)
            cases.append((set(values), json.loads(style)))
        default = re.search(r"default:\s*return (\{[^;]*\});", body)
        layers[h]["styler"] = {
            "key": key,
            "cases": cases,
            "default": json.loads(default.group(1)) if default else None,
        }
    for h, parent in re.findall(r"geo_json_([a-f0-9]+)\.addTo\(([a-z_0-9]+)\);", html):
        layers[h]["parent"] = parent
    return layers


def parse_vectors(html):
    """All circle_marker/marker/circle/poly_line declarations."""
    out = []
    for var, kind, coords, opts, parent in re.findall(
            r"var ((?:circle_marker|marker|circle|poly_line)_[a-f0-9]+) = "
            r"L\.(circleMarker|marker|circle|polyline)\(\s*(\[.*?\]),\s*(\{.*?\})\s*\)"
            r"\.addTo\(([a-z_0-9]+)\);", html, re.S):
        out.append({"var": var, "kind": kind,
                    "coords": loads_js(coords), "opts": loads_js(opts),
                    "parent": parent})
    return out


def parse_tooltips(html):
    return {var: re.sub(r"\s+", " ", text).strip()
            for var, text in re.findall(
                r"([a-z_]+_[a-f0-9]+)\.bindTooltip\(\s*`\s*<div>\s*(.*?)\s*</div>\s*`",
                html, re.S)}


def parse_popups(html):
    """Bound-element var -> popup inner HTML."""
    html_divs = dict(re.findall(r"var html_([a-f0-9]+) = \$\(`<div[^>]*>(.*?)</div>`\)\[0\];",
                                html, re.S))
    popup_to_html = dict(re.findall(r"popup_([a-f0-9]+)\.setContent\(html_([a-f0-9]+)\);", html))
    out = {}
    for var, popup in re.findall(r"([a-z_]+_[a-f0-9]+)\.bindPopup\(popup_([a-f0-9]+)\)", html):
        h = popup_to_html.get(popup)
        if h in html_divs:
            out[var] = html_divs[h]
    return out


def parse_icons(html):
    """Marker var -> icon spec (AwesomeMarkers options or divIcon options)."""
    defs = {}
    for var, kind, opts in re.findall(
            r"var ((?:icon|div_icon)_[a-f0-9]+) = L\.(AwesomeMarkers\.icon|divIcon)\(\s*(\{.*?\})\s*\);",
            html, re.S):
        defs[var] = (kind, loads_js(opts))
    out = {}
    for marker, icon_var in re.findall(r"(marker_[a-f0-9]+)\.setIcon\(([a-z_0-9]+)\);", html):
        if icon_var in defs:
            out[marker] = defs[icon_var]
    return out


def popup_lines(popup_html):
    """Popup HTML -> list of plain-text lines."""
    lines = re.split(r"<br\s*/?>", popup_html)
    return [html_mod.unescape(re.sub(r"<[^>]+>", "", ln)).strip() for ln in lines if ln.strip()]


def clean_style(opts):
    return {k: opts[k] for k in STYLE_KEYS if k in opts and opts[k] is not None}


def styled_feature(feature, styler):
    """Apply a Folium styler switch to one feature; bake style into properties."""
    style = styler["default"]
    val = str(feature["properties"].get(styler["key"]))
    for values, case_style in styler["cases"]:
        if val in values:
            style = case_style
            break
    feature["properties"]["style"] = style
    return feature


def point(lat, lon):
    return {"type": "Point", "coordinates": [lon, lat]}


def write_fc(path, features, description, sources, extra=None):
    fc = {"type": "FeatureCollection",
          "name": path.stem,
          "x_description": description,
          "x_sources": sources,
          "x_built_by": "camden/scripts/build_handoff.py",
          "features": features}
    if extra:
        fc.update(extra)
    path.write_text(json.dumps(fc, ensure_ascii=False))
    print(f"    {path.name}: {len(features)} features, {path.stat().st_size/1024:.0f} KB")


SOURCES = {
    "hysplit": "NOAA HYSPLIT v5.4.2 unit-source tracer simulation, HRRR 3-km meteorology "
               "(2026-03-10 fire). Relative concentration — not measured µg/m³.",
    "purpleair": "PurpleAir API, 10-min data, EPA Barkjohn correction applied "
                 "(Barkjohn et al. 2021, Atmos. Meas. Tech.).",
    "airnow": "EPA AirNow regulatory monitors via OpenAQ v3 (hourly max during fire window).",
    "asos": "PHL ASOS surface observations (NWS/FAA), averaged over the fire window.",
    "ejscreen": "EPA EJScreen 2024 v2.32 via the Public Environmental Data Partners mirror "
                "on Harvard Dataverse (EPA removed EJScreen from its website 2025-02-05).",
    "nces": "NCES public/private school directories.",
    "cms": "CMS provider directories (certified hospitals / nursing homes).",
    "osm": "OpenStreetMap via Overpass API — © OpenStreetMap contributors.",
}


# ──────────────────────────────────────────────────────────────────────
# 1. HYSPLIT exposure map (01b)
# ──────────────────────────────────────────────────────────────────────
def build_hysplit():
    out_dir = HANDOFF / "01_hysplit_exposure_map"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[1] HYSPLIT exposure map → {out_dir.relative_to(ROOT)}")

    src = BUNDLE / "01b_hysplit_still_2026-03-10_corrected.html"
    shutil.copy2(src, out_dir / "reference.html")

    html = src.read_text()
    overlays = parse_overlays(html)
    layers = parse_geojson_layers(html)
    vectors = parse_vectors(html)
    tooltips = parse_tooltips(html)
    popups = parse_popups(html)
    icons = parse_icons(html)

    fg = {name: var for name, var in overlays.items()}

    # -- footprint bands (cumulative, smoothed) + raw 500 m cells
    def footprint_features(group_var):
        feats = []
        for h, layer in layers.items():
            if layer["parent"] != group_var:
                continue
            for f in layer["fc"]["features"]:
                f = styled_feature(f, layer["styler"])
                label = tooltips.get(f"geo_json_{h}")
                if label:
                    f["properties"]["label"] = label
                feats.append(f)
        return feats

    write_fc(out_dir / "footprint_cumulative.geojson",
             footprint_features(fg["Modeled tracer footprint (cumulative)"]),
             "Smoothed cumulative HYSPLIT tracer footprint for the 2026-03-10 EMR fire, "
             "three bands: ≥1%, ≥10%, ≥50% of peak modeled concentration.",
             [SOURCES["hysplit"]])

    write_fc(out_dir / "footprint_raw_cells.geojson",
             footprint_features(fg["Footprint — raw 500 m cells (≥1% of peak)"]),
             "Raw 500 m HYSPLIT grid cells at ≥1% of peak. Properties carry "
             "fraction_of_peak and max_tracer_relative per cell; fill darkens with fraction.",
             [SOURCES["hysplit"]])

    # -- PurpleAir sensors (circleMarkers)
    def parse_sensor_popup(p):
        lines = popup_lines(p)
        props = {"name": lines[0]}
        for ln in lines[1:]:
            m = re.match(r"([\d.]+) µg/m³", ln)
            if m:
                props["pm25_max_ugm3"] = float(m.group(1))
                continue
            m = re.match(r"AQI band: (.+)", ln)
            if m:
                props["aqi_band"] = m.group(1)
                continue
            m = re.match(r"Peak observed at: (.+)", ln)
            if m:
                props["peak_observed"] = m.group(1)
                continue
            m = re.match(r"([\d.]+) mi from EMR", ln)
            if m:
                props["distance_mi_from_emr"] = float(m.group(1))
        return props

    pa_feats = []
    for v in vectors:
        if v["kind"] == "circleMarker" and v["parent"] == fg["PurpleAir — max PM2.5 during fire window"]:
            props = parse_sensor_popup(popups[v["var"]])
            props["style"] = clean_style(v["opts"])
            lat, lon = v["coords"]
            pa_feats.append({"type": "Feature", "geometry": point(lat, lon), "properties": props})
    write_fc(out_dir / "sensors_purpleair.geojson", pa_feats,
             "PurpleAir sensors within ~2 mi of EMR: max corrected PM2.5 during the "
             "2026-03-10 fire window. Marker fill encodes AQI band; radius scales with value.",
             [SOURCES["purpleair"]])

    # -- Regulatory monitors (markers with divIcon diamonds)
    reg_feats = []
    for v in vectors:
        if v["kind"] == "marker" and v["parent"] == fg["Regulatory (AirNow / EPA FRM, hourly max)"]:
            props = parse_sensor_popup(popups[v["var"]])
            kind, icon_opts = icons[v["var"]]
            bg = re.search(r"background:([^;]+);", icon_opts.get("html", ""))
            props["style"] = {"shape": "diamond", "fill": bg.group(1) if bg else None}
            lat, lon = v["coords"]
            reg_feats.append({"type": "Feature", "geometry": point(lat, lon), "properties": props})
    write_fc(out_dir / "monitors_regulatory.geojson", reg_feats,
             "Regulatory monitors (AirNow / EPA FRM): hourly max PM2.5 during the fire "
             "window. Rendered as yellow diamonds in the reference.",
             [SOURCES["airnow"]])

    # -- Site context: EMR, PHL ASOS + wind vector, distance rings
    ctx = []
    for v in vectors:
        if not v["parent"].startswith("map_"):
            continue
        if v["kind"] == "marker":  # EMR
            lines = popup_lines(popups[v["var"]])
            kind, icon_opts = icons.get(v["var"], (None, {}))
            ctx.append({"type": "Feature", "geometry": point(*v["coords"]),
                        "properties": {"name": lines[0], "role": lines[1] if len(lines) > 1 else None,
                                       "icon": icon_opts}})
        elif v["kind"] == "circleMarker":  # PHL ASOS
            ctx.append({"type": "Feature", "geometry": point(*v["coords"]),
                        "properties": {"name": tooltips.get(v["var"]),
                                       "style": clean_style(v["opts"])}})
        elif v["kind"] == "circle":  # distance rings — GeoJSON has no circles; keep center+radius
            r = v["opts"]["radius"]
            ctx.append({"type": "Feature", "geometry": point(*v["coords"]),
                        "properties": {"name": f"{r / METERS_PER_MILE:g} mi ring around EMR",
                                       "radius_m": r, "radius_mi": round(r / METERS_PER_MILE, 4),
                                       "style": clean_style(v["opts"])}})
    for v in vectors:
        if v["kind"] == "polyline":  # PHL wind vector
            coords = [[lon, lat] for lat, lon in v["coords"]]
            ctx.append({"type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {"name": tooltips.get(v["var"]),
                                       "style": clean_style(v["opts"])}})
    write_fc(out_dir / "site_context.geojson", ctx,
             "EMR Eastern facility point, PHL ASOS station + mean wind vector during the "
             "fire, and 1/2/5-mile rings (GeoJSON points with radius_m — re-draw as circles).",
             [SOURCES["asos"],
              "EMR Eastern facility marker: from the camden pipeline maps. Per the "
              "reporter's landmarks CSV (2026-06-05) the fires occur at the shredder, "
              "1400 S. Front St — see landmarks_sophia.geojson for per-site addresses."])


# ──────────────────────────────────────────────────────────────────────
# 2. Receptors + demographics (03)
# ──────────────────────────────────────────────────────────────────────
DEMO_LAYERS = {  # overlay name -> (fill column slug, EJScreen value column)
    "Demographics: % low income": ("fill_low_income", "LOWINCPCT"),
    "Demographics: % people of color": ("fill_people_of_color", "PEOPCOLORPCT"),
    "Demographics: % under age 5": ("fill_under_age_5", "UNDER5PCT"),
    "Demographics: % age 65+": ("fill_age_65_plus", "OVER64PCT"),
}

RECEPTOR_SOURCES = {"NCES": SOURCES["nces"], "CMS": SOURCES["cms"], "OSM": SOURCES["osm"],
                    "CMS-certified": SOURCES["cms"]}


def build_receptors():
    out_dir = HANDOFF / "02_receptors_demographics"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[2] Receptors + demographics → {out_dir.relative_to(ROOT)}")

    src = BUNDLE / "03_receptors_and_demographics_map.html"
    # reference.html is NOT copied from the bundle anymore — it's rebuilt to the
    # 2026-06-05 layer decision by build_receptors_reference.py (run it after this).
    html = src.read_text()
    overlays = parse_overlays(html)
    layers = parse_geojson_layers(html)
    vectors = parse_vectors(html)
    tooltips = parse_tooltips(html)
    popups = parse_popups(html)
    icons = parse_icons(html)

    # -- one demographics file: identical geometry across the four layers,
    #    bake each layer's choropleth fill as its own property
    demo_geo = {name: h for h, layer in layers.items()
                for name, var in overlays.items() if layer["parent"] == var}
    base_hash = demo_geo["Demographics: % low income"]
    base = layers[base_hash]["fc"]["features"]
    ref_geoms = json.dumps([f["geometry"] for f in base], sort_keys=True)

    fills = {}
    for name, (col, _val) in DEMO_LAYERS.items():
        layer = layers[demo_geo[name]]
        assert json.dumps([f["geometry"] for f in layer["fc"]["features"]],
                          sort_keys=True) == ref_geoms, f"geometry mismatch in {name}"
        styler = layer["styler"]
        for f in layer["fc"]["features"]:
            style = styler["default"]
            geoid = str(f["properties"][styler["key"]])
            for values, case_style in styler["cases"]:
                if geoid in values:
                    style = case_style
                    break
            fills.setdefault(geoid, {})[col] = style["fillColor"]

    feats = []
    for f in base:
        props = dict(f["properties"])
        props.update(fills[str(props["GEOID"])])
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    write_fc(out_dir / "ejscreen_demographics.geojson", feats,
             "798 Census block groups around EMR with EJScreen 2024 indicators. The four "
             "choropleth fills from the reference map are baked in as fill_* columns "
             "(copy the one you want into your fill style). Values are fractions 0-1; "
             "*_display columns are formatted strings. Outline style on all four layers: "
             "color #666, weight 0.4, fillOpacity 0.65.",
             [SOURCES["ejscreen"]],
             extra={"x_fill_columns": {col: name for name, (col, _v) in DEMO_LAYERS.items()}})

    # -- receptor point layers (12): circleMarkers or icon markers
    def parse_receptor(v):
        props = {}
        p = popups.get(v["var"])
        if p:
            lines = popup_lines(p)
            props["name"] = lines[0]
            for ln in lines[1:]:
                m = re.match(r"([\d.]+) mi from EMR", ln)
                if m:
                    props["distance_mi_from_emr"] = float(m.group(1))
                elif not ln.startswith(props.get("category", "\x00")):
                    if "category" not in props and not re.match(r"[\d.]+ mi", ln):
                        props["category"] = ln
                    else:
                        props["address"] = ln
        else:  # tooltip-only layers
            t = tooltips.get(v["var"], "")
            m = re.match(r"(.+?) \(([\d.]+) mi\)$", t)
            if m:
                props["name"], props["distance_mi_from_emr"] = m.group(1), float(m.group(2))
            else:
                props["name"] = t or None
        if v["kind"] == "circleMarker":
            props["style"] = clean_style(v["opts"])
        else:
            kind, icon_opts = icons.get(v["var"], (None, {}))
            props["icon"] = {k: icon_opts[k] for k in ("markerColor", "icon", "iconColor")
                             if k in icon_opts}
        return {"type": "Feature", "geometry": point(*v["coords"]), "properties": props}

    by_parent = {}
    for v in vectors:
        if v["kind"] in ("circleMarker", "marker"):
            by_parent.setdefault(v["parent"], []).append(v)

    for name, var in overlays.items():
        if name in DEMO_LAYERS or var not in by_parent:
            continue
        # Editorial decision 2026-06-05: bulk OSM receptor layers are replaced by
        # the reporter's curated landmarks (build_landmarks.py). Keep NCES/CMS.
        if "(OSM)" in name:
            continue
        m = re.match(r"(.+?) \((\d+)\)$", name)
        label, expected = m.group(1), int(m.group(2))
        feats = [parse_receptor(v) for v in by_parent[var]]
        assert len(feats) == expected, f"{name}: {len(feats)} != {expected}"
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        srcs = list(dict.fromkeys(v for k, v in RECEPTOR_SOURCES.items() if k in name))
        write_fc(out_dir / f"receptors_{slug}.geojson", feats,
                 f"{name} — sensitive-receptor points near EMR with distance from the "
                 "facility; marker style/icon from the reference map baked in.",
                 srcs)

    # -- EMR point + distance rings on the base map
    ctx = []
    for v in vectors:
        if not v["parent"].startswith("map_"):
            continue
        if v["kind"] == "marker":
            kind, icon_opts = icons.get(v["var"], (None, {}))
            ctx.append({"type": "Feature", "geometry": point(*v["coords"]),
                        "properties": {"name": tooltips.get(v["var"]),
                                       "icon": {k: icon_opts[k] for k in
                                                ("markerColor", "icon", "iconColor")
                                                if k in icon_opts}}})
        elif v["kind"] == "circle":
            r = v["opts"]["radius"]
            ctx.append({"type": "Feature", "geometry": point(*v["coords"]),
                        "properties": {"name": f"{r / METERS_PER_MILE:g} mi ring around EMR",
                                       "radius_m": r, "radius_mi": round(r / METERS_PER_MILE, 4),
                                       "style": clean_style(v["opts"])}})
    write_fc(out_dir / "emr_site.geojson", ctx,
             "EMR Eastern facility point and distance rings from the reference map "
             "(ring features are points with radius_m — re-draw as circles).",
             ["EMR Eastern facility marker: from the camden pipeline maps. Per-site "
              "addresses (shredder, scrapyard, etc.) are in landmarks_sophia.geojson."])


# ──────────────────────────────────────────────────────────────────────
# 3. All-fires PM2.5 grid (09b) — reference image only
# ──────────────────────────────────────────────────────────────────────
def build_fires_grid():
    out_dir = HANDOFF / "03_fires_pm25_grid"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[3] All-fires PM2.5 grid → {out_dir.relative_to(ROOT)}")
    shutil.copy2(BUNDLE / "09b_all_fires_pm25_grid_adjusted.png", out_dir / "reference.png")
    # underlying 10-min series for the 4 locally-recoverable fire windows
    # (run extract_fire_timeseries.py first to populate data/processed/)
    n = 0
    for csv in sorted((ROOT / "data" / "processed").glob("fire_*_pm25_10min.csv")):
        shutil.copy2(csv, out_dir / csv.name)
        meta = csv.with_suffix(".meta.json")
        if meta.exists():
            shutil.copy2(meta, out_dir / meta.name)
        n += 1
    print(f"    reference.png + {n} fire CSVs copied")


if __name__ == "__main__":
    build_hysplit()
    build_receptors()
    build_fires_grid()
    print("\nDone.")
