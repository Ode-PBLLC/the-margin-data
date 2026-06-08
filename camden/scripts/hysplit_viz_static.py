"""
Static HYSPLIT trajectory map — publication-ready for The Margin.

Encoding:
  - Color gradient (white → Margin Red): time progression (hours since fire)
  - Line weight: altitude (thicker = closer to ground, thinner = higher)

Usage:
    python hysplit_viz_static.py <path_to_gis_zip>

Source: NOAA ARL HYSPLIT (Stein et al., 2015) via READY
Location: EMR Metal Recycling, Camden NJ (39.926374, -75.128614)
"""

import os
import sys
import json
import zipfile
import tempfile
import glob
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.cm as cm
from matplotlib.lines import Line2D
from matplotlib.collections import LineCollection
import contextily as cx

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")

# ── Brand colors (The Margin) ────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
SUBHEADING = "#373737"
BACKGROUND = "#EFEEED"

# ── EMR location ─────────────────────────────────────────────────────────────
# Source: EMR South Front Street facility, Camden NJ
EMR_LAT = 39.926374
EMR_LON = -75.128614


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

        # Parse att file
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


def build_static_map(gdf, output_path):
    """Build publication-ready static map with time gradient + altitude weight."""
    # Reproject to Web Mercator for contextily basemap
    gdf_wm = gdf.to_crs(epsg=3857)

    # Compute hours since fire start
    t0 = gdf['datetime_utc'].min()
    gdf_wm['hours_since'] = (gdf['datetime_utc'] - t0).dt.total_seconds() / 3600
    max_hours = gdf_wm['hours_since'].max()

    # Time colormap: white → Margin Red
    cmap = mcolors.LinearSegmentedColormap.from_list(
        'smoke_time', ['#ffffff', MARGIN_RED]
    )
    norm_time = mcolors.Normalize(vmin=0, vmax=max_hours)

    # Altitude → line weight: lower = thicker (more ground-level impact)
    max_alt = gdf['level_m'].max()
    min_alt = max(gdf['level_m'].min(), 1)

    fig, ax = plt.subplots(figsize=(12, 10))
    fig.patch.set_facecolor(BACKGROUND)

    # Draw trajectory segments colored by time, weighted by altitude
    for traj_num, group in gdf_wm.groupby('traj_num'):
        group = group.sort_values('hours_since')
        if len(group) < 2:
            continue

        xs = group.geometry.x.values
        ys = group.geometry.y.values
        hours = group['hours_since'].values
        levels = group['level_m'].values

        # Build line segments
        points = np.column_stack([xs, ys]).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)

        # Color by time (midpoint of each segment)
        seg_hours = (hours[:-1] + hours[1:]) / 2
        colors = cmap(norm_time(seg_hours))

        # Weight by altitude (midpoint): lower altitude = thicker line
        seg_levels = (levels[:-1] + levels[1:]) / 2
        # Invert: low altitude → thick (3.0), high altitude → thin (0.8)
        linewidths = 0.8 + 2.2 * (1 - (seg_levels - min_alt) / max(max_alt - min_alt, 1))

        lc = LineCollection(segments, colors=colors, linewidths=linewidths,
                            capstyle='round', joinstyle='round')
        ax.add_collection(lc)

    # Set bounds with padding
    xmin, ymin, xmax, ymax = gdf_wm.total_bounds
    pad_x = (xmax - xmin) * 0.08
    pad_y = (ymax - ymin) * 0.08
    ax.set_xlim(xmin - pad_x, xmax + pad_x)
    ax.set_ylim(ymin - pad_y, ymax + pad_y)

    # Dark basemap
    cx.add_basemap(ax, source=cx.providers.CartoDB.DarkMatter, zoom=8)

    # EMR facility marker
    emr_wm = gpd.GeoSeries(
        gpd.points_from_xy([EMR_LON], [EMR_LAT]), crs='EPSG:4326'
    ).to_crs(epsg=3857)
    ax.plot(emr_wm.x.values[0], emr_wm.y.values[0],
            marker='o', color=MARGIN_RED, markersize=12,
            markeredgecolor='white', markeredgewidth=2, zorder=10)
    ax.annotate(
        'EMR Metal\nRecycling',
        xy=(emr_wm.x.values[0], emr_wm.y.values[0]),
        xytext=(15, 15), textcoords='offset points',
        fontsize=9, fontweight='bold', color='white',
        arrowprops=dict(arrowstyle='->', color='white', lw=1.2),
        zorder=10,
    )

    # ── Time colorbar ─────────────────────────────────────────────────────────
    sm = cm.ScalarMappable(cmap=cmap, norm=norm_time)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.5, aspect=20, pad=0.02)
    cbar.set_label('Hours After Fire Start (5:00 PM EST)', fontsize=9,
                   color='white', labelpad=10)
    cbar.ax.tick_params(colors='white', labelsize=8)
    # Add key hour labels
    tick_hours = [0, 6, 12, 24, 36, 48]
    tick_hours = [h for h in tick_hours if h <= max_hours]
    cbar.set_ticks(tick_hours)
    cbar.set_ticklabels([f'{int(h)}h' for h in tick_hours])

    # ── Altitude legend ───────────────────────────────────────────────────────
    legend_lines = [
        Line2D([0], [0], color=MARGIN_RED, linewidth=3.0, label='Near surface (~20m)'),
        Line2D([0], [0], color=MARGIN_RED, linewidth=1.8, label='Mid-level (~100m)'),
        Line2D([0], [0], color=MARGIN_RED, linewidth=0.8, label='Higher (~180m)'),
    ]
    leg = ax.legend(handles=legend_lines, loc='lower left', fontsize=8,
                    title='Altitude', title_fontsize=9,
                    facecolor='#1a1a1a', edgecolor='#333',
                    labelcolor='white')
    leg.get_title().set_color('white')

    # ── Title + attribution ───────────────────────────────────────────────────
    ax.set_axis_off()

    fig.text(
        0.05, 0.96,
        'Where Did the Smoke Go?',
        fontsize=18, fontweight='bold', color='white',
        ha='left', va='top',
    )
    fig.text(
        0.05, 0.925,
        'HYSPLIT forward trajectories from EMR Metal Recycling fire — Camden, NJ — Feb 21, 2025, 5:00 PM EST',
        fontsize=10, color='#aaaaaa',
        ha='left', va='top',
    )

    # Source attribution
    fig.text(
        0.05, 0.025,
        'Model: NOAA ARL HYSPLIT (Stein et al., 2015)  |  Met data: GDAS 1° archive  |  '
        'Basemap: CartoDB Dark Matter',
        fontsize=7, color='#888888',
        ha='left', va='bottom',
    )

    fig.subplots_adjust(left=0.02, right=0.92, top=0.91, bottom=0.05)
    fig.savefig(output_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)
    print(f"Static map saved: {output_path}")


