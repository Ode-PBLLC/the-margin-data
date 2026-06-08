"""
Convert HYSPLIT KMZ output from NOAA READY to GeoJSON + interactive map.

Usage:
    python hysplit_kmz_to_geojson.py <path_to_kmz_file>

Outputs:
    - GeoJSON file with concentration contour polygons
    - Interactive Folium map (HTML) with smoke plume over satellite basemap

Source: NOAA HYSPLIT model via READY (https://www.ready.noaa.gov/HYSPLIT.php)
Location: EMR Metal Recycling, Camden NJ (39.926374, -75.128614)
"""

import os
import sys
import json
import zipfile
import tempfile
import geopandas as gpd
import folium
from folium.plugins import FloatImage
import kml2geojson

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

# ── Brand colors (The Margin) ────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
BACKGROUND = "#EFEEED"

# ── EMR Metal Recycling location ─────────────────────────────────────────────
# Source: EMR South Front Street facility, Camden NJ
EMR_LAT = 39.926374
EMR_LON = -75.128614


def extract_kml_from_kmz(kmz_path):
    """Extract the KML file from a KMZ archive."""
    with zipfile.ZipFile(kmz_path, 'r') as z:
        kml_files = [f for f in z.namelist() if f.endswith('.kml')]
        if not kml_files:
            raise ValueError(f"No KML file found in {kmz_path}")
        with z.open(kml_files[0]) as kml_file:
            return kml_file.read().decode('utf-8')


def kmz_to_geojson(kmz_path):
    """Convert KMZ to GeoJSON features."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract KML from KMZ
        kml_content = extract_kml_from_kmz(kmz_path)
        kml_path = os.path.join(tmpdir, "hysplit.kml")
        with open(kml_path, 'w') as f:
            f.write(kml_content)

        # Convert KML to GeoJSON
        features = kml2geojson.convert(kml_path, tmpdir)
        return features


def build_geojson(features, output_path):
    """Write cleaned GeoJSON with concentration metadata."""
    # kml2geojson returns a list of feature collections
    all_features = []
    for fc in features:
        if 'features' in fc:
            all_features.extend(fc['features'])

    # Filter to only polygon/multipolygon features (concentration contours)
    geo_features = [
        f for f in all_features
        if f.get('geometry', {}).get('type') in ('Polygon', 'MultiPolygon')
    ]

    if not geo_features:
        print(f"WARNING: No polygon features found. Total features: {len(all_features)}")
        print("Feature types found:", set(
            f.get('geometry', {}).get('type', 'None') for f in all_features
        ))
        # Fall back to all features
        geo_features = all_features

    geojson = {
        "type": "FeatureCollection",
        "features": geo_features,
        "properties": {
            "model": "NOAA HYSPLIT",
            "source_location": {"lat": EMR_LAT, "lon": EMR_LON},
            "description": "Smoke dispersion from EMR Metal Recycling fire, Camden NJ",
        }
    }

    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)

    print(f"GeoJSON saved: {output_path}")
    print(f"  Features: {len(geo_features)}")
    return geojson


def build_map(geojson_path, output_html):
    """Create interactive Folium map with smoke plume."""
    gdf = gpd.read_file(geojson_path)

    # Center map on EMR facility
    m = folium.Map(
        location=[EMR_LAT, EMR_LON],
        zoom_start=10,
        tiles=None,
    )

    # Dark satellite basemap (Margin brand)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
    ).add_to(m)

    # Add smoke plume polygons
    if len(gdf) > 0:
        # Color gradient: lighter = lower concentration, darker = higher
        style_function = lambda feature: {
            'fillColor': MARGIN_RED,
            'color': MARGIN_RED,
            'weight': 0.5,
            'fillOpacity': 0.4,
        }

        folium.GeoJson(
            gdf.to_json(),
            name="Smoke Dispersion",
            style_function=style_function,
            tooltip=folium.GeoJsonTooltip(
                fields=list(gdf.columns.drop('geometry', errors='ignore'))[:3],
                aliases=list(gdf.columns.drop('geometry', errors='ignore'))[:3],
            ) if len(gdf.columns) > 1 else None,
        ).add_to(m)

    # Mark EMR facility
    folium.CircleMarker(
        location=[EMR_LAT, EMR_LON],
        radius=8,
        color=MARGIN_RED,
        fill=True,
        fillColor=MARGIN_RED,
        fillOpacity=0.9,
        popup="EMR Metal Recycling<br>South Front Street, Camden NJ",
        tooltip="EMR Metal Recycling",
    ).add_to(m)

    # Title overlay
    title_html = f"""
    <div style="position: fixed; top: 10px; left: 60px; z-index: 9999;
                background: {BACKGROUND}; padding: 10px 16px; border-radius: 4px;
                font-family: sans-serif; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">
        <div style="font-size: 14px; font-weight: bold; color: {BODY_TEXT};">
            Smoke Dispersion — EMR Fire, Feb 27, 2025
        </div>
        <div style="font-size: 11px; color: {BODY_TEXT}; opacity: 0.7;">
            NOAA HYSPLIT forward dispersion model &nbsp;|&nbsp; Camden, NJ
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    folium.LayerControl().add_to(m)
    m.save(output_html)
    print(f"Map saved: {output_html}")


def write_metadata(kmz_source):
    """Write metadata for this output."""
    return {
        "sources": [
            "NOAA HYSPLIT forward dispersion model via READY (https://www.ready.noaa.gov/HYSPLIT.php)",
            f"Input KMZ: {os.path.basename(kmz_source)}",
            "EMR Metal Recycling facility location: 39.926374, -75.128614 (South Front St, Camden NJ)",
        ],
        "date": "2025-02-27",
        "location": "Camden, NJ",
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python hysplit_kmz_to_geojson.py <path_to_kmz_file>")
        print()
        print("Steps to get the KMZ from NOAA READY:")
        print("  1. Go to https://www.ready.noaa.gov/HYSPLIT.php")
        print("  2. Select 'Run HYSPLIT Dispersion Model' → 'Compute'")
        print("  3. Set source: 39.926374, -75.128614 (Camden NJ)")
        print("  4. Date: 2025-02-27, start hour ~17:00 UTC")
        print("  5. Run duration: 12-24 hours forward")
        print("  6. On results page, select output format: 'Google Earth'")
        print("  7. Download the .kmz file")
        print("  8. Run this script with the downloaded file")
        sys.exit(1)

    kmz_path = sys.argv[1]
    if not os.path.exists(kmz_path):
        print(f"ERROR: File not found: {kmz_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    basename = os.path.splitext(os.path.basename(kmz_path))[0]
    geojson_path = os.path.join(OUTPUT_DIR, f"hysplit_smoke_{basename}.geojson")
    html_path = os.path.join(OUTPUT_DIR, f"hysplit_smoke_{basename}.html")
    meta_path = os.path.join(OUTPUT_DIR, f"hysplit_smoke_{basename}.meta.json")

    # Convert KMZ → GeoJSON
    print(f"Converting: {kmz_path}")
    features = kmz_to_geojson(kmz_path)
    build_geojson(features, geojson_path)

    # Build interactive map
    build_map(geojson_path, html_path)

    # Save metadata
    meta = write_metadata(kmz_path)
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata saved: {meta_path}")


if __name__ == "__main__":
    main()
