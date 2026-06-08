"""Central project config.

Single source of truth for: facility location, search radius, time windows,
sensor selection, and file paths. Everything else imports from here so we can
re-tune without hunting through scripts.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- Facility -------------------------------------------------------------
# EMR Camden scrap-metal recycling facility, verified lat/lon from project owner.
EMR_LAT = 39.926309013731036
EMR_LON = -75.128629463321810
EMR_NAME = "EMR Eastern (Camden scrap yard)"

# --- Search geometry ------------------------------------------------------
# Two-tier radius. We pull every sensor in SEARCH_RADIUS_MILES so the wider set
# is available for regional context; PRIMARY_RADIUS_MILES marks the inner ring
# whose readings carry the most weight for plume attribution.
PRIMARY_RADIUS_MILES = 2.0
SEARCH_RADIUS_MILES = 5.0

# --- Time windows ---------------------------------------------------------
# Hours before/after each fire date we pull. Fire dates are stored as calendar
# dates (no specific time); we treat 00:00 -> 24:00 local as "the fire day"
# and pad ±N days on either side.
WINDOW_DAYS_BEFORE = 3
WINDOW_DAYS_AFTER = 3

# --- PurpleAir pull settings ---------------------------------------------
# 10-min averages are PurpleAir's finest hourly-grade resolution and keep
# point cost reasonable. Bump down to 0 (raw 2-min) only for case studies.
PA_AVERAGE_MINUTES = 10
PA_FIELDS = ("pm2.5_atm", "pm2.5_cf_1", "humidity", "temperature")

# --- NOAA ASOS -----------------------------------------------------------
# Philadelphia International is the nearest reliable hourly station to Camden.
NOAA_STATION = "PHL"
LOCAL_TZ = "America/New_York"

# --- Paths ----------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
PA_RAW_DIR = RAW_DIR / "purpleair"
PA_CORRECTED_DIR = PROCESSED_DIR / "purpleair_corrected"
NOAA_RAW_DIR = RAW_DIR / "noaa"
FIRE_EVENTS_CSV = DATA_DIR / "fire_events.csv"


def pa_dir(corrected: bool = False):
    """Pick the PurpleAir data root. Corrected parquets share the same schema
    as raw (pm2.5_atm is overwritten with the Barkjohn-corrected value, the
    original survives as pm2.5_atm_raw) so any reader can flip between them
    with no further code changes."""
    return PA_CORRECTED_DIR if corrected else PA_RAW_DIR