def write_metadata(output_path):
    meta = {
        "output": output_path,
        "sources": [
            "NOAA ARL HYSPLIT trajectory model via READY (Stein et al., 2015)",
            "Meteorological data: GDAS 1-degree archive",
            "EMR facility location: 39.926374, -75.128614 (South Front St, Camden NJ)",
            "Basemap: CartoDB Dark Matter",
        ],
        "citation": "Stein, A.F., et al. (2015). NOAA's HYSPLIT Atmospheric Transport and "
                    "Dispersion Modeling System. Bull. Amer. Meteor. Soc., 96, 2059-2077.",
        "usage": "HYSPLIT results from ARCHIVE data — redistribution permitted per NOAA ARL agreement",
        "encoding": {
            "color": "Time since fire start (white=0h → red=48h)",
            "line_weight": "Altitude (thick=near surface, thin=higher altitude)",
        },
        "date": "2025-02-21",
        "location": "Camden, NJ",
    }
    meta_path = output_path.replace('.png', '.meta.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {meta_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python hysplit_viz_static.py <path_to_gis_zip>")
        sys.exit(1)

    zip_path = sys.argv[1]
    if not os.path.exists(zip_path):
        print(f"ERROR: File not found: {zip_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    gdf = extract_and_parse(zip_path)
    print(f"Loaded: {len(gdf)} points, {gdf['traj_num'].nunique()} trajectories")

    output_path = os.path.join(OUTPUT_DIR, "hysplit_smoke_static.png")
    build_static_map(gdf, output_path)
    write_metadata(output_path)


if __name__ == "__main__":
    main()
