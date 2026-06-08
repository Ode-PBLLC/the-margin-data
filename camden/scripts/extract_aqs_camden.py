"""
Extract Camden-County PM2.5 from the EPA AQS pregenerated files.
================================================================
Reads the zipped annual AQS files in data/raw/aqs/ (parameter 88101 = PM2.5)
and writes the flat per-site CSVs that build_pm25_graphs.py consumes:

    data/processed/south_camden_aqs_hourly_2025.csv
    data/processed/camden_county_aqs_daily_2024.csv
    data/processed/camden_county_aqs_daily_2025.csv

Camden-area sites (state 34, county 007):
    34-007-0010  South Camden (at the CCMUA site) — online 2024-08-07
    34-007-0002  Camden Spruce Street            — last reported 2024-06-18
    34-007-1007  Pennsauken (county context)

The raw zips are committed under data/raw/aqs/. To refresh or add a year,
re-download from EPA (no API key needed):
    https://aqs.epa.gov/aqsweb/airdata/hourly_88101_<YEAR>.zip
    https://aqs.epa.gov/aqsweb/airdata/daily_88101_<YEAR>.zip
EPA publishes with a lag; 2026 files are not yet posted as of this writing.

    python scripts/extract_aqs_camden.py
"""

import csv
import io
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AQS = REPO / "data" / "raw" / "aqs"
OUT = REPO / "data" / "processed"

STATE, COUNTY = "34", "007"


def rows_for_county(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        with z.open(z.namelist()[0]) as f:
            for row in csv.DictReader(io.TextIOWrapper(f)):
                if row["State Code"] == STATE and row["County Code"] == COUNTY:
                    yield row


def build_hourly_south_camden():
    out = OUT / "south_camden_aqs_hourly_2025.csv"
    n = 0
    with out.open("w") as f:
        f.write("date_local,time_local,poc,pm25_ugm3,method\n")
        for row in rows_for_county(AQS / "hourly_88101_2025.zip"):
            if row["Site Num"] != "0010":
                continue
            f.write(",".join(x.replace(",", ";") for x in (
                row["Date Local"], row["Time Local"], row["POC"],
                row["Sample Measurement"], row["Method Name"])) + "\n")
            n += 1
    print(f"  {out.name}: {n} hourly rows")


def build_daily(year):
    out = OUT / f"camden_county_aqs_daily_{year}.csv"
    recs = [(r["Site Num"], r["POC"], r["Date Local"], r["Arithmetic Mean"],
             r["Local Site Name"]) for r in rows_for_county(AQS / f"daily_88101_{year}.zip")]
    with out.open("w") as f:
        f.write("site_num,poc,date_local,pm25_daily_mean,site_name\n")
        for t in sorted(recs):
            f.write(",".join(t) + "\n")
    print(f"  {out.name}: {len(recs)} daily rows")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_hourly_south_camden()
    build_daily(2024)
    build_daily(2025)
    print("Done.")
