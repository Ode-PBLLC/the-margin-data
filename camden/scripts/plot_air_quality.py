"""
Plot South Camden PM2.5 readings on Feb 21, 2025 — the day of an EMR Metal Recycling fire.

Source: air_quality.xlsx — hourly PM2.5 from South Camden monitor
AQI breakpoints: EPA 2024 PM2.5 NAAQS (annual 9.0 μg/m³ primary standard)
Fire time: Caller reported fire started ~17:10 (from 911 dispatch, page 91 of EMR complaint PDF)
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_PATH = os.path.join(PROJECT_DIR, "data", "raw", "air_quality.xlsx")
OUTPUT_PATH = os.path.join(PROJECT_DIR, "output", "south_camden_pm25_feb21_2025.png")

# ── Brand colors (The Margin) ─────────────────────────────────────────────────
MARGIN_RED = "#c60101"
BODY_TEXT = "#474747"
SUBHEADING = "#373737"
BACKGROUND = "#EFEEED"

# ── AQI bands (EPA 2024 breakpoints for PM2.5) ────────────────────────────────
# Source: EPA 2024 revised PM2.5 NAAQS breakpoints
AQI_BANDS = [
    {"label": "Good",                          "lo": 0.0,   "hi": 9.0,   "color": "#4CAF50", "alpha": 0.13},
    {"label": "Moderate",                      "lo": 9.0,   "hi": 35.4,  "color": "#FFC107", "alpha": 0.15},
    {"label": "Unhealthy for\nSensitive Groups", "lo": 35.4,  "hi": 55.4,  "color": "#FF9800", "alpha": 0.18},
    {"label": "Unhealthy",                     "lo": 55.4,  "hi": 125.4, "color": "#F44336", "alpha": 0.15},
    {"label": "Very Unhealthy",                "lo": 125.4, "hi": 140.0, "color": "#9C27B0", "alpha": 0.15},
]

# ── Load data ──────────────────────────────────────────────────────────────────
df = pd.read_excel(DATA_PATH)
hours = list(range(24))
pm25 = df["South Camden (PM2.5 μg/m3)"].values

# Build mask for valid (non-NaN) readings
valid = ~np.isnan(pm25)
hours_valid = [h for h, v in zip(hours, valid) if v]
pm25_valid = pm25[valid]

# ── Figure setup ───────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5.5))
fig.patch.set_facecolor(BACKGROUND)
ax.set_facecolor(BACKGROUND)

# ── Draw AQI bands ─────────────────────────────────────────────────────────────
for band in AQI_BANDS:
    ax.axhspan(band["lo"], band["hi"], color=band["color"], alpha=band["alpha"],
               linewidth=0, zorder=0)
    # Label on right edge
    label_y = (band["lo"] + band["hi"]) / 2
    ax.text(23.6, label_y, band["label"], fontsize=6.5, color=BODY_TEXT,
            va="center", ha="left", fontstyle="italic", alpha=0.7)

# ── Plot PM2.5 line ───────────────────────────────────────────────────────────
ax.plot(hours_valid, pm25_valid, color=MARGIN_RED, linewidth=2.2, zorder=3,
        solid_capstyle="round")
ax.scatter(hours_valid, pm25_valid, color=MARGIN_RED, s=18, zorder=4,
           edgecolors="white", linewidths=0.5)

# ── Fire annotation ───────────────────────────────────────────────────────────
# Source: 911 dispatch — caller stated fire started around 17:10 (EMR complaint PDF, page 91)
fire_hour = 17 + 10 / 60  # 17:10 as decimal hour
ax.axvline(x=fire_hour, color=BODY_TEXT, linestyle="--", linewidth=1.0,
           alpha=0.6, zorder=2)
ax.annotate(
    "Fire reported\n17:10",
    xy=(fire_hour, 95),
    xytext=(fire_hour - 3.5, 115),
    fontsize=8.5,
    color=SUBHEADING,
    fontweight="bold",
    ha="center",
    arrowprops=dict(arrowstyle="-|>", color=BODY_TEXT, lw=1.0),
    zorder=5,
)

# ── Peak annotation ───────────────────────────────────────────────────────────
peak_hour = hours_valid[np.argmax(pm25_valid)]
peak_val = np.max(pm25_valid)
ax.annotate(
    f"{peak_val:.1f} μg/m³",
    xy=(peak_hour, peak_val),
    xytext=(peak_hour + 1.8, peak_val + 5),
    fontsize=9,
    fontweight="bold",
    color=MARGIN_RED,
    ha="left",
    arrowprops=dict(arrowstyle="-|>", color=MARGIN_RED, lw=1.2),
    zorder=5,
)

# ── Axes styling ───────────────────────────────────────────────────────────────
ax.set_xlim(-0.5, 23.5)
ax.set_ylim(0, 140)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h}:00" for h in range(0, 24, 2)], fontsize=8, color=BODY_TEXT)
ax.set_ylabel("PM2.5 (μg/m³)", fontsize=9, color=SUBHEADING, fontweight="bold")
ax.set_xlabel("Hour of Day — February 21, 2025", fontsize=9, color=SUBHEADING)
ax.tick_params(axis="both", colors=BODY_TEXT, labelsize=8)

# Minimal chrome
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_color(BODY_TEXT)
ax.spines["left"].set_linewidth(0.5)
ax.spines["bottom"].set_color(BODY_TEXT)
ax.spines["bottom"].set_linewidth(0.5)
ax.yaxis.set_major_locator(mticker.MultipleLocator(25))
ax.grid(axis="y", color=BODY_TEXT, alpha=0.08, linewidth=0.5)

# ── Title / subtitle ──────────────────────────────────────────────────────────
fig.text(
    0.06, 0.97,
    "Air Quality Spiked After EMR Fire in South Camden",
    fontsize=14, fontweight="bold", color=SUBHEADING,
    ha="left", va="top",
)
fig.text(
    0.06, 0.925,
    "Hourly PM2.5 readings from South Camden monitor, February 21, 2025",
    fontsize=9.5, color=BODY_TEXT,
    ha="left", va="top",
)

# ── Source attribution ─────────────────────────────────────────────────────────
fig.text(
    0.06, 0.02,
    "Data: South Camden air quality monitor  |  AQI bands: EPA 2024 PM2.5 breakpoints  |  Fire time: NJ DEP EMR complaint (911 dispatch)",
    fontsize=6.5, color=BODY_TEXT, alpha=0.6,
    ha="left", va="bottom",
)

# ── Save ───────────────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
fig.subplots_adjust(left=0.08, right=0.82, top=0.88, bottom=0.13)
fig.savefig(OUTPUT_PATH, dpi=200, facecolor=BACKGROUND, bbox_inches="tight")
plt.close(fig)

print(f"Saved: {OUTPUT_PATH}")


def write_metadata():
    """Write metadata for this output."""
    return {
        "output": OUTPUT_PATH,
        "sources": [
            "South Camden air quality monitor — hourly PM2.5 readings (air_quality.xlsx)",
            "EPA 2024 revised PM2.5 NAAQS breakpoints (annual primary standard: 9.0 μg/m³)",
            "NJ DEP EMR complaint PDF (980132083) — 911 dispatch, fire reported ~17:10, page 91",
        ],
        "date_range": "2025-02-21",
        "location": "South Camden, NJ",
    }


if __name__ == "__main__":
    meta = write_metadata()
    print(f"Sources: {meta['sources']}")
