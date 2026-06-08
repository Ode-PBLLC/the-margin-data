"""
Animated HYSPLIT trajectory map — interactive time slider for The Margin.

Encoding:
  - Time slider: scrub through hours to watch trajectories grow
  - Color by altitude: 3 bands (surface / mid / upper)
  - Point size: larger = closer to ground

Usage:
    python hysplit_viz_animated.py <path_to_gis_zip>

Source: NOAA ARL HYSPLIT (Stein et al., 2015) via READY
Location: EMR Metal Recycling, Camden NJ (39.926374, -75.128614)
"""

import os
import sys
import json
import zipfile
import tempfile
import glob
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import TimestampedGeoJson

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

# ── Brand colors (The Margin) ────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
SUBHEADING = "#373737"
BACKGROUND = "#EFEEED"

# ── Altitude color bands ─────────────────────────────────────────────────────
# Surface (0-60m): Margin Red — ground-level impact, most dangerous
# Mid (60-120m): Orange — elevated plume
# Upper (120m+): Yellow — high-altitude dispersal
ALT_BANDS = [
    {'label': 'Surface (< 60m)',  'max': 60,  'color': '#c60101', 'radius': 7},
    {'label': 'Mid (60–120m)',    'max': 120, 'color': '#e87d2f', 'radius': 5},
    {'label': 'Upper (> 120m)',   'max': 9999, 'color': '#f0c05a', 'radius': 3},
]

# ── EMR location ─────────────────────────────────────────────────────────────
# Source: EMR South Front Street facility, Camden NJ
EMR_LAT = 39.926374
EMR_LON = -75.128614


def get_alt_style(level_m):
    """Return color and radius for a given altitude."""
    for band in ALT_BANDS:
        if level_m <= band['max']:
            return band['color'], band['radius']
    return ALT_BANDS[-1]['color'], ALT_BANDS[-1]['radius']


