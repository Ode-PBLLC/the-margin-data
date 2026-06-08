"""
HYSPLIT trajectory density map — kernel density heatmap for The Margin.

Shows where smoke most likely concentrated based on trajectory point density.
Areas where multiple trajectories overlap = higher likelihood of smoke impact.

Usage:
    python hysplit_viz_density.py <path_to_gis_zip>

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
from matplotlib.lines import Line2D
from scipy.ndimage import gaussian_filter
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


def compute_density(xs, ys, bounds, resolution=300, sigma=8):
    """Compute 2D kernel density on a grid."""
    xmin, ymin, xmax, ymax = bounds

    # Create grid
    x_edges = np.linspace(xmin, xmax, resolution)
    y_edges = np.linspace(ymin, ymax, resolution)

    # Bin points into grid
    H, _, _ = np.histogram2d(xs, ys, bins=[x_edges, y_edges])

    # Smooth with Gaussian kernel
    H = gaussian_filter(H.T, sigma=sigma)

    return H, x_edges, y_edges


def build_density_map(gdf, output_path):
    """Build density heatmap on dark basemap."""
    # Reproject to Web Mercator
    gdf_wm = gdf.to_crs(epsg=3857)

    xs = gdf_wm.geometry.x.values
    ys = gdf_wm.geometry.y.values

    # Compute hours since start for time-based weighting
    t0 = gdf['datetime_utc'].min()
    hours = (gdf['datetime_utc'] - t0).dt.total_seconds().values / 3600

    # Get bounds with padding
    pad = 0.1
    xmin, ymin, xmax, ymax = gdf_wm.total_bounds
    dx = (xmax - xmin) * pad
    dy = (ymax - ymin) * pad
    bounds = (xmin - dx, ymin - dy, xmax + dx, ymax + dy)

    fig, ax = plt.subplots(figsize=(12, 10))

    # Dark basemap first
    ax.set_xlim(bounds[0], bounds[2])
    ax.set_ylim(bounds[1], bounds[3])
    cx.add_basemap(ax, source=cx.providers.CartoDB.DarkMatter, zoom=8)

    # ── Density heatmap ───────────────────────────────────────────────────────
    # Custom colormap: transparent → white → Margin Red
    colors_list = [
        (0.0, (1, 1, 1, 0)),          # fully transparent
        (0.15, (1, 1, 1, 0.05)),       # barely visible white
        (0.3, (1, 0.85, 0.7, 0.2)),    # faint warm
        (0.5, (0.9, 0.4, 0.15, 0.45)), # orange
        (0.7, (0.78, 0.1, 0.02, 0.6)), # dark red
        (1.0, (0.78, 0.0, 0.01, 0.85)),# Margin Red, strong
    ]
    smoke_cmap = mcolors.LinearSegmentedColormap.from_list('smoke', colors_list)

    H, x_edges, y_edges = compute_density(xs, ys, bounds, resolution=400, sigma=10)

    # Mask zero/near-zero
    H_masked = np.where(H > H.max() * 0.01, H, np.nan)

    ax.imshow(
        H_masked,
        origin='lower',
        extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
        cmap=smoke_cmap,
        aspect='auto',
        interpolation='bilinear',
        zorder=3,
    )

    # ── Time contour rings ────────────────────────────────────────────────────
    # Show 6h, 12h, 24h extent as faint contour outlines
    for hour_mark, label in [(6, '6h'), (12, '12h'), (24, '24h')]:
        mask = hours <= hour_mark
        if mask.sum() < 3:
            continue
        sub_xs = xs[mask]
        sub_ys = ys[mask]
        H_sub, _, _ = compute_density(sub_xs, sub_ys, bounds, resolution=200, sigma=12)
        threshold = H_sub.max() * 0.05
        ax.contour(
            H_sub,
            levels=[threshold],
            extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
            colors=['white'],
            linewidths=0.8,
            linestyles='--',
            alpha=0.5,
            zorder=4,
        )
        # Label the contour
        # Find rightmost point above threshold for label placement
        rows_above = np.where(H_sub > threshold)
        if len(rows_above[0]) > 0:
            max_col = rows_above[1].max()
            row_at_max = rows_above[0][rows_above[1] == max_col].mean()
            lx = x_edges[0] + (x_edges[-1] - x_edges[0]) * max_col / H_sub.shape[1]
            ly = y_edges[0] + (y_edges[-1] - y_edges[0]) * row_at_max / H_sub.shape[0]
            ax.text(lx, ly, f' {label}', fontsize=8, color='white', alpha=0.7,
                    va='center', ha='left', fontweight='bold', zorder=5)

    # ── State boundaries ─────────────────────────────────────────────────────
    # Source: US Census Bureau TIGER/Line shapefiles via Natural Earth / geopandas
    try:
        import urllib.request
        states_url = "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json"
        states_path = os.path.join(tempfile.gettempdir(), "us_states.geojson")
        if not os.path.exists(states_path):
            urllib.request.urlretrieve(states_url, states_path)
        states = gpd.read_file(states_path).to_crs(epsg=3857)
        states.boundary.plot(ax=ax, color='#555555', linewidth=0.6, zorder=2)
    except Exception as e:
        print(f"Note: Could not load state boundaries: {e}")

    # ── City labels ───────────────────────────────────────────────────────────
    # Source: coordinates from US Census Bureau Gazetteer
    cities = [
        ('Philadelphia', 39.9526, -75.1652),
        ('Camden', 39.9259, -75.1196),
        ('Wilmington', 39.7391, -75.5398),
        ('Baltimore', 39.2904, -76.6122),
        ('Washington\nD.C.', 38.9072, -77.0369),
        ('Dover', 39.1582, -75.5244),
        ('Annapolis', 38.9784, -76.4922),
        ('Atlantic\nCity', 39.3643, -74.4229),
        ('Trenton', 40.2171, -74.7429),
        ('Richmond', 37.5407, -77.4360),
        ('Norfolk', 36.8508, -76.2859),
    ]

    for name, lat, lon in cities:
        pt = gpd.GeoSeries(
            gpd.points_from_xy([lon], [lat]), crs='EPSG:4326'
        ).to_crs(epsg=3857)
        px, py = pt.x.values[0], pt.y.values[0]

        # Only label if within map bounds
        if bounds[0] <= px <= bounds[2] and bounds[1] <= py <= bounds[3]:
            is_major = name in ('Philadelphia', 'Baltimore', 'Washington\nD.C.')
            fontsize = 9 if is_major else 7.5
            alpha = 0.9 if is_major else 0.6

            ax.plot(px, py, 'o', color='white', markersize=3 if is_major else 2,
                    alpha=alpha, zorder=8)
            ax.annotate(
                name, xy=(px, py),
                xytext=(8, 6), textcoords='offset points',
                fontsize=fontsize, color='white', alpha=alpha,
                ha='left', va='bottom', zorder=8,
            )

    # ── EMR facility marker ───────────────────────────────────────────────────
    emr_wm = gpd.GeoSeries(
        gpd.points_from_xy([EMR_LON], [EMR_LAT]), crs='EPSG:4326'
    ).to_crs(epsg=3857)
    ax.plot(emr_wm.x.values[0], emr_wm.y.values[0],
            marker='o', color='white', markersize=10,
            markeredgecolor=MARGIN_RED, markeredgewidth=2.5, zorder=10)
    ax.annotate(
        'EMR Metal\nRecycling',
        xy=(emr_wm.x.values[0], emr_wm.y.values[0]),
        xytext=(15, 20), textcoords='offset points',
        fontsize=9, fontweight='bold', color='white',
        arrowprops=dict(arrowstyle='->', color='white', lw=1.2),
        zorder=10,
    )

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_elements = [
        Line2D([0], [0], color='white', linestyle='--', linewidth=0.8,
               alpha=0.6, label='Extent at 6h / 12h / 24h'),
    ]
    leg = ax.legend(handles=legend_elements, loc='lower left', fontsize=8,
                    facecolor='#1a1a1a', edgecolor='#333', labelcolor='white')

    # ── Title + attribution ───────────────────────────────────────────────────
    ax.set_axis_off()

    fig.text(
        0.05, 0.96,
        'Estimated Smoke Transport Zone',
        fontsize=18, fontweight='bold', color='white',
        ha='left', va='top',
    )
    fig.text(
        0.05, 0.925,
        'Trajectory density from EMR Metal Recycling fire — Camden, NJ — Feb 21, 2025, 5:00 PM EST',
        fontsize=10, color='#aaaaaa',
        ha='left', va='top',
    )
    fig.text(
        0.05, 0.895,
        'Darker areas indicate where multiple modeled trajectories overlap — higher likelihood of smoke transport',
        fontsize=8.5, color='#888888', fontstyle='italic',
        ha='left', va='top',
    )

    fig.text(
        0.05, 0.025,
        'Model: NOAA ARL HYSPLIT (Stein et al., 2015)  |  Met data: GDAS 1° archive  |  '
        'Basemap: CartoDB Dark Matter  |  '
        'Note: Trajectories show transport paths, not measured concentrations',
        fontsize=6.5, color='#888888',
        ha='left', va='bottom',
    )

    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.05)
    fig.savefig(output_path, dpi=200, facecolor='#1a1a1a', bbox_inches='tight')
    plt.close(fig)
    print(f"Density map saved: {output_path}")


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
            "heatmap": "Kernel density of trajectory points — darker red = more trajectories overlap",
            "contours": "Dashed white lines show plume extent at 6h, 12h, 24h after fire start",
        },
        "caveat": "Density of trajectory points indicates likely transport paths, not measured "
                  "pollutant concentrations. Actual smoke dispersion depends on emission rate, "
                  "atmospheric stability, and mixing processes not captured by trajectory models.",
        "date": "2025-02-21",
        "location": "Camden, NJ",
    }
    meta_path = output_path.replace('.png', '.meta.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {meta_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python hysplit_viz_density.py <path_to_gis_zip>")
        sys.exit(1)

    zip_path = sys.argv[1]
    if not os.path.exists(zip_path):
        print(f"ERROR: File not found: {zip_path}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    gdf = extract_and_parse(zip_path)
    print(f"Loaded: {len(gdf)} points, {gdf['traj_num'].nunique()} trajectories")

    output_path = os.path.join(OUTPUT_DIR, "hysplit_smoke_density.png")
    build_density_map(gdf, output_path)
    write_metadata(output_path)


if __name__ == "__main__":
    main()
