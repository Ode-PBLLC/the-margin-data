"""
Convert HYSPLIT GIS trajectory output to time-stamped GeoJSON + interactive map.

Joins the shapefile (points with IDs) to the .att file (timestamps + levels)
to produce trajectories with full time information.

Usage:
    python hysplit_trajectory_to_geojson.py <path_to_zip>

Source: NOAA HYSPLIT trajectory model via READY (https://www.ready.noaa.gov/HYSPLIT.php)
Citation: Stein et al., 2015, NOAA Air Resources Laboratory
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
from shapely.geometry import LineString

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

# ── Brand colors (The Margin) ────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
SUBHEADING = "#373737"
BACKGROUND = "#EFEEED"

# ── EMR Metal Recycling location ─────────────────────────────────────────────
# Source: EMR South Front Street facility, Camden NJ
EMR_LAT = 39.926374
EMR_LON = -75.128614


def extract_zip(zip_path, tmpdir):
    """Extract zip and return path to extracted directory."""
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(tmpdir)
    return tmpdir


def parse_att_file(att_path):
    """Parse HYSPLIT .att file → DataFrame with id, datetime, level."""
    rows = []
    with open(att_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 4:
                point_id = int(parts[0])
                date_str = parts[1]  # YYYYMMDD
                time_str = parts[2].strip()  # HHMM or HH00
                level = float(parts[3])

                # Parse datetime
                hour = int(time_str[:2]) if len(time_str) >= 2 else 0
                minute = int(time_str[2:4]) if len(time_str) >= 4 else 0
                dt = pd.Timestamp(
                    year=int(date_str[:4]),
                    month=int(date_str[4:6]),
                    day=int(date_str[6:8]),
                    hour=hour,
                    minute=minute,
                )

                # Trajectory number from ID: first digit(s) = traj, last two = hour offset
                traj_num = point_id // 1000

                rows.append({
                    'id': point_id,
                    'traj_num': traj_num,
                    'datetime_utc': dt,
                    'level_m': level,
                })

    return pd.DataFrame(rows)


def join_shp_att(shp_path, att_path):
    """Join shapefile geometry to .att time data."""
    gdf = gpd.read_file(shp_path)
    att = parse_att_file(att_path)

    # Merge on ID
    gdf['id'] = gdf['id'].astype(int)
    merged = gdf.merge(att, on='id', how='inner')
    merged = gpd.GeoDataFrame(merged, geometry='geometry', crs=gdf.crs)

    return merged


def build_trajectory_lines(gdf):
    """Group points by trajectory number → LineString features with time range."""
    lines = []
    for traj_num, group in gdf.groupby('traj_num'):
        group = group.sort_values('datetime_utc')
        if len(group) < 2:
            continue

        coords = [(row.geometry.x, row.geometry.y) for _, row in group.iterrows()]
        line = LineString(coords)

        # Convert timestamps to Eastern time for display
        start_utc = group['datetime_utc'].iloc[0]
        end_utc = group['datetime_utc'].iloc[-1]
        start_et = start_utc - pd.Timedelta(hours=5)  # EST = UTC-5
        end_et = end_utc - pd.Timedelta(hours=5)
        start_level = group['level_m'].iloc[0]

        lines.append({
            'geometry': line,
            'traj_num': int(traj_num),
            'start_utc': str(start_utc),
            'end_utc': str(end_utc),
            'start_eastern': str(start_et),
            'end_eastern': str(end_et),
            'start_level_m': start_level,
            'num_points': len(group),
        })

    return gpd.GeoDataFrame(lines, crs='EPSG:4326')


def build_points_geojson(gdf, output_path):
    """Save time-stamped points as GeoJSON."""
    # Convert timestamps to strings for JSON serialization
    export = gdf.copy()
    export['datetime_utc'] = export['datetime_utc'].astype(str)
    # Add Eastern time
    export['datetime_eastern'] = (
        gdf['datetime_utc'] - pd.Timedelta(hours=5)
    ).astype(str)
    export['hour_eastern'] = (
        gdf['datetime_utc'] - pd.Timedelta(hours=5)
    ).dt.strftime('%I:%M %p')

    export.to_file(output_path, driver='GeoJSON')
    print(f"Points GeoJSON: {output_path} ({len(export)} points)")


def build_lines_geojson(lines_gdf, output_path):
    """Save trajectory lines as GeoJSON."""
    lines_gdf.to_file(output_path, driver='GeoJSON')
    print(f"Lines GeoJSON: {output_path} ({len(lines_gdf)} trajectories)")


def build_map(gdf, lines_gdf, output_html):
    """Create interactive Folium map with trajectories colored by time."""
    m = folium.Map(
        location=[EMR_LAT, EMR_LON],
        zoom_start=9,
        tiles=None,
    )

    # Dark satellite basemap
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

    # Color trajectories by start level
    levels = sorted(gdf['level_m'].unique()) if 'level_m' in gdf.columns else []
    # Use opacity to distinguish: higher = more opaque
    max_level = max(levels) if levels else 500

    # Draw trajectory lines
    for _, row in lines_gdf.iterrows():
        opacity = 0.3 + 0.5 * (row['start_level_m'] / max_level)
        coords = list(row.geometry.coords)
        folium.PolyLine(
            locations=[(c[1], c[0]) for c in coords],
            color=MARGIN_RED,
            weight=2.5,
            opacity=opacity,
            tooltip=f"Traj {row['traj_num']} | {row['start_level_m']:.0f}m | {row['start_eastern']} → {row['end_eastern']} ET",
        ).add_to(m)

    # Draw hourly points with time labels
    for _, row in gdf.iterrows():
        dt_eastern = row['datetime_utc'] - pd.Timedelta(hours=5)
        hour_label = dt_eastern.strftime('%I:%M %p')

        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=3,
            color='white',
            fill=True,
            fillColor='white',
            fillOpacity=0.7,
            weight=0.5,
            tooltip=f"{hour_label} ET | {row['level_m']:.0f}m altitude",
        ).add_to(m)

    # Mark EMR facility
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

    # Title
    title_html = f"""
    <div style="position: fixed; top: 10px; left: 60px; z-index: 9999;
                background: {BACKGROUND}; padding: 10px 16px; border-radius: 4px;
                font-family: sans-serif; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">
        <div style="font-size: 14px; font-weight: bold; color: {SUBHEADING};">
            Where Did the Smoke Go? — EMR Fire, Feb 21, 2025
        </div>
        <div style="font-size: 11px; color: {BODY_TEXT}; opacity: 0.7;">
            NOAA HYSPLIT forward trajectories from Camden, NJ &nbsp;|&nbsp;
            Hover for timestamps
        </div>
        <div style="font-size: 9px; color: {BODY_TEXT}; opacity: 0.5; margin-top: 4px;">
            Model: NOAA ARL HYSPLIT (Stein et al., 2015) &nbsp;|&nbsp;
            Met data: GDAS archive &nbsp;|&nbsp;
            Times shown in Eastern
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    folium.LayerControl().add_to(m)
    m.save(output_html)
    print(f"Map saved: {output_html}")


