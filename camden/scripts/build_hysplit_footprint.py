"""Compute the cumulative-footprint envelope from the multi-height HYSPLIT runs.

Reads every 30-min averaged concentration file under
tools/hysplit/output/fire_<date>/, takes the max value per cell across all
timesteps and all release heights, and emits two GeoJSON files representing
the modeled-tracer footprint:

  1. data/processed/hysplit_footprint_cells_<date>.geojson
     Honest grid-cell rendering: every 500-m cell that exceeded the
     threshold at any point. Square polygons, blocky but faithful to the
     underlying sampling resolution.

  2. data/processed/hysplit_footprint_contours_<date>.geojson
     Smooth contour polygons at 1% / 10% / 50% of the simulation peak,
     extracted with `contourpy`. Easier to read but implies smoothness
     beyond the sampling grid.

NOAA's HYSPLIT ensemble convention uses 1% and 10% bands; we add 50% for the
"core impact area." The MaxOverTime aggregation is NOT deposition — particles
remain airborne in the simulation. Caption accordingly when published.

Run:
    python3 scripts/build_hysplit_footprint.py --fire 2026-03-10
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import EMR_LAT, EMR_LON  # noqa: F401
from src.fires import hysplit_fire_out_dir

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
HEIGHTS = [10, 30, 100, 200]


def parse_conc_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", header=0, engine="python")
    cols = list(df.columns)
    df = df.rename(columns={cols[-3]: "lat", cols[-2]: "lon", cols[-1]: "value"})
    return df[["lat", "lon", "value"]]


def collect_max_grid(out_dir: Path) -> pd.DataFrame:
    """Max value per (lat, lon) across all timesteps × all release heights."""
    frames: list[pd.DataFrame] = []
    for h in HEIGHTS:
        for f in sorted(out_dir.glob(f"conc_h{h}_*")):
            if not re.match(r"conc_h\d+_\d+_\d{4}$", f.name):
                continue
            frames.append(parse_conc_file(f))
    if not frames:
        raise SystemExit(f"No conc_* files in {out_dir}. Run scripts/run_hysplit.py first.")
    stacked = pd.concat(frames, ignore_index=True)
    return stacked.groupby(["lat", "lon"], as_index=False)["value"].max()


def grid_to_array(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lats = np.sort(df["lat"].unique())
    lons = np.sort(df["lon"].unique())
    Z = np.zeros((len(lats), len(lons)), dtype=float)
    lat_idx = {v: i for i, v in enumerate(lats)}
    lon_idx = {v: i for i, v in enumerate(lons)}
    for _, r in df.iterrows():
        Z[lat_idx[r["lat"]], lon_idx[r["lon"]]] = r["value"]
    return lats, lons, Z


def cells_geojson(df: pd.DataFrame, threshold: float, dlat: float, dlon: float,
                  peak: float) -> dict:
    feats = []
    nz = df[df["value"] >= threshold]
    for _, r in nz.iterrows():
        lat, lon, v = float(r["lat"]), float(r["lon"]), float(r["value"])
        ring = [
            [lon - dlon / 2, lat - dlat / 2],
            [lon + dlon / 2, lat - dlat / 2],
            [lon + dlon / 2, lat + dlat / 2],
            [lon - dlon / 2, lat + dlat / 2],
            [lon - dlon / 2, lat - dlat / 2],
        ]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "max_tracer_relative": v,
                "fraction_of_peak": v / peak,
                "above_threshold": True,
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def contours_geojson(lats: np.ndarray, lons: np.ndarray, Z: np.ndarray,
                     levels: list[tuple[str, float]]) -> dict:
    """Use contourpy to extract smooth polygons at each level. Returns a
    FeatureCollection where each feature has a `band` label and a `lower` value.
    """
    try:
        import contourpy
    except ImportError:
        raise SystemExit("`contourpy` is required. pip install contourpy")
    from shapely.geometry import Polygon, MultiPolygon, mapping
    from shapely.ops import unary_union

    feats = []
    for label, lvl in levels:
        # contourpy works on a grid (lons increasing in x, lats in y).
        cg = contourpy.contour_generator(
            x=lons, y=lats, z=Z, fill_type="OuterCode",
        )
        # Filled contour from this level to +infinity.
        vertices_list, codes_list = cg.filled(lvl, float(Z.max() + 1.0))
        polys: list[Polygon] = []
        for verts, codes in zip(vertices_list, codes_list):
            # codes uses Path.MOVETO=1, LINETO=2, CLOSEPOLY=79 conventions.
            # Each MOVETO starts a new ring; subsequent vertices fill it.
            rings: list[list[tuple[float, float]]] = []
            current: list[tuple[float, float]] = []
            for (x, y), c in zip(verts, codes):
                if c == 1:  # MOVETO
                    if current:
                        rings.append(current)
                    current = [(float(x), float(y))]
                elif c == 2:  # LINETO
                    current.append((float(x), float(y)))
                elif c == 79:  # CLOSEPOLY
                    if current and current[0] != current[-1]:
                        current.append(current[0])
                    rings.append(current)
                    current = []
            if current:
                rings.append(current)
            if not rings:
                continue
            # The first ring is exterior; remaining (if any) are holes (rare here).
            try:
                poly = Polygon(rings[0], holes=rings[1:] if len(rings) > 1 else None)
                if poly.is_valid and not poly.is_empty:
                    polys.append(poly)
            except Exception:
                continue
        if not polys:
            continue
        merged = unary_union(polys)
        if isinstance(merged, Polygon):
            geoms = [merged]
        elif isinstance(merged, MultiPolygon):
            geoms = list(merged.geoms)
        else:
            geoms = []
        for g in geoms:
            feats.append({
                "type": "Feature",
                "geometry": mapping(g),
                "properties": {"band": label, "lower_relative": lvl},
            })
    return {"type": "FeatureCollection", "features": feats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", default="2026-03-10",
                    help="Fire date YYYY-MM-DD (selects tools/hysplit/output/fire_<date>/)")
    args = ap.parse_args()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    df = collect_max_grid(hysplit_fire_out_dir(args.fire))
    print(f"Cells in grid: {len(df)}")
    peak = float(df["value"].max())
    print(f"Cumulative peak across all heights+timesteps: {peak:.3e}")
    threshold_10pct = 0.10 * peak
    threshold_1pct = 0.01 * peak
    threshold_50pct = 0.50 * peak

    lats, lons, Z = grid_to_array(df)
    dlat = float(np.median(np.diff(lats)))
    dlon = float(np.median(np.diff(lons)))

    # --- Cells GeoJSON (everything above 1% of peak so the viewer can choose) ---
    cells = cells_geojson(df, threshold_1pct, dlat, dlon, peak)
    out_cells = PROCESSED_DIR / f"hysplit_footprint_cells_{args.fire}.geojson"
    out_cells.write_text(json.dumps(cells))
    print(f"Wrote {out_cells.relative_to(PROJECT_ROOT)} "
          f"({len(cells['features'])} cells ≥ 1% of peak)")

    # --- Contour-polygon GeoJSON (1%, 10%, 50% bands) ---
    contours = contours_geojson(lats, lons, Z, [
        ("outer_1pct", threshold_1pct),
        ("core_10pct", threshold_10pct),
        ("hotspot_50pct", threshold_50pct),
    ])
    out_contours = PROCESSED_DIR / f"hysplit_footprint_contours_{args.fire}.geojson"
    out_contours.write_text(json.dumps(contours))
    print(f"Wrote {out_contours.relative_to(PROJECT_ROOT)} "
          f"({len(contours['features'])} polygon features across 3 bands)")

    print()
    print("Thresholds (relative tracer units):")
    print(f"  outer_1pct   : {threshold_1pct:.3e}")
    print(f"  core_10pct   : {threshold_10pct:.3e}  ← matches NOAA HYSPLIT ensemble convention")
    print(f"  hotspot_50pct: {threshold_50pct:.3e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
