"""Animated HYSPLIT plume + PurpleAir readings for an EMR Camden fire.

Run:
    python3 scripts/build_hysplit_animation.py --fire 2026-03-10 --corrected

Reads 30-min averaged HYSPLIT output across 4 release heights (10/30/100/200 m
AGL), computes a union "modeled smoke transport scenario" footprint per
timestep at a 10%-of-peak threshold (per the convention NOAA uses in HYSPLIT
ensemble displays), and animates it next to the PurpleAir sensor readings
at the same timestep.

Per Codex feedback for journalistic integrity:
 - Plume is rendered MONOCHROME GRAY (not in AQI colors). The map reserves
   the AQI color scale for measured PurpleAir readings only — eliminates the
   "looks like quantitative validation" trap.
 - Plume is labeled "Modeled smoke tracer (unit-source HYSPLIT, not µg/m³)".
 - Multi-height envelope is presented as a sensitivity bracket, not a
   probability map. No height weighting.
 - 30-min averaged output (not 10-min snapshots) — Codex: don't publish
   sub-hourly snapshots from a single 2500-particle run.

Output: figures/hysplit_animation_<fire>.html
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
import numpy as np
import pandas as pd
from folium.plugins import TimestampedGeoJson

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import EMR_LAT, EMR_LON, EMR_NAME, LOCAL_TZ, pa_dir
from src.fires import hysplit_fire_out_dir
from src.qc import is_stuck

PA_META_CSV = PROJECT_ROOT / "data" / "raw" / "sensors_metadata.csv"
HEIGHTS = [10, 30, 100, 200]


def parse_conc_file(path: Path) -> pd.DataFrame:
    """One con2asc -t file = one timestep. Per-row columns vary by HYSPLIT mode:
    averaged output uses `DAY HR LAT LON <value>` (5 cols).
    """
    df = pd.read_csv(path, sep=r"\s+", header=0, engine="python")
    cols = list(df.columns)
    df = df.rename(columns={cols[-3]: "lat", cols[-2]: "lon", cols[-1]: "value"})
    return df[["lat", "lon", "value"]]


def filename_timestamp(path: Path, year: int) -> datetime | None:
    """con2asc -t names files like conc_h10_069_2130 — Julian day + HHMM UTC.

    The Julian day is relative to the fire's year (passed in, since the
    filename doesn't carry it).
    """
    m = re.match(r"conc_h\d+_(\d+)_(\d{4})", path.name)
    if not m:
        return None
    julian, hhmm = int(m.group(1)), m.group(2)
    hh, mm = int(hhmm[:2]), int(hhmm[2:])
    base = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=julian - 1)
    return base.replace(hour=hh, minute=mm)


def load_all_runs(out_dir: Path, year: int) -> dict[datetime, dict[int, pd.DataFrame]]:
    """Returns {timestamp_utc: {height_m: df_lat_lon_value}}."""
    runs: dict[datetime, dict[int, pd.DataFrame]] = {}
    for h in HEIGHTS:
        for f in sorted(out_dir.glob(f"conc_h{h}_*")):
            if f.suffix in (".csv",) or f.is_dir():
                continue
            ts = filename_timestamp(f, year)
            if ts is None:
                continue
            df = parse_conc_file(f)
            runs.setdefault(ts, {})[h] = df[["lat", "lon", "value"]]
    return runs


def union_envelope(per_height: dict[int, pd.DataFrame], threshold: float) -> pd.DataFrame:
    """Union the 4 height runs: a cell is "in the envelope" if ANY height >= threshold.

    Returns cells with their MAX value across heights (so the visual emphasizes
    where ANY height shows plume mass).
    """
    frames = []
    for h, df in per_height.items():
        keep = df[df["value"] >= threshold].copy()
        keep["height"] = h
        frames.append(keep)
    if not frames:
        return pd.DataFrame(columns=["lat", "lon", "value", "height"])
    stacked = pd.concat(frames, ignore_index=True)
    return stacked.loc[stacked.groupby(["lat", "lon"])["value"].idxmax()].reset_index(drop=True)


def cells_to_features(cells: pd.DataFrame, dlat: float, dlon: float,
                      ts_iso: str, threshold: float) -> list[dict]:
    """Each cell → a square Polygon feature timestamped at ts_iso."""
    features = []
    for _, r in cells.iterrows():
        lat, lon = float(r["lat"]), float(r["lon"])
        ring = [
            [lon - dlon / 2, lat - dlat / 2],
            [lon + dlon / 2, lat - dlat / 2],
            [lon + dlon / 2, lat + dlat / 2],
            [lon - dlon / 2, lat + dlat / 2],
            [lon - dlon / 2, lat - dlat / 2],
        ]
        # Single monochrome gray for all plume cells — Codex: do not share
        # the AQI color scale with measured PurpleAir markers.
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "times": [ts_iso],
                "style": {"color": "#555555", "weight": 0.4, "opacity": 0.6,
                          "fillColor": "#888888", "fillOpacity": 0.40},
                "popup": (f"Modeled tracer (relative units): {r['value']:.2e}<br>"
                          f"Above 10%-of-peak threshold ({threshold:.2e})<br>"
                          f"Reached envelope at release height ≥{int(r['height'])} m AGL"),
            },
        })
    return features


def pa_features_for_time(target_utc: datetime, sensors_meta: pd.DataFrame,
                         pa_long: dict[int, pd.DataFrame], ts_iso: str) -> list[dict]:
    """Each sensor → a single Point feature with its reading at this timestep."""
    features = []
    for _, meta in sensors_meta.iterrows():
        idx = int(meta["sensor_index"])
        df = pa_long.get(idx)
        if df is None or df.empty:
            continue
        # Closest 10-min reading within ±20 min of target_utc.
        diffs = (df["time_utc"] - target_utc).abs()
        i = int(diffs.idxmin())
        if diffs.iloc[i] > timedelta(minutes=20):
            continue
        v = float(df.iloc[i]["pm2.5_atm"])
        # EPA PM2.5 AQI bands (2024)
        if v < 9: c = "#a8e0a8"
        elif v < 35: c = "#ffe066"
        elif v < 55: c = "#ffa64d"
        elif v < 125: c = "#e84f3f"
        elif v < 225: c = "#a04ba0"
        else: c = "#7d1f1f"
        radius_px = 5 + 18 * min(v / 200.0, 1.0) ** 0.5
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(meta["longitude"]),
                                                          float(meta["latitude"])]},
            "properties": {
                "times": [ts_iso],
                "icon": "circle",
                "iconstyle": {
                    "fillColor": c, "fillOpacity": 0.85, "stroke": True,
                    "color": "#ffffff", "weight": 1, "radius": radius_px,
                },
                "popup": (f"<b>{meta['name']}</b><br>"
                          f"<b>{v:.1f} µg/m³</b> (PurpleAir, 10-min)<br>"
                          f"{meta['miles_from_emr']:.2f} mi from EMR"),
            },
        })
    return features


def parse_pardump_ascii(path: Path) -> dict[datetime, list[tuple[float, float, float]]]:
    """Parse `par2asc` ASCII output. Returns {snapshot_utc: [(lat, lon, height_m), ...]}."""
    lines = path.read_text().splitlines()
    out: dict[datetime, list[tuple[float, float, float]]] = {}
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        if len(parts) == 7:
            try:
                numpar, numpol, yy, mo, da, hr, mn = (int(p) for p in parts)
            except ValueError:
                i += 1
                continue
            yyyy = 2000 + yy if yy < 100 else yy
            try:
                ts = datetime(yyyy, mo, da, hr, mn, tzinfo=timezone.utc)
            except ValueError:
                i += 1
                continue
            rows: list[tuple[float, float, float]] = []
            i += 1
            for _ in range(numpar):
                # Three records per particle. We only need record 2 (lat/lon/height).
                if i + 2 >= len(lines):
                    break
                # Record 1: mass values, skip
                i += 1
                # Record 2: TLAT TLON ZLVL SIGH SIGW SIGV
                r2 = lines[i].split()
                try:
                    lat = float(r2[0]); lon = float(r2[1]); zlvl = float(r2[2])
                    rows.append((lat, lon, zlvl))
                except (ValueError, IndexError):
                    pass
                i += 1
                # Record 3: PAGE HDWP PTYP PGRD NSORT, skip
                i += 1
            out[ts] = rows
        else:
            i += 1
    return out


def load_pa_long(pa_root, fire_date: str,
                 window_start: datetime, window_end: datetime) -> dict[int, pd.DataFrame]:
    fire_dir = pa_root / f"fire_{fire_date}"
    out: dict[int, pd.DataFrame] = {}
    for f in sorted(fire_dir.glob("sensor_*.parquet")):
        idx = int(f.stem.split("_")[1])
        df = pd.read_parquet(f)
        if df.empty:
            continue
        df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
        # QC the modeled window specifically — a sensor can be stuck during the
        # fire window but vary across the wider ±3-day pull (or vice versa).
        win = df[(df["time_utc"] >= window_start) & (df["time_utc"] <= window_end)]
        if is_stuck(win["pm2.5_atm"]) if not win.empty else is_stuck(df["pm2.5_atm"]):
            med = (win if not win.empty else df)["pm2.5_atm"].median()
            print(f"  [QC] dropping stuck sensor {idx}: pinned at "
                  f"~{med:.0f} µg/m³ (near-zero variance) during fire window")
            continue
        out[idx] = df[["time_utc", "pm2.5_atm"]]
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", default="2026-03-10",
                    help="Fire date YYYY-MM-DD (must be in data/fire_events.csv)")
    ap.add_argument("--corrected", action="store_true",
                    help="Use EPA Barkjohn-corrected PurpleAir data")
    args = ap.parse_args()
    suffix = "_corrected" if args.corrected else ""

    fire = args.fire
    hys_out_dir = hysplit_fire_out_dir(fire)
    noaa_csv = PROJECT_ROOT / "data" / "raw" / "noaa" / f"fire_{fire}.csv"
    regulatory_parquet = PROJECT_ROOT / "data" / "raw" / "regulatory" / f"fire_{fire}_airnow.parquet"

    runs = load_all_runs(hys_out_dir, int(fire[:4]))
    times = sorted(runs.keys())
    print(f"Loaded {len(times)} HYSPLIT timesteps × {len(HEIGHTS)} heights")
    for t in times:
        n = sum((df["value"] > 0).sum() for df in runs[t].values())
        print(f"  {t.isoformat()}  non-zero cells (sum across heights): {n}")

    # Global peak across ALL heights × timesteps → 10%-of-peak threshold.
    global_peak = 0.0
    for per_h in runs.values():
        for df in per_h.values():
            if not df.empty:
                global_peak = max(global_peak, float(df["value"].max()))
    threshold = 0.10 * global_peak
    print(f"Global peak modeled tracer: {global_peak:.3e}")
    print(f"Display threshold (10% of peak): {threshold:.3e}")

    # Grid cell size for square polygons (assume regular grid).
    sample = next(iter(next(iter(runs.values())).values()))
    lats = np.sort(sample["lat"].unique())
    lons = np.sort(sample["lon"].unique())
    dlat = float(np.median(np.diff(lats))) if len(lats) >= 2 else 0.005
    dlon = float(np.median(np.diff(lons))) if len(lons) >= 2 else 0.005

    # PurpleAir + sensor metadata + NOAA wind.
    pa_long = load_pa_long(pa_dir(args.corrected), fire, times[0], times[-1])
    sensors = pd.read_csv(PA_META_CSV)
    noaa = pd.read_csv(noaa_csv, parse_dates=["valid"])
    # NOAA times were written as local-tz naive → attach LOCAL_TZ.
    noaa["valid_local"] = noaa["valid"].dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="NaT")

    # Regulatory (AirNow / EPA FRM via OpenAQ) — hourly cadence.
    reg_df = pd.DataFrame()
    if regulatory_parquet.exists():
        reg_df = pd.read_parquet(regulatory_parquet)
        reg_df["time_utc"] = pd.to_datetime(reg_df["time_utc"], utc=True)
        reg_df["value_ugm3"] = pd.to_numeric(reg_df["value_ugm3"], errors="coerce")
        reg_df.loc[reg_df["value_ugm3"] < 0, "value_ugm3"] = np.nan  # AirNow -999 missing flag
        reg_df = reg_df.dropna(subset=["value_ugm3"])

    # Build timestamped features
    plume_features: list[dict] = []
    pa_features: list[dict] = []
    wind_features: list[dict] = []
    reg_features: list[dict] = []
    for t in times:
        ts_iso = t.isoformat().replace("+00:00", "Z")
        env = union_envelope(runs[t], threshold)
        plume_features.extend(cells_to_features(env, dlat, dlon, ts_iso, threshold))
        pa_features.extend(pa_features_for_time(t, sensors, pa_long, ts_iso))

        # Regulatory: hourly cadence. For each 30-min slider step, attach the
        # AirNow value for the nearest hour (within 30 min) — so the diamond
        # holds its color through both half-hour ticks of each hour.
        if not reg_df.empty:
            ts_next_iso = (t + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            for (loc_id, name, lat, lon, miles, provider), g in reg_df.groupby(
                ["location_id", "location_name", "lat", "lon", "miles_from_emr", "provider"]
            ):
                diffs = (g["time_utc"] - t).abs()
                ri = int(diffs.idxmin())
                if diffs.loc[ri] > timedelta(minutes=30):
                    continue
                v = float(g.loc[ri, "value_ugm3"])
                if v < 9: c = "#a8e0a8"
                elif v < 35: c = "#ffe066"
                elif v < 55: c = "#ffa64d"
                elif v < 125: c = "#e84f3f"
                elif v < 225: c = "#a04ba0"
                else: c = "#7d1f1f"
                size = int(round(14 + 16 * min(v / 50.0, 1.0) ** 0.5))
                # Diamond shape via a rotated square divIcon
                html_icon = (
                    f"<div style='width:{size}px;height:{size}px;background:{c};"
                    f"border:2px solid white;box-shadow:0 0 0 1.5px #333;"
                    f"transform:rotate(45deg);'></div>"
                )
                popup = (
                    f"<b>{name}</b> ({provider})<br>"
                    f"<b>{v:.1f} µg/m³</b> &nbsp;<i>(hourly avg, AirNow regulatory)</i><br>"
                    f"{miles:.2f} mi from EMR"
                )
                reg_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                    "properties": {
                        "times": [ts_iso, ts_next_iso],
                        "icon": "marker",
                        "iconstyle": {
                            "iconUrl": "data:image/svg+xml;utf8,"
                                       "<svg xmlns='http://www.w3.org/2000/svg' "
                                       f"width='{size+6}' height='{size+6}' "
                                       f"viewBox='0 0 {size+6} {size+6}'>"
                                       f"<rect x='3' y='3' width='{size}' height='{size}' "
                                       f"transform='rotate(45 {(size+6)/2} {(size+6)/2})' "
                                       f"fill='{c}' stroke='white' stroke-width='2'/></svg>",
                            "iconSize": [size + 6, size + 6],
                            "iconAnchor": [(size + 6) // 2, (size + 6) // 2],
                        },
                        "popup": popup,
                    },
                })

        # Nearest hourly wind sample within ±45 min.
        t_local = t.astimezone(ZoneInfo(LOCAL_TZ))
        diffs = (noaa["valid_local"] - t_local).abs()
        wi = int(diffs.idxmin())
        if diffs.iloc[wi] <= timedelta(minutes=45):
            wd = noaa.iloc[wi]["drct"]
            ws = noaa.iloc[wi]["sknt"]
            if pd.notna(wd) and pd.notna(ws):
                # Wind blows FROM `wd`, TO (wd+180). Convert to an end-point for a small arrow line.
                # Anchor at PHL coords; arrow length scales with wind speed in km.
                phl_lat, phl_lon = 39.8744, -75.2424
                to_dir = (wd + 180.0) % 360
                length_km = max(0.5, float(ws) * 0.2)  # 0.2 km per knot
                dy = length_km / 111.0 * np.cos(np.radians(to_dir))
                dx = length_km / (111.0 * np.cos(np.radians(phl_lat))) * np.sin(np.radians(to_dir))
                end_lat, end_lon = phl_lat + dy, phl_lon + dx
                wind_features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [[phl_lon, phl_lat], [end_lon, end_lat]]},
                    "properties": {
                        "times": [ts_iso, ts_iso],
                        "style": {"color": "#1a5f9c", "weight": 3, "opacity": 0.9},
                        "popup": f"PHL wind: from {wd:.0f}° at {ws:.0f} kt",
                    },
                })

    # --- Particle dump (single height = 30 m AGL representative case) ---
    pardump_txt = hys_out_dir / "PARDUMP.txt"
    particle_features: list[dict] = []
    if pardump_txt.exists():
        snapshots = parse_pardump_ascii(pardump_txt)
        print(f"Particle snapshots: {len(snapshots)}")
        snap_times = sorted(snapshots.keys())
        for ts in snap_times:
            particles = snapshots[ts]
            # Show each snapshot's particles for the full hour by tagging with both
            # the snapshot time and the next 30-min slider tick.
            ts_iso = ts.isoformat().replace("+00:00", "Z")
            ts_next_iso = (ts + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
            print(f"  {ts.isoformat()}  particles: {len(particles)}")
            for lat, lon, height_m in particles:
                # Color by altitude: ground-hugging vs lofted. Light gray = surface,
                # darker = aloft. Single hue family to avoid implying chemistry/AQI.
                if height_m < 100: c = "#bbbbbb"
                elif height_m < 300: c = "#888888"
                elif height_m < 800: c = "#555555"
                else: c = "#222222"
                particle_features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "times": [ts_iso, ts_next_iso],
                        "icon": "circle",
                        "iconstyle": {
                            "fillColor": c, "fillOpacity": 0.7, "stroke": False,
                            "radius": 1.8,
                        },
                    },
                })

    print(f"Plume features: {len(plume_features)}  PA features: {len(pa_features)}  "
          f"Wind features: {len(wind_features)}  Particle features: {len(particle_features)}  "
          f"Regulatory features: {len(reg_features)}")

    # --- Build the map ---
    fmap = folium.Map(location=[EMR_LAT, EMR_LON], zoom_start=12,
                      tiles="cartodbpositron", control_scale=True)

    # Static "cumulative footprint" layers (max over all timesteps × heights),
    # produced by scripts/build_hysplit_footprint.py. Both are toggleable via
    # LayerControl; off by default so they don't clash with the animation.
    footprint_cells = PROJECT_ROOT / "data" / "processed" / f"hysplit_footprint_cells_{fire}.geojson"
    footprint_contours = PROJECT_ROOT / "data" / "processed" / f"hysplit_footprint_contours_{fire}.geojson"

    if footprint_cells.exists():
        cells_gj = json.loads(footprint_cells.read_text())
        fg_cells = folium.FeatureGroup(name="Footprint — cells (max over 6 hr, ≥1% of peak)",
                                       show=False)
        # Color cells by fraction-of-peak using a sequential gray ramp.
        for f in cells_gj["features"]:
            frac = f["properties"].get("fraction_of_peak", 0.0)
            # Log-scale gray: lower fractions lighter, higher darker.
            t = max(0.0, min(1.0, (np.log10(max(frac, 1e-4)) + 4) / 4))
            shade = int(220 - 180 * t)
            color = f"#{shade:02x}{shade:02x}{shade:02x}"
            folium.GeoJson(
                f, name=None,
                style_function=lambda x, c=color: {
                    "fillColor": c, "color": "#444", "weight": 0.2,
                    "fillOpacity": 0.55,
                },
                tooltip=f"Max tracer (relative): {f['properties']['max_tracer_relative']:.2e}  "
                        f"({frac*100:.1f}% of peak)",
            ).add_to(fg_cells)
        fg_cells.add_to(fmap)

    if footprint_contours.exists():
        contours_gj = json.loads(footprint_contours.read_text())
        # Render the three bands together so toggling is one click.
        band_styles = {
            "outer_1pct":    {"fill": "#cccccc", "opacity": 0.35, "label": "outer extent (≥1% of peak)"},
            "core_10pct":    {"fill": "#888888", "opacity": 0.55, "label": "plume core (≥10% of peak)"},
            "hotspot_50pct": {"fill": "#333333", "opacity": 0.75, "label": "hotspot (≥50% of peak)"},
        }
        fg_contours = folium.FeatureGroup(
            name="Footprint — smooth contour polygons (1% / 10% / 50% of peak)",
            show=True,
        )
        # Draw outer first so smaller polygons sit on top.
        for label in ["outer_1pct", "core_10pct", "hotspot_50pct"]:
            for f in contours_gj["features"]:
                if f["properties"]["band"] != label:
                    continue
                s = band_styles[label]
                folium.GeoJson(
                    f,
                    style_function=lambda x, s=s: {
                        "fillColor": s["fill"], "color": s["fill"],
                        "weight": 1.0, "opacity": 0.9,
                        "fillOpacity": s["opacity"],
                    },
                    tooltip=f"Cumulative footprint: {s['label']}",
                ).add_to(fg_contours)
        fg_contours.add_to(fmap)

    # Static reference layers
    for r_mi in (1.0, 2.0, 5.0):
        folium.Circle([EMR_LAT, EMR_LON], radius=r_mi * 1609.344, color="#c60101",
                      weight=0.8, opacity=0.45, fill=False, dash_array="4 4",
                      interactive=False).add_to(fmap)
    folium.Marker(
        [EMR_LAT, EMR_LON],
        icon=folium.Icon(color="red", icon="fire", prefix="fa"),
        tooltip=EMR_NAME,
        z_index_offset=1000,
    ).add_to(fmap)
    # PHL anchor
    folium.CircleMarker(
        [39.8744, -75.2424], radius=4, color="#1a5f9c", weight=1.5,
        fill=True, fill_color="#1a5f9c", fill_opacity=0.4,
        tooltip="PHL ASOS station (wind data)",
    ).add_to(fmap)

    # All time-animated features go into one TimestampedGeoJson, transition
    # duration set short so the slider stays responsive.
    fc = {
        "type": "FeatureCollection",
        "features": plume_features + pa_features + wind_features + particle_features + reg_features,
    }
    TimestampedGeoJson(
        fc,
        period="PT30M",
        duration="PT29M",           # ~30 min minus a buffer so consecutive
                                    # features don't overlap at boundary ticks.
        add_last_point=False,
        auto_play=False,
        loop=True,
        max_speed=8,
        loop_button=True,
        date_options="YYYY-MM-DD HH:mm 'UTC'",
        time_slider_drag_update=True,
        transition_time=200,        # Brief fade keeps the swap smooth.
    ).add_to(fmap)

    # Toggleable layer control — picks up every FeatureGroup with a name.
    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    # Title bar
    title_html = (
        "<div style='position: fixed; top: 12px; left: 50%; transform: translateX(-50%); "
        "z-index: 9999; background: white; padding: 8px 18px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        f"<b>EMR Camden fire, {fire}</b> · "
        "<span style='color:#555'>Modeled smoke tracer</span> & "
        "<span style='color:#c60101'>measured PurpleAir PM2.5</span> over time"
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(title_html))

    # Legend (top-right) — also moved off the bottom edge to clear the time slider.
    legend_html = (
        "<div style='position: fixed; top: 72px; right: 18px; z-index: 9999; "
        "background: white; padding: 10px 14px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; font-size: 11px; "
        "max-width: 280px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        "<b>Measured PM2.5 (EPA 2024 AQI band)</b><br>"
        "<b>Circles</b> = PurpleAir (low-cost, 10-min). "
        "<b>Diamonds ◆</b> = AirNow / EPA FRM regulatory (hourly).<br>"
        "<span style='color:#a8e0a8'>●</span> Good (0–9 µg/m³) &nbsp;"
        "<span style='color:#ffe066'>●</span> Moderate (9–35)<br>"
        "<span style='color:#ffa64d'>●</span> USG (35–55) &nbsp;"
        "<span style='color:#e84f3f'>●</span> Unhealthy (55–125)<br>"
        "<span style='color:#a04ba0'>●</span> Very Unhealthy (125–225) &nbsp;"
        "<span style='color:#7d1f1f'>●</span> Hazardous (225+)<br>"
        "<hr style='margin:6px 0;border:0;border-top:1px solid #ccc'>"
        "<b>Modeled tracer (gray cells)</b>: NOAA HYSPLIT v5.4.2 with HRRR 3-km met, "
        "unit-source emission rate, 30-min averaged output. "
        "Cells shown are above 10% of the simulation's peak modeled tracer value "
        "(NOAA's convention for ensemble plume displays), unioned across 4 release "
        "heights (10, 30, 100, 200 m AGL) as a source-height sensitivity envelope."
        "<br><br><b>Modeled particles (small dark dots)</b>: individual HYSPLIT "
        "Lagrangian particles from the 30 m release run, dumped hourly. Shade darkens with altitude "
        "(light gray &lt; 100 m, darker for higher in the column)."
        "<br><hr style='margin:6px 0;border:0;border-top:1px solid #ccc'>"
        "<i style='color:#666'>Wind arrow = PHL ASOS surface wind, drawn from the "
        "station <b>in the direction the wind is going</b>. Length scales with speed.</i>"
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(legend_html))

    # Caveats / methodology — placed at TOP-LEFT to clear the TimestampedGeoJson
    # play controls / slider that lives at the bottom of the map.
    caveat_html = (
        "<div style='position: fixed; top: 72px; left: 18px; z-index: 9999; "
        "background: white; padding: 10px 14px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; font-size: 11px; "
        "max-width: 320px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        "<b>How to read this</b><br>"
        "Gray cells are the <b>modeled smoke transport scenario</b> &mdash; relative "
        "concentrations from a unit-source HYSPLIT run. They are <b>not</b> measured "
        "or estimated µg/m³ and carry no calibration to any specific fire emission "
        "rate. Only the <b>shape and direction</b> of the modeled plume are meaningful.<br><br>"
        f"Colored dots are the <b>actual PurpleAir 10-min readings</b> "
        f"({'EPA Barkjohn-corrected' if args.corrected else 'uncorrected ATM channel'}) "
        "closest to each timestep. Color follows EPA's 2024 PM2.5 AQI band.<br><br>"
        "<b>Why the model and sensors don't peak at the same moment:</b> the "
        "modeled shading is a 30-minute average of column concentration (0&ndash;100&nbsp;m AGL) "
        "on 500&nbsp;m cells, while PurpleAir samples are 10-minute averages at ~3&nbsp;m "
        "above ground. In light, shifting winds"
        + (" (PHL ASOS recorded 140&deg;&ndash;240&deg; during the burn)"
           if fire == "2026-03-10" else "")
        + ", near-source sensor peaks can legitimately occur earlier or "
        "later than the modeled column plume passes overhead.<br><br>"
        "<b>Other caveats:</b> 3-km HRRR meteorology drives the transport &mdash; "
        "the 500&nbsp;m display grid is a sampling choice, not a claim of 500&nbsp;m "
        "predictive skill. HYSPLIT places elevated releases at their final height "
        "(not along the rising trajectory), and the closest sensor (0.4&nbsp;mi) is "
        "inside NOAA's caution zone for HYSPLIT short-range timing. No dry or wet "
        "deposition is modeled &mdash; mass remains airborne throughout."
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(caveat_html))

    out = PROJECT_ROOT / "figures" / f"hysplit_animation_{fire}{suffix}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out))
    print(f"Wrote {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
