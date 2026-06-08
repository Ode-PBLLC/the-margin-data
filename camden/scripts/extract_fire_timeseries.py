"""
Extract the embedded PurpleAir 10-min time series from the fire animations.
===========================================================================
The bundle's fire animation HTMLs (05-08) inline their data as `const DATA`:
per-sensor 10-minute PM2.5 (raw uncorrected ATM channel) for ±3-4 days
around each fire. This recovers that data as flat CSVs so we can build
custom chart windows without the (claude.ai) pipeline.

Writes data/processed/fire_<date>_pm25_10min.csv (+ .meta.json), long format:
    timestamp, sensor_id, sensor_name, miles_from_emr, in_primary, pm25_raw_atm

    python camden/scripts/extract_fire_timeseries.py
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "bundle"
OUT = REPO / "data" / "processed"

ANIMATIONS = [
    "05_fire_2025-02-21_animated.html",
    "06_fire_2026-03-10_animated.html",
    "07_fire_2022-10-18_animated.html",
    "08_fire_2026-02-26_animated.html",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for fname in ANIMATIONS:
        html = (BUNDLE / fname).read_text()
        data = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1))
        ts = data["timestamps"]
        out = OUT / f"fire_{data['fire']}_pm25_10min.csv"
        n_rows = 0
        with out.open("w") as f:
            f.write("timestamp,sensor_id,sensor_name,miles_from_emr,in_primary,pm25_raw_atm\n")
            for sid, s in data["sensors"].items():
                assert len(s["values"]) == len(ts), (fname, sid)
                name = s["name"].replace('"', "'")
                for t, v in zip(ts, s["values"]):
                    if v is None:
                        continue
                    f.write(f'{t},{sid},"{name}",{s["miles"]},{s["in_primary"]},{v}\n')
                    n_rows += 1
        meta = {
            "description": f"PurpleAir 10-min PM2.5 around the {data['fire']} EMR fire, "
                           f"{len(data['sensors'])} sensors within 5 mi of the facility. "
                           "RAW uncorrected ATM channel — apply EPA Barkjohn correction "
                           "before publication-facing numbers.",
            "window": [ts[0], ts[-1]],
            "sources": [
                "PurpleAir API (pm2.5_atm, 10-min averages) via the camden pipeline",
                f"Extracted from bundle animation {fname} (built 2026-06-02), which "
                "inlines the pipeline data verbatim.",
            ],
            "built_by": "camden/scripts/extract_fire_timeseries.py",
        }
        out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
        print(f"{out.name}: {len(data['sensors'])} sensors, {n_rows} rows")


if __name__ == "__main__":
    main()
