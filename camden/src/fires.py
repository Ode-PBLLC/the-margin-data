"""Fire-event helpers shared by the HYSPLIT run + visualization scripts.

Single place that answers: "for fire X, when did it start (UTC), what
simulation window do we use, which HRRR met chunks cover it, and where do
its HYSPLIT outputs live?"
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import FIRE_EVENTS_CSV, LOCAL_TZ, PROJECT_ROOT

HYS_TOOLS_DIR = PROJECT_ROOT / "tools" / "hysplit"
HYS_MET_DIR = HYS_TOOLS_DIR / "met"
HYS_WORK_DIR = HYS_TOOLS_DIR / "working"
HYS_OUT_DIR = HYS_TOOLS_DIR / "output"

# NOAA ARL archive of HRRR in HYSPLIT (ARL) format. Files are 6-hour chunks
# named like `20260310_18-23_hrrr` (~3.4 GB each).
ARL_HRRR_BASE_URL = "https://www.ready.noaa.gov/data/archives/hrrr"

DEFAULT_RUN_HOURS = 6


def ignition_utc(fire_date: str, start_override: str | None = None) -> datetime:
    """UTC ignition time for a fire.

    `fire_date` is YYYY-MM-DD and must exist in data/fire_events.csv.
    `start_override` (YYYY-MM-DDTHH:MM, local ET) wins over the CSV — used for
    fires whose ignition_local is not yet known (e.g. 2026-05-29).
    """
    if start_override:
        local = datetime.fromisoformat(start_override)
    else:
        events = pd.read_csv(FIRE_EVENTS_CSV)
        row = events[events["date"] == fire_date]
        if row.empty:
            known = ", ".join(events["date"].tolist())
            raise SystemExit(f"Fire {fire_date} not in {FIRE_EVENTS_CSV}.\nKnown fires: {known}")
        ig = row.iloc[0]["ignition_local"]
        if pd.isna(ig) or not str(ig).strip():
            raise SystemExit(
                f"Fire {fire_date} has no ignition_local in {FIRE_EVENTS_CSV}.\n"
                "Add it there or pass --start YYYY-MM-DDTHH:MM (local ET)."
            )
        local = datetime.fromisoformat(str(ig))
    tz = ZoneInfo(LOCAL_TZ)
    local = local.replace(tzinfo=tz)
    # Reject DST-transition wall times that are ambiguous (fall-back, occurs
    # twice) or nonexistent (spring-forward gap) rather than silently picking
    # one. None of the known fires fall here, but a bad ignition_local should
    # fail loudly, not resolve to the wrong UTC hour.
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise SystemExit(
            f"Ignition time {local:%Y-%m-%d %H:%M} is ambiguous or nonexistent "
            f"in {LOCAL_TZ} (DST transition). Specify an unambiguous time."
        )
    return local.astimezone(timezone.utc)


def fire_window_utc(fire_date: str, run_hours: int = DEFAULT_RUN_HOURS,
                    start_override: str | None = None) -> tuple[datetime, datetime]:
    """(start, end) of the simulation window in UTC."""
    start = ignition_utc(fire_date, start_override)
    return start, start + timedelta(hours=run_hours)


def met_chunk_names(start_utc: datetime, run_hours: int) -> list[str]:
    """HRRR ARL 6-hour chunk filenames covering [start, start + run_hours].

    Chunks cover UTC hours 00-05 / 06-11 / 12-17 / 18-23 of each day.
    """
    names: list[str] = []
    t = start_utc.replace(minute=0, second=0, microsecond=0)
    end = start_utc + timedelta(hours=run_hours)
    while t <= end:
        h0 = (t.hour // 6) * 6
        name = f"{t:%Y%m%d}_{h0:02d}-{h0 + 5:02d}_hrrr"
        if name not in names:
            names.append(name)
        t += timedelta(hours=6)
    # The stepping above can skip the chunk containing `end` when start is not
    # on a chunk boundary — add it explicitly.
    h0 = (end.hour // 6) * 6
    last = f"{end:%Y%m%d}_{h0:02d}-{h0 + 5:02d}_hrrr"
    if last not in names:
        names.append(last)
    return names


def hysplit_fire_out_dir(fire_date: str) -> Path:
    return HYS_OUT_DIR / f"fire_{fire_date}"