def extract_and_parse(zip_path):
    """Extract zip, join shapefile + att file, return GeoDataFrame."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(tmpdir)

        shp_files = glob.glob(os.path.join(tmpdir, '*.shp'))
        att_files = glob.glob(os.path.join(tmpdir, '*.att'))

        if not shp_files or not att_files:
            print("ERROR: Missing .shp or .att file in zip")
            sys.exit(1)

        gdf = gpd.read_file(shp_files[0])
        gdf['id'] = gdf['id'].astype(int)

        rows = []
        with open(att_files[0]) as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 4:
                    pid = int(parts[0])
                    date_str = parts[1]
                    time_str = parts[2].strip()
                    hour = int(time_str[:2]) if len(time_str) >= 2 else 0
                    minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                    dt = pd.Timestamp(
                        year=int(date_str[:4]), month=int(date_str[4:6]),
                        day=int(date_str[6:8]), hour=hour, minute=minute,
                    )
                    rows.append({
                        'id': pid,
                        'traj_num': pid // 1000,
                        'datetime_utc': dt,
                        'level_m': float(parts[3]),
                    })

        att = pd.DataFrame(rows)
        merged = gdf.merge(att, on='id', how='inner')
        return gpd.GeoDataFrame(merged, geometry='geometry', crs=gdf.crs)


def build_animated_map(gdf, output_html):
    """Build Folium map with TimestampedGeoJson time slider."""
    m = folium.Map(
        location=[EMR_LAT, EMR_LON],
        zoom_start=8,
        tiles=None,
    )

    # Basemaps
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
    ).add_to(m)

    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Dark",
    ).add_to(m)

    # Build GeoJSON features for TimestampedGeoJson
    # Each feature is a point with a timestamp
    features = []
    for _, row in gdf.iterrows():
        color, radius = get_alt_style(row['level_m'])
        dt_eastern = row['datetime_utc'] - pd.Timedelta(hours=5)
        hour_label = dt_eastern.strftime('%-I:%M %p')
        date_label = dt_eastern.strftime('%b %-d')

        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [row.geometry.x, row.geometry.y],
            },
            'properties': {
                'time': row['datetime_utc'].isoformat(),
                'popup': f"{date_label} {hour_label} ET<br>{row['level_m']:.0f}m altitude",
                'icon': 'circle',
                'iconstyle': {
                    'fillColor': color,
                    'fillOpacity': 0.8,
                    'stroke': 'true',
                    'color': 'white',
                    'weight': 0.5,
                    'radius': radius,
                },
            },
        }
        features.append(feature)

    # Also add trajectory line segments that appear with time
    for traj_num, group in gdf.groupby('traj_num'):
        group = group.sort_values('datetime_utc')
        coords = [(row.geometry.x, row.geometry.y) for _, row in group.iterrows()]
        times = group['datetime_utc'].tolist()

        # Add progressive line segments
        for i in range(1, len(coords)):
            color, _ = get_alt_style(group['level_m'].iloc[i])
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'LineString',
                    'coordinates': coords[:i + 1],
                },
                'properties': {
                    'time': times[i].isoformat(),
                    'style': {
                        'color': color,
                        'weight': 2,
                        'opacity': 0.6,
                    },
                },
            }
            features.append(feature)

    timestamped = TimestampedGeoJson(
        {'type': 'FeatureCollection', 'features': features},
        period='PT1H',
        duration='PT2H',
        add_last_point=True,
        auto_play=False,
        loop=False,
        max_speed=4,
        loop_button=True,
        time_slider_drag_update=True,
    )
    timestamped.add_to(m)

    # EMR facility marker (always visible)
    folium.CircleMarker(
        location=[EMR_LAT, EMR_LON],
        radius=10,
        color=MARGIN_RED,
        fill=True,
        fillColor=MARGIN_RED,
        fillOpacity=1.0,
        popup="EMR Metal Recycling<br>South Front Street, Camden NJ",
        tooltip="EMR Metal Recycling — Fire Origin",
    ).add_to(m)

    # Title + legend overlay
    legend_html = f"""
    <div style="position: fixed; top: 10px; left: 60px; z-index: 9999;
                background: rgba(26,26,26,0.92); padding: 12px 18px; border-radius: 6px;
                font-family: sans-serif; box-shadow: 0 2px 8px rgba(0,0,0,0.5);
                max-width: 340px;">
        <div style="font-size: 15px; font-weight: bold; color: white;">
            Where Did the Smoke Go?
        </div>
        <div style="font-size: 11px; color: #aaa; margin-bottom: 8px;">
            EMR Metal Recycling fire — Camden, NJ — Feb 21, 2025
        </div>
        <div style="font-size: 10px; color: #ccc; margin-bottom: 3px;">
            <b>Altitude</b> &nbsp;(use slider below to scrub time)
        </div>
        <div style="display: flex; align-items: center; gap: 8px; margin: 3px 0;">
            <span style="display:inline-block; width:14px; height:14px; border-radius:50%;
                         background:{ALT_BANDS[0]['color']}; border:1px solid #fff;"></span>
            <span style="font-size:10px; color:#ccc;">{ALT_BANDS[0]['label']} — ground-level impact</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; margin: 3px 0;">
            <span style="display:inline-block; width:10px; height:10px; border-radius:50%;
                         background:{ALT_BANDS[1]['color']}; border:1px solid #fff;"></span>
            <span style="font-size:10px; color:#ccc;">{ALT_BANDS[1]['label']} — elevated plume</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; margin: 3px 0;">
            <span style="display:inline-block; width:6px; height:6px; border-radius:50%;
                         background:{ALT_BANDS[2]['color']}; border:1px solid #fff;"></span>
            <span style="font-size:10px; color:#ccc;">{ALT_BANDS[2]['label']} — high dispersal</span>
        </div>
        <div style="font-size: 8px; color: #666; margin-top: 8px;">
            NOAA ARL HYSPLIT (Stein et al., 2015) &nbsp;|&nbsp; GDAS archive
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl().add_to(m)
    m.save(output_html)
    print(f"Animated map saved: {output_html}")


def write_metadata(output_path):
    meta = {
        "output": output_path,
        "sources": [
            "NOAA ARL HYSPLIT trajectory model via READY (Stein et al., 2015)",
            "Meteorological data: GDAS 1-degree archive",
            "EMR facility location: 39.926374, -75.128614 (South Front St, Camden NJ)",
        ],
        "citation": "Stein, A.F., et al. (2015). NOAA's HYSPLIT Atmospheric Transport and "
                    "Dispersion Modeling System. Bull. Amer. Meteor. Soc., 96, 2059-2077.",
        "usage": "HYSPLIT results from ARCHIVE data — redistribution permitted per NOAA ARL agreement",
        "encoding": {
            "time": "Interactive slider — scrub through hours to watch plume expand",
            "color": "Altitude band (red=surface <60m, orange=mid 60-120m, yellow=upper >120m)",
            "point_size": "Altitude (larger=closer to ground)",
        },
        "date": "2025-02-21",
        "location": "Camden, NJ",
    }
    meta_path = output_path.replace('.html', '.meta.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {meta_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python hysplit_viz_animated.py <path_to_gis_zip>")
        sys.exit(1)

    zip_path = sys.argv[1]
    if not os.path.exists(zip_path):
        print(f"ERROR: File not found: {zip_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    gdf = extract_and_parse(zip_path)
    print(f"Loaded: {len(gdf)} points, {gdf['traj_num'].nunique()} trajectories")

    output_html = os.path.join(OUTPUT_DIR, "hysplit_smoke_animated.html")
    build_animated_map(gdf, output_html)
    write_metadata(output_html)


if __name__ == "__main__":
    main()
