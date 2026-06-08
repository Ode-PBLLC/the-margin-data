"""
Build the analysis graphs for the reporter's 2026-06-05 requests.
===========================================================
Outputs (PNG + .meta.json) land in output/pm25_graphs/.

  1. fire_2025-02-21_noon_to_noon_10min.png
     Her ask: all monitors, sub-hourly, 12pm 2/21 -> 12pm 2/22, vs the EPA
     mobile monitoring window (~3-5am 2/22).
     Data: PurpleAir 10-min RAW ATM (extracted from the bundle animation by
     extract_fire_timeseries.py) + South Camden regulatory BAM hourly (AQS).

  2-4. South Camden / Camden County PM2.5 context at 1 month, 6 months,
     12 months — how the fire spikes compare to "normal" levels.
     Data: EPA AQS pregenerated files (34-007-0010 South Camden,
     34-007-0002 Camden Spruce St, 34-007-1007 Pennsauken).

  5. fire_2026-05-29_morning_monitors_wind.png
     Her ask: conditions at 6:30am 5/29/26. Regulatory PM2.5 (AirNow public
     files) + PHL wind (IEM ASOS). HYSPLIT plume run still pipeline-bound.

    python camden/scripts/build_pm25_graphs.py
"""

import io
import json
import math
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PROCESSED = REPO / "data" / "processed"
AIRNOW_DIR = REPO / "data" / "raw" / "airnow_20260529"
OUT = REPO / "output" / "pm25_graphs"

# ── Brand (The Margin) ────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
SUBHEADING = "#373737"
BACKGROUND = "#EFEEED"

# AQI bands — EPA 2024 PM2.5 breakpoints (same as scripts/plot_air_quality.py)
AQI_BANDS = [
    {"label": "Good", "lo": 0.0, "hi": 9.0, "color": "#4CAF50", "alpha": 0.10},
    {"label": "Moderate", "lo": 9.0, "hi": 35.4, "color": "#FFC107", "alpha": 0.10},
    {"label": "USG", "lo": 35.4, "hi": 55.4, "color": "#FF9800", "alpha": 0.12},
    {"label": "Unhealthy", "lo": 55.4, "hi": 125.4, "color": "#F44336", "alpha": 0.10},
    {"label": "Very Unhealthy", "lo": 125.4, "hi": 225.4, "color": "#9C27B0", "alpha": 0.10},
    {"label": "Hazardous", "lo": 225.4, "hi": 10000, "color": "#7E0023", "alpha": 0.08},
]

NAAQS_24H = 35.0  # EPA 24-hr PM2.5 NAAQS (µg/m³)

# Sacred Heart locations (reporter landmarks CSV; church from OSM layer)
SACRED_HEART_SCHOOL = (39.92222, -75.12098)   # 421 Jasper St (Census geocode)


def aqi_background(ax, ymax):
    for b in AQI_BANDS:
        if b["lo"] >= ymax:
            continue
        ax.axhspan(b["lo"], min(b["hi"], ymax), color=b["color"], alpha=b["alpha"], zorder=0)
    ax.axhline(NAAQS_24H, color=BODY_TEXT, ls=":", lw=1, zorder=3)


def style_fig(fig, axes, title, subtitle, footer):
    fig.patch.set_facecolor(BACKGROUND)
    for ax in axes:
        ax.set_facecolor(BACKGROUND)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=BODY_TEXT, labelsize=8.5)
        for s in ax.spines.values():
            s.set_color(BODY_TEXT)
    fig.suptitle(title, x=0.06, ha="left", fontsize=14, fontweight="bold",
                 color=SUBHEADING)
    fig.text(0.06, 0.918, subtitle, fontsize=9, color=BODY_TEXT, va="top")
    fig.text(0.06, 0.012, footer, fontsize=7, color="#8a8a8a", va="bottom")


def save(fig, name, description, sources):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(fig)
    path.with_suffix(".meta.json").write_text(json.dumps(
        {"description": description, "sources": sources,
         "built_by": "camden/scripts/build_pm25_graphs.py"}, indent=1))
    print(f"  {name} ({path.stat().st_size/1024:.0f} KB)")


