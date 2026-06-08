"""Static "exposure summary" map for an EMR Camden fire.

One image, no slider. Combines:
  - The cumulative-footprint contour polygons (1% / 10% / 50% of modeled peak)
    from scripts/build_hysplit_footprint.py
  - The MAXIMUM PurpleAir PM2.5 each sensor saw during the simulated fire
    window (ignition → ignition + run hours, from data/fire_events.csv)
  - EMR location, distance rings, average PHL wind direction during the burn

Output: figures/hysplit_still_<fire>.html (~30 KB; no time animation).

Run:
    python3 scripts/build_hysplit_still.py --fire 2026-03-10 --corrected
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import folium
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import EMR_LAT, EMR_LON, EMR_NAME, LOCAL_TZ, pa_dir
from src.fires import DEFAULT_RUN_HOURS, fire_window_utc
from src.qc import is_stuck

PA_META_CSV = PROJECT_ROOT / "data" / "raw" / "sensors_metadata.csv"


def max_regulatory_per_site(window_start: datetime, window_end: datetime,
                            reg_parquet: Path) -> pd.DataFrame:
    """Hourly OpenAQ regulatory readings → max per site over the fire window."""
    if not reg_parquet.exists():
        return pd.DataFrame()
    df = pd.read_parquet(reg_parquet)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    df["value_ugm3"] = pd.to_numeric(df["value_ugm3"], errors="coerce")
    df.loc[df["value_ugm3"] < 0, "value_ugm3"] = np.nan  # AirNow -999 missing flag
    in_window = df[(df["time_utc"] >= window_start) & (df["time_utc"] <= window_end)
                   & df["value_ugm3"].notna()]
    if in_window.empty:
        return pd.DataFrame()
    rows = []
    for (loc_id, name), g in in_window.groupby(["location_id", "location_name"]):
        peak_i = g["value_ugm3"].idxmax()
        peak_row = g.loc[peak_i]
        rows.append({
            "location_id": int(loc_id),
            "name": name,
            "lat": float(peak_row["lat"]),
            "lon": float(peak_row["lon"]),
            "miles_from_emr": float(peak_row["miles_from_emr"]),
            "max_pm25": float(peak_row["value_ugm3"]),
            "peak_time_utc": peak_row["time_utc"].isoformat(),
            "peak_time_local": peak_row["time_utc"].tz_convert(LOCAL_TZ).strftime("%b %-d %-I:%M %p %Z"),
            "provider": peak_row.get("provider", "AirNow"),
        })
    return pd.DataFrame(rows).sort_values("miles_from_emr").reset_index(drop=True)


def max_pa_per_sensor(window_start: datetime, window_end: datetime,
                       pa_root, fire_date: str) -> pd.DataFrame:
    sensors = pd.read_csv(PA_META_CSV)
    rows = []
    for f in sorted((pa_root / f"fire_{fire_date}").glob("sensor_*.parquet")):
        idx = int(f.stem.split("_")[1])
        df = pd.read_parquet(f)
        if df.empty:
            continue
        df["t"] = pd.to_datetime(df["time_utc"], utc=True)
        in_window = df[(df["t"] >= window_start) & (df["t"] <= window_end)
                       & df["pm2.5_atm"].notna()]
        if in_window.empty:
            continue
        if is_stuck(in_window["pm2.5_atm"]):
            print(f"    [QC] dropping stuck sensor {idx}: pinned at "
                  f"~{in_window['pm2.5_atm'].median():.0f} µg/m³ (near-zero variance)")
            continue
        peak_idx = in_window["pm2.5_atm"].idxmax()
        peak_row = in_window.loc[peak_idx]
        meta = sensors[sensors["sensor_index"] == idx]
        if meta.empty:
            continue
        rows.append({
            "sensor_index": idx,
            "name": meta.iloc[0]["name"],
            "lat": float(meta.iloc[0]["latitude"]),
            "lon": float(meta.iloc[0]["longitude"]),
            "miles_from_emr": float(meta.iloc[0]["miles_from_emr"]),
            "max_pm25": float(peak_row["pm2.5_atm"]),
            "peak_time_utc": peak_row["t"].isoformat(),
            "peak_time_local": peak_row["t"].tz_convert(LOCAL_TZ).strftime("%b %d %I:%M %p %Z"),
        })
    if not rows:
        # No PurpleAir for this fire (e.g. fires before PA coverage started 2021-02-03).
        return pd.DataFrame(columns=["sensor_index", "name", "lat", "lon",
                                     "miles_from_emr", "max_pm25",
                                     "peak_time_utc", "peak_time_local"])
    return pd.DataFrame(rows).sort_values("miles_from_emr").reset_index(drop=True)


def avg_wind_during_window(noaa_csv: Path, window_start: datetime,
                           window_end: datetime) -> tuple[float, float] | None:
    if not noaa_csv.exists():
        return None
    df = pd.read_csv(noaa_csv, parse_dates=["valid"])
    df["valid"] = df["valid"].dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="NaT")
    df["valid_utc"] = df["valid"].dt.tz_convert("UTC")
    sub = df[(df["valid_utc"] >= window_start) & (df["valid_utc"] <= window_end)].copy()
    sub = sub.dropna(subset=["drct", "sknt"])
    if sub.empty:
        return None
    # Vector-average wind direction (don't naively average degrees).
    u = -sub["sknt"] * np.sin(np.radians(sub["drct"]))   # eastward component
    v = -sub["sknt"] * np.cos(np.radians(sub["drct"]))   # northward component
    u_mean, v_mean = float(u.mean()), float(v.mean())
    spd = float(np.sqrt(u_mean**2 + v_mean**2))
    # Direction wind blows TO (so reader sees plume direction).
    dir_to = (np.degrees(np.arctan2(u_mean, v_mean)) + 360.0) % 360
    return dir_to, spd


def aqi_color(v: float) -> str:
    if v < 9: return "#a8e0a8"
    if v < 35: return "#ffe066"
    if v < 55: return "#ffa64d"
    if v < 125: return "#e84f3f"
    if v < 225: return "#a04ba0"
    return "#7d1f1f"


def aqi_label(v: float) -> str:
    if v < 9: return "Good"
    if v < 35: return "Moderate"
    if v < 55: return "Unhealthy for sensitive groups"
    if v < 125: return "Unhealthy"
    if v < 225: return "Very Unhealthy"
    return "Hazardous"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", default="2026-03-10",
                    help="Fire date YYYY-MM-DD (must be in data/fire_events.csv)")
    ap.add_argument("--start",
                    help="Override ignition time, YYYY-MM-DDTHH:MM local ET")
    ap.add_argument("--run-hours", type=int, default=DEFAULT_RUN_HOURS,
                    help="Window length (must match the run_hysplit.py run)")
    ap.add_argument("--corrected", action="store_true",
                    help="Use EPA Barkjohn-corrected PurpleAir data")
    args = ap.parse_args()
    suffix = "_corrected" if args.corrected else ""

    fire = args.fire
    window_start, window_end = fire_window_utc(fire, args.run_hours, args.start)
    noaa_csv = PROJECT_ROOT / "data" / "raw" / "noaa" / f"fire_{fire}.csv"
    footprint_geo = PROJECT_ROOT / "data" / "processed" / f"hysplit_footprint_contours_{fire}.geojson"
    footprint_cells = PROJECT_ROOT / "data" / "processed" / f"hysplit_footprint_cells_{fire}.geojson"
    regulatory_parquet = PROJECT_ROOT / "data" / "raw" / "regulatory" / f"fire_{fire}_airnow.parquet"

    pa = max_pa_per_sensor(window_start, window_end, pa_dir(args.corrected), fire)
    print(f"Sensors with PA data in window: {len(pa)} ({'corrected' if args.corrected else 'raw'})")
    print(pa[["name", "miles_from_emr", "max_pm25", "peak_time_local"]].head(10).to_string(index=False))

    fmap = folium.Map(location=[EMR_LAT, EMR_LON], zoom_start=12,
                      tiles="cartodbpositron", control_scale=True)

    # --- Distance rings ---
    for r_mi in (1.0, 2.0, 5.0):
        folium.Circle([EMR_LAT, EMR_LON], radius=r_mi * 1609.344,
                      color="#c60101", weight=0.8, opacity=0.45,
                      fill=False, dash_array="4 4", interactive=False).add_to(fmap)

    # --- Cumulative footprint contour polygons ---
    if footprint_geo.exists():
        contours = json.loads(footprint_geo.read_text())
        band_styles = {
            "outer_1pct":    {"fill": "#cccccc", "opacity": 0.35, "label": "outer extent (≥1% of peak)"},
            "core_10pct":    {"fill": "#888888", "opacity": 0.55, "label": "plume core (≥10% of peak)"},
            "hotspot_50pct": {"fill": "#333333", "opacity": 0.75, "label": "highest band (≥50% of peak)"},
        }
        fg = folium.FeatureGroup(name="Modeled tracer footprint (cumulative)", show=True)
        for label in ["outer_1pct", "core_10pct", "hotspot_50pct"]:
            for f in contours["features"]:
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
                    tooltip=f"Modeled footprint: {s['label']}",
                ).add_to(fg)
        fg.add_to(fmap)

    # --- Optional cell view ---
    if footprint_cells.exists():
        cells = json.loads(footprint_cells.read_text())
        fg_cells = folium.FeatureGroup(name="Footprint — raw 500 m cells (≥1% of peak)", show=False)
        for f in cells["features"]:
            frac = f["properties"].get("fraction_of_peak", 0.0)
            t = max(0.0, min(1.0, (np.log10(max(frac, 1e-4)) + 4) / 4))
            shade = int(220 - 180 * t)
            color = f"#{shade:02x}{shade:02x}{shade:02x}"
            folium.GeoJson(
                f,
                style_function=lambda x, c=color: {
                    "fillColor": c, "color": "#444", "weight": 0.2,
                    "fillOpacity": 0.55,
                },
                tooltip=f"Max relative tracer: {f['properties']['max_tracer_relative']:.2e}",
            ).add_to(fg_cells)
        fg_cells.add_to(fmap)

    # --- EMR marker (drawn after polygons so it sits on top) ---
    folium.Marker(
        [EMR_LAT, EMR_LON],
        icon=folium.Icon(color="red", icon="fire", prefix="fa"),
        tooltip=EMR_NAME,
        popup=folium.Popup(f"<b>{EMR_NAME}</b><br>Subject of investigation", max_width=320),
        z_index_offset=1000,
    ).add_to(fmap)

    # --- Average wind arrow ---
    wind = avg_wind_during_window(noaa_csv, window_start, window_end)
    if wind is not None:
        dir_to, spd = wind
        phl_lat, phl_lon = 39.8744, -75.2424
        length_km = max(2.0, spd * 0.6)
        dy = length_km / 111.0 * np.cos(np.radians(dir_to))
        dx = length_km / (111.0 * np.cos(np.radians(phl_lat))) * np.sin(np.radians(dir_to))
        end_lat, end_lon = phl_lat + dy, phl_lon + dx
        folium.PolyLine(
            [(phl_lat, phl_lon), (end_lat, end_lon)],
            color="#1a5f9c", weight=4, opacity=0.85,
            tooltip=f"Avg PHL wind during fire: blowing TO {dir_to:.0f}° at {spd:.1f} kt mean",
        ).add_to(fmap)
        folium.CircleMarker(
            [phl_lat, phl_lon], radius=4, color="#1a5f9c", weight=1.5,
            fill=True, fill_color="#1a5f9c", fill_opacity=0.6,
            tooltip="PHL ASOS station",
        ).add_to(fmap)

    # --- PA sensor markers — MAX value over window ---
    pa_max_val = pa["max_pm25"].max() if not pa.empty else 1
    fg_pa = folium.FeatureGroup(name="PurpleAir — max PM2.5 during fire window", show=True)
    for _, r in pa.iterrows():
        v = r["max_pm25"]
        c = aqi_color(v)
        radius = 6 + 22 * min(v / max(pa_max_val, 1), 1.0) ** 0.5
        popup = (
            f"<b>{r['name']}</b><br>"
            f"<b>{v:.1f} µg/m³</b> &nbsp; <i>(max during fire window)</i><br>"
            f"AQI band: <b>{aqi_label(v)}</b><br>"
            f"Peak observed at: {r['peak_time_local']}<br>"
            f"{r['miles_from_emr']:.2f} mi from EMR"
        )
        folium.CircleMarker(
            [r["lat"], r["lon"]],
            radius=radius,
            color="white", weight=1.2, opacity=0.95,
            fill=True, fill_color=c, fill_opacity=0.88,
            tooltip=f"{r['name']}: max {v:.1f} µg/m³ ({aqi_label(v)})",
            popup=folium.Popup(popup, max_width=320),
        ).add_to(fg_pa)
    fg_pa.add_to(fmap)

    # --- Regulatory / AirNow markers (FRM/FEM gold standard) ---
    reg = max_regulatory_per_site(window_start, window_end, regulatory_parquet)
    if not reg.empty:
        print()
        print(f"Regulatory sites with data in window: {len(reg)}")
        print(reg[["name", "provider", "miles_from_emr", "max_pm25", "peak_time_local"]]
              .to_string(index=False))
        fg_reg = folium.FeatureGroup(name="Regulatory (AirNow / EPA FRM, hourly max)",
                                     show=True)
        for _, r in reg.iterrows():
            v = float(r["max_pm25"])
            c = aqi_color(v)
            # Use a square divIcon to visually distinguish from PurpleAir circles.
            size = int(round(14 + 22 * min(v / max(reg['max_pm25'].max(), 1), 1.0) ** 0.5))
            html_icon = (
                f"<div style='width:{size}px;height:{size}px;background:{c};"
                f"border:2px solid white;box-shadow:0 0 0 1.5px #333;"
                f"transform:rotate(45deg);'></div>"
            )
            popup = (
                f"<b>{r['name']}</b> ({r['provider']})<br>"
                f"<b>{v:.1f} µg/m³</b> &nbsp;<i>(hourly max during fire window)</i><br>"
                f"AQI band: <b>{aqi_label(v)}</b><br>"
                f"Peak observed at: {r['peak_time_local']}<br>"
                f"{r['miles_from_emr']:.2f} mi from EMR &nbsp; · &nbsp; EPA-grade FRM/FEM"
            )
            folium.Marker(
                [r["lat"], r["lon"]],
                icon=folium.DivIcon(html=html_icon,
                                    icon_size=(size + 6, size + 6),
                                    icon_anchor=((size + 6) // 2, (size + 6) // 2)),
                tooltip=f"{r['name']} (regulatory): max {v:.1f} µg/m³ ({aqi_label(v)})",
                popup=folium.Popup(popup, max_width=320),
            ).add_to(fg_reg)
        fg_reg.add_to(fmap)

    folium.LayerControl(collapsed=False, position="topright").add_to(fmap)

    # --- Header / title ---
    win_local_start = window_start.astimezone(__import__("zoneinfo").ZoneInfo(LOCAL_TZ))
    win_local_end = window_end.astimezone(__import__("zoneinfo").ZoneInfo(LOCAL_TZ))
    title_html = (
        "<div style='position: fixed; top: 12px; left: 50%; transform: translateX(-50%); "
        "z-index: 9999; background: white; padding: 8px 18px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        f"<b>EMR Camden fire, {fire}</b> &middot; exposure summary &middot; "
        f"{win_local_start.strftime('%b %-d %-I:%M %p')} &ndash; "
        f"{win_local_end.strftime('%-I:%M %p %Z')}"
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(title_html))

    # --- Legend ---
    legend_html = (
        "<div style='position: fixed; top: 72px; right: 18px; z-index: 9999; "
        "background: white; padding: 10px 14px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; font-size: 11px; "
        "max-width: 290px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        f"<b>PurpleAir circles</b>: max PM2.5 ({'EPA Barkjohn-corrected' if args.corrected else 'uncorrected ATM channel'}, ~3 m above ground, 10-min samples).<br>"
        "<b>Regulatory diamonds (AirNow ◆)</b>: max hourly PM2.5 from EPA-grade FRM/FEM monitors.<br>"
        "<span style='color:#a8e0a8'>●</span> Good (0–9 µg/m³) &nbsp;"
        "<span style='color:#ffe066'>●</span> Moderate (9–35)<br>"
        "<span style='color:#ffa64d'>●</span> USG (35–55) &nbsp;"
        "<span style='color:#e84f3f'>●</span> Unhealthy (55–125)<br>"
        "<span style='color:#a04ba0'>●</span> Very Unhealthy (125–225) &nbsp;"
        "<span style='color:#7d1f1f'>●</span> Hazardous (225+)<br>"
        "Marker size scales with maximum value.<br>"
        "<hr style='margin:6px 0;border:0;border-top:1px solid #ccc'>"
        "<b>Modeled tracer footprint</b> (gray bands): cumulative envelope of the "
        "HYSPLIT dispersion run over the same window. From light to dark: "
        "≥1% / ≥10% / ≥50% of the simulation's peak modeled relative concentration. "
        "1% and 10% are NOAA's HYSPLIT ensemble-display convention.<br>"
        "<hr style='margin:6px 0;border:0;border-top:1px solid #ccc'>"
        "<i style='color:#666'>Blue arrow = vector-averaged PHL ASOS wind during the "
        "fire, drawn from the station in the direction the wind blew.</i>"
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(legend_html))

    # --- Caveat / methodology ---
    pa_method = ("EPA Barkjohn-corrected (Barkjohn et&nbsp;al., AMT&nbsp;2021)"
                 if args.corrected else "uncorrected ATM channel")
    # Fire-specific prose — only defensible for the fire it was written about.
    south_camden_note = (
        "Compare the two: regulatory monitors confirm the plume direction "
        "(closest downwind site, NJDEP's South Camden monitor at 0.4 mi ESE, rose "
        "to ~33 µg/m³ during the burn). "
    )
    caveat_html = (
        "<div style='position: fixed; top: 72px; left: 18px; z-index: 9999; "
        "background: white; padding: 10px 14px; border: 1px solid #888; "
        "border-radius: 4px; font-family: sans-serif; font-size: 11px; "
        "max-width: 330px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>"
        "<b>How to read this map</b><br>"
        f"Two sensor networks shown together. <b>Circles = PurpleAir</b> (low-cost "
        f"optical, ~3 m above ground, 10-min samples, {pa_method}). <b>Diamonds = "
        f"regulatory AirNow / EPA FRM monitors</b> (gold-standard hourly aggregated). "
        f"Both show each site's <b>maximum value during the fire window</b>; color "
        f"follows EPA's 2024 PM2.5 AQI band, size scales with magnitude.<br><br>"
        + (south_camden_note if fire == "2026-03-10" else "")
        + ("Corrected PurpleAir peaks now align much closer to regulatory "
           "values; the residual gap reflects PurpleAir's 10-min cadence catching "
           "sub-hour spikes that hourly regulatory averages smooth.<br><br>"
           if args.corrected else
           "Regulatory hourly-averaged peaks run lower than PurpleAir's "
           "10-min peaks. Two reasons: PurpleAir's raw ATM channel is known to "
           "overstate PM2.5 in heavy smoke (EPA's Barkjohn correction typically pulls "
           "extreme readings down 30&ndash;50%), and hourly averaging smooths the "
           "sub-hour spikes PurpleAir catches.<br><br>")
        +
        "Gray bands are the <b>modeled smoke tracer footprint</b> &mdash; locations "
        "where a unit-source NOAA HYSPLIT run (HRRR 3-km met, 30-min averaged column "
        "concentration 0&ndash;100 m AGL, union of 10/30/100/200 m release heights) "
        "predicted modeled tracer mass at any point in the window. The bands are "
        "<b>relative</b>, not measured or estimated µg/m³, and the model carries no "
        "calibration to a specific fire emission rate. Only the shape and direction "
        "of the modeled plume are meaningful; the cumulative footprint shows "
        "<b>where, not when</b>.<br><br>"
        "<b>Mass remains airborne</b> in the simulation (no dry or wet deposition). "
        "Sensor peaks and modeled footprint cores do not always overlap because the "
        "model averages a 0&ndash;100 m air column over 500&nbsp;m cells, while sensors "
        "sample 10-minute PM at ~3&nbsp;m above ground in light, shifting winds."
        "</div>"
    )
    fmap.get_root().html.add_child(folium.Element(caveat_html))

    out = PROJECT_ROOT / "figures" / f"hysplit_still_{fire}{suffix}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out))
    print(f"\nWrote {out.relative_to(PROJECT_ROOT)} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