def write_metadata():
    return {
        "sources": [
            "NOAA ARL HYSPLIT trajectory model via READY (Stein et al., 2015)",
            "Meteorological data: GDAS 1-degree archive",
            "EMR facility location: 39.926374, -75.128614 (South Front St, Camden NJ)",
        ],
        "citation": "Stein, A.F., et al. (2015). NOAA's HYSPLIT Atmospheric Transport and Dispersion Modeling System. Bull. Amer. Meteor. Soc., 96, 2059-2077.",
        "usage": "HYSPLIT results from ARCHIVE data — redistribution permitted per NOAA ARL usage agreement",
        "date": "2025-02-21",
        "location": "Camden, NJ",
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python hysplit_trajectory_to_geojson.py <path_to_gis_zip>")
        sys.exit(1)

    zip_path = sys.argv[1]
    if not os.path.exists(zip_path):
        print(f"ERROR: File not found: {zip_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        extract_zip(zip_path, tmpdir)

        # Find shapefile and att file
        shp_files = glob.glob(os.path.join(tmpdir, '*.shp'))
        att_files = glob.glob(os.path.join(tmpdir, '*.att'))

        if not shp_files:
            print("ERROR: No .shp file found in zip")
            sys.exit(1)
        if not att_files:
            print("ERROR: No .att file found in zip")
            sys.exit(1)

        print(f"Shapefile: {os.path.basename(shp_files[0])}")
        print(f"Attribute: {os.path.basename(att_files[0])}")

        # Join shapefile + attributes
        gdf = join_shp_att(shp_files[0], att_files[0])
        print(f"Joined: {len(gdf)} points across {gdf['traj_num'].nunique()} trajectories")
        print(f"Time range: {gdf['datetime_utc'].min()} → {gdf['datetime_utc'].max()} UTC")

        # Build trajectory lines
        lines_gdf = build_trajectory_lines(gdf)

        # Output files
        points_path = os.path.join(OUTPUT_DIR, "hysplit_trajectory_points.geojson")
        lines_path = os.path.join(OUTPUT_DIR, "hysplit_trajectory_lines.geojson")
        html_path = os.path.join(OUTPUT_DIR, "hysplit_trajectory_map.html")
        meta_path = os.path.join(OUTPUT_DIR, "hysplit_trajectory.meta.json")

        build_points_geojson(gdf, points_path)
        build_lines_geojson(lines_gdf, lines_path)
        build_map(gdf, lines_gdf, html_path)

        meta = write_metadata()
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        print(f"Metadata: {meta_path}")


if __name__ == "__main__":
    main()