def haversine_mi(lat1, lon1, lat2, lon2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def south_camden_hourly():
    """South Camden BAM hourly, mean of the two collocated POCs. Local std time."""
    df = pd.read_csv(PROCESSED / "south_camden_aqs_hourly_2025.csv")
    df["dt"] = pd.to_datetime(df["date_local"] + " " + df["time_local"])
    return df.groupby("dt")["pm25_ugm3"].mean()


# ──────────────────────────────────────────────────────────────────────
# 1. 2/21/25 fire — noon to noon, every monitor, sub-hourly
# ──────────────────────────────────────────────────────────────────────
def graph_noon_to_noon():
    print("\n[1] 2/21 noon -> 2/22 noon")
    df = pd.read_csv(PROCESSED / "fire_2025-02-21_pm25_10min.csv")
    df["dt"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    w0, w1 = pd.Timestamp("2025-02-21 12:00"), pd.Timestamp("2025-02-22 12:00")
    df = df[(df["dt"] >= w0) & (df["dt"] <= w1)]

    # highlight the near-EMR ("primary", within 2 mi) sensors; far sensors stay gray context
    peaks = (df[df["in_primary"]].groupby("sensor_name")["pm25_raw_atm"].max()
             .sort_values(ascending=False))
    top = list(peaks.index[:6])

    fig, ax = plt.subplots(figsize=(12, 6.2))
    ymax = 320
    aqi_background(ax, ymax)

    cmap = ["#c60101", "#1a5f9c", "#a04ba0", "#e07b00", "#2c7c4f", "#7a5230"]
    off_scale = []
    for name, g in df.groupby("sensor_name"):
        g = g.sort_values("dt")
        if name in top:
            c = cmap[top.index(name)]
            mi = g["miles_from_emr"].iloc[0]
            ax.plot(g["dt"], g["pm25_raw_atm"], lw=1.4, color=c,
                    label=f"{name} ({mi:.2f} mi)", zorder=5)
            if g["pm25_raw_atm"].max() > ymax:
                off_scale.append((name, g["pm25_raw_atm"].max()))
        else:
            ax.plot(g["dt"], g["pm25_raw_atm"], lw=0.6, color="#999", alpha=0.55, zorder=4)

    sc = south_camden_hourly()
    sc = sc[(sc.index >= w0) & (sc.index <= w1)]
    ax.step(sc.index, sc.values, where="post", color="black", lw=2.0, zorder=6,
            label="South Camden regulatory BAM (hourly)")

    fire_t = pd.Timestamp("2025-02-21 17:00")
    ax.axvline(fire_t, color=MARGIN_RED, lw=1.2, ls="--", zorder=7)
    ax.annotate("fire reported ~5 p.m.", xy=(fire_t, ymax * 0.97), fontsize=8.5,
                color=MARGIN_RED, rotation=90, va="top", ha="right")

    m0, m1 = pd.Timestamp("2025-02-22 03:00"), pd.Timestamp("2025-02-22 05:00")
    ax.axvspan(m0, m1, color="#1a5f9c", alpha=0.14, zorder=1)
    ax.annotate("EPA mobile monitoring\n(~3–5 a.m., per reporter)\nBAM hours: 36 → 24 µg/m³",
                xy=(m0, ymax * 0.97), fontsize=8.5, color="#1a5f9c", va="top", ha="left")

    bam_peak_t = sc.idxmax()
    ax.annotate(f"regulatory BAM hourly mean\npeaked {sc.max():.0f} µg/m³ (10–11 p.m.)",
                xy=(bam_peak_t, min(sc.max(), ymax * 0.93)), xytext=(-130, -30),
                textcoords="offset points", fontsize=8.5, color="black",
                arrowprops=dict(arrowstyle="->", color="black", lw=0.8),
                bbox=dict(fc="white", ec="black", lw=0.6, pad=2.5))

    for i, (name, v) in enumerate(off_scale):
        ax.annotate(f"{name} peak = {v:.0f} µg/m³ (off scale)",
                    xy=(0.99, 0.97 - 0.05 * i), xycoords="axes fraction", ha="right",
                    fontsize=8.5, color=MARGIN_RED,
                    bbox=dict(fc="white", ec=MARGIN_RED, lw=0.8, pad=2.5))

    ax.set_ylim(0, ymax)
    ax.set_xlim(w0, w1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-I %p\n%b %-d"))
    ax.set_ylabel("PM2.5 (µg/m³)", color=BODY_TEXT, fontsize=9)
    ax.legend(loc="upper left", bbox_to_anchor=(0.13, 0.99), fontsize=8, framealpha=0.9)

    style_fig(fig, [ax], "EMR fire 2/21/25 — every monitor, noon to noon",
              "PurpleAir 10-minute (RAW uncorrected ATM channel; for scale, this fire's raw "
              "1,195 µg/m³ peak ≈ 942 corrected) + South Camden regulatory monitor (hourly), "
              "12 p.m. Feb 21 → 12 p.m. Feb 22, 2025.\n"
              "Dotted line = EPA 24-hr NAAQS (35 µg/m³). Background bands = AQI categories. "
              "For copy reference — not publication.",
              "Data: PurpleAir API 10-min pm2.5_atm (via camden pipeline bundle, 2026-06-02) · "
              "EPA AQS hourly 88101, site 34-007-0010 South Camden (BAM-1022, mean of 2 collocated "
              "instruments; times local standard) · fire start ~5 p.m.: reporter CSV (City of Camden/EMR), "
              "consistent with 911 dispatch ~17:10 (EMR complaint PDF p.91) · EPA mobile window: reporter.")
    save(fig, "fire_2025-02-21_noon_to_noon_10min.png",
         "2/21/25 fire: all PurpleAir sensors (10-min, raw ATM) + South Camden regulatory "
         "hourly, noon-to-noon, with fire start and EPA mobile-monitoring window marked.",
         ["PurpleAir API via camden pipeline (raw pm2.5_atm; extract_fire_timeseries.py)",
          "EPA AQS hourly_88101_2025.zip, site 34-007-0010 (South Camden)",
          "Fire start time: reporter CSV 2026-06-05; 911 dispatch ~17:10 per EMR complaint PDF p.91",
          "EPA mobile monitoring window ~3-5am 2/22: per reporter (unverified by us)"])


# ──────────────────────────────────────────────────────────────────────
# 2-4. Context windows: 1 month / 6 months / 12 months
# ──────────────────────────────────────────────────────────────────────
FIRE_DATES = {  # bundle grid panels (PurpleAir-documented) + reporter evacuation CSV
    "2024-07-29": "7/29/24 fire",
    "2025-02-21": "2/21/25 fire",
}


def mark_fires(ax, lo, hi, ymax):
    for d, label in FIRE_DATES.items():
        t = pd.Timestamp(d)
        if lo <= t <= hi:
            ax.axvline(t, color=MARGIN_RED, lw=1.1, ls="--", zorder=6)
            ax.annotate(label, xy=(t, ymax * 0.96), fontsize=8, color=MARGIN_RED,
                        rotation=90, va="top", ha="right")


def graph_context_1month():
    print("\n[2] 1-month context (hourly)")
    sc = south_camden_hourly()
    lo, hi = pd.Timestamp("2025-02-05"), pd.Timestamp("2025-03-07")
    sc = sc[(sc.index >= lo) & (sc.index <= hi)]
    fig, ax = plt.subplots(figsize=(12, 5))
    ymax = max(60, sc.max() * 1.15)
    aqi_background(ax, ymax)
    ax.plot(sc.index, sc.values, lw=0.9, color=SUBHEADING, zorder=5)
    mark_fires(ax, lo, hi, ymax)
    ax.set_ylim(0, ymax)
    ax.set_xlim(lo, hi)
    ax.set_ylabel("PM2.5 (µg/m³)", color=BODY_TEXT, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
    style_fig(fig, [ax], "One month around the 2/21/25 fire — South Camden monitor",
              "Hourly PM2.5 at the South Camden regulatory monitor (NJDEP, at the CCMUA site), "
              "Feb 5 – Mar 7, 2025. Dotted line = EPA 24-hr NAAQS (35 µg/m³).\n"
              "For copy reference — note this fixed monitor sits ~0.4 mi from EMR; nearer "
              "PurpleAir sensors peaked far higher during the fire (see noon-to-noon chart).",
              "Data: EPA AQS hourly 88101, site 34-007-0010 South Camden (mean of 2 collocated "
              "BAM-1022; times local standard) · Fire dates: camden pipeline bundle + reporter CSV.")
    save(fig, "south_camden_pm25_context_1month.png",
         "Hourly South Camden regulatory PM2.5, 1-month window around the 2/21/25 fire.",
         ["EPA AQS hourly_88101_2025.zip, site 34-007-0010"])


def daily_series():
    d24 = pd.read_csv(PROCESSED / "camden_county_aqs_daily_2024.csv")
    d25 = pd.read_csv(PROCESSED / "camden_county_aqs_daily_2025.csv")
    df = pd.concat([d24, d25])
    df["date"] = pd.to_datetime(df["date_local"])
    df["site_num"] = df["site_num"].astype(str).str.zfill(4)
    return df.groupby(["site_num", "date"])["pm25_daily_mean"].mean().reset_index()


def graph_context_long(months, fname, lo, hi):
    print(f"\n[{3 if months == 6 else 4}] {months}-month context (daily means)")
    df = daily_series()
    df = df[(df["date"] >= lo) & (df["date"] <= hi)]
    fig, ax = plt.subplots(figsize=(12, 5))
    ymax = max(45, df["pm25_daily_mean"].max() * 1.2)
    aqi_background(ax, ymax)

    series = [("0010", "South Camden (from Aug 7, 2024)", SUBHEADING, 1.4, 5),
              ("1007", "Pennsauken (county context, ~5 mi NE)", "#9b9b9b", 1.0, 4)]
    if months == 12:
        series.insert(1, ("0002", "Camden Spruce St (closed Jun 18, 2024)", "#2c5f7c", 1.2, 5))
    for site, label, color, lw, z in series:
        g = df[df["site_num"] == site].sort_values("date")
        if len(g):
            ax.plot(g["date"], g["pm25_daily_mean"], lw=lw, color=color, label=label, zorder=z)

    mark_fires(ax, lo, hi, ymax)
    if months == 12:
        gap0, gap1 = pd.Timestamp("2024-06-18"), pd.Timestamp("2024-08-07")
        ax.axvspan(gap0, gap1, color="#888", alpha=0.10, zorder=1)
        ax.annotate("no Camden-city monitor\n(Spruce St → South Camden gap)\n7/29/24 fire falls here",
                    xy=(gap0 + (gap1 - gap0) / 2, ymax * 0.82), fontsize=8, color="#666",
                    ha="center")
    ax.set_ylim(0, ymax)
    ax.set_xlim(lo, hi)
    ax.set_ylabel("PM2.5 daily mean (µg/m³)", color=BODY_TEXT, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    style_fig(fig, [ax],
              f"{months} months of Camden PM2.5 — fire spikes vs. normal levels",
              "Daily mean PM2.5 at Camden-area regulatory monitors. Dotted line = EPA 24-hr "
              "NAAQS (35 µg/m³). Red dashes = documented EMR fires in window.\n"
              "Daily averaging mutes short fire spikes — the 2/21/25 fire peaked at hundreds of "
              "µg/m³ on nearby 10-min sensors but hours later the daily mean settles; "
              "non-EMR regional events (e.g., summer smoke, July 4) also appear. For copy reference.",
              "Data: EPA AQS daily 88101, sites 34-007-0010 (South Camden), "
              + ("34-007-0002 (Camden Spruce St), " if months == 12 else "")
              + "34-007-1007 (Pennsauken) · Fire dates: camden pipeline bundle + reporter CSV.")
    save(fig, fname,
         f"Daily-mean regulatory PM2.5, {months}-month window, EMR fires marked.",
         ["EPA AQS daily_88101_2024.zip + daily_88101_2025.zip, Camden County sites"])


# ──────────────────────────────────────────────────────────────────────
# 5. 5/29/26 morning — regulatory monitors + PHL wind
# ──────────────────────────────────────────────────────────────────────
AIRNOW_SITES = {  # the regulatory sites shown on our exposure maps
    "340070010": ("South Camden (0.4 mi from EMR)", MARGIN_RED, 2.0),
    "421010057": ("FAB — Philadelphia (2.5 mi)", "#1a5f9c", 1.2),
    "421010055": ("RIT — Philadelphia (3.1 mi)", "#7a7a7a", 1.2),
    "421010048": ("NEW — Philadelphia (5.2 mi)", "#b0a06a", 1.2),
}


def graph_may29_morning():
    print("\n[5] 5/29/26 morning monitors + wind")
    rows = []
    for f in sorted(AIRNOW_DIR.glob("HourlyData_*.dat")):
        for line in f.read_text(errors="replace").splitlines():
            p = line.split("|")
            if len(p) >= 8 and p[2] in AIRNOW_SITES and p[5] == "PM2.5":
                # file times are GMT; 5/29/26 is EDT (UTC-4)
                t = pd.Timestamp(f"2026-{p[0][:2]}-{p[0][3:5]} {p[1]}") - pd.Timedelta(hours=4)
                rows.append((t, p[2], float(p[7])))
    pm = pd.DataFrame(rows, columns=["dt", "site", "pm25"])

    url = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?"
           "station=PHL&data=drct,sknt&year1=2026&month1=5&day1=29&year2=2026&"
           "month2=5&day2=30&tz=America%2FNew_York&format=onlycomma&latlon=no&"
           "missing=M&trace=T&report_type=3")
    wind = pd.read_csv(io.StringIO(urllib.request.urlopen(url, timeout=30).read().decode()))
    wind["dt"] = pd.to_datetime(wind["valid"])
    wind = wind[(wind["dt"] >= "2026-05-29 00:00") & (wind["dt"] <= "2026-05-29 13:00")]
    wind = wind[(wind["drct"] != "M") & (wind["sknt"] != "M")]
    wind["drct"] = wind["drct"].astype(float)
    wind["sknt"] = wind["sknt"].astype(float)

    fig, (ax, axw) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                  height_ratios=[2.4, 1], constrained_layout=False)
    fig.subplots_adjust(hspace=0.12, top=0.86, bottom=0.14, left=0.06, right=0.97)

    ymax = max(40, pm["pm25"].max() * 1.3)
    aqi_background(ax, ymax)
    for site, (label, color, lw) in AIRNOW_SITES.items():
        g = pm[pm["site"] == site].sort_values("dt")
        if len(g):
            ax.step(g["dt"], g["pm25"], where="post", lw=lw, color=color, label=label, zorder=5)
    t630 = pd.Timestamp("2026-05-29 06:30")
    for a in (ax, axw):
        a.axvline(t630, color=MARGIN_RED, lw=1.4, ls="--", zorder=7)
    ax.annotate("6:30 a.m.", xy=(t630, ymax * 0.95), fontsize=9, color=MARGIN_RED,
                rotation=90, va="top", ha="right")
    ax.set_ylim(0, ymax)
    ax.set_ylabel("PM2.5 (µg/m³)", color=BODY_TEXT, fontsize=9)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    axw.plot(wind["dt"], wind["drct"], "o-", ms=4, lw=1, color="#1a5f9c", zorder=5)
    for _, r in wind.iterrows():
        axw.annotate(f"{r['sknt']:.0f}kt", xy=(r["dt"], r["drct"]), xytext=(0, 8),
                     textcoords="offset points", fontsize=6.5, color="#1a5f9c", ha="center")
    axw.set_ylim(0, 360)
    axw.set_yticks([0, 90, 180, 270, 360])
    axw.set_yticklabels(["N", "E", "S", "W", "N"])
    axw.set_ylabel("PHL wind FROM", color=BODY_TEXT, fontsize=9)
    axw.xaxis.set_major_formatter(mdates.DateFormatter("%-I %p"))
    axw.set_xlim(pd.Timestamp("2026-05-29 00:00"), pd.Timestamp("2026-05-29 13:00"))

    style_fig(fig, [ax, axw],
              "Morning of the 5/29/26 fire — regulatory monitors + wind",
              "Hourly PM2.5 at the regulatory monitors near EMR (AirNow), midnight – 1 p.m. EDT, "
              "with PHL wind direction below. Wind FROM the NNW/NW all morning → plume heading "
              "SSE/SE, away from the river and toward Waterfront South / Fairview.\n"
              "PurpleAir 10-min detail and the HYSPLIT plume snapshot for 6:30 a.m. still require "
              "the analysis pipeline — this is the keyless-source view. For copy reference.",
              "Data: EPA AirNow hourly data files (files.airnowtech.org, 2026-05-29; site 340070010 "
              "South Camden/NJDEP + Philadelphia AMS sites; times converted GMT→EDT) · "
              "PHL ASOS via Iowa Environmental Mesonet (routine hourly obs).")
    save(fig, "fire_2026-05-29_morning_monitors_wind.png",
         "5/29/26 fire morning: hourly regulatory PM2.5 + PHL wind direction, 6:30am marked.",
         ["EPA AirNow public hourly data files, 2026-05-29 (GMT→EDT)",
          "PHL ASOS (NWS/FAA) via Iowa Environmental Mesonet"])


if __name__ == "__main__":
    graph_noon_to_noon()
    graph_context_1month()
    graph_context_long(6, "south_camden_pm25_context_6months.png",
                       pd.Timestamp("2024-12-01"), pd.Timestamp("2025-05-31"))
    graph_context_long(12, "camden_pm25_context_12months.png",
                       pd.Timestamp("2024-06-01"), pd.Timestamp("2025-05-31"))
    graph_may29_morning()
    print("\nDone.")
