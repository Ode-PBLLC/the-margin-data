# Camden — EMR Metal Recycling fires

Data and analysis supporting The Margin's investigation of the EMR Eastern
scrap-metal facility in Camden, NJ: recurring fires, the smoke they put over
the surrounding environmental-justice community, and who lives in the path.
Facility (shredder, 1400 S. Front St): **39.9264 N, 75.1286 W**.

This directory is self-contained and reproducible — every artifact is rebuilt
from inputs committed here by the scripts in `scripts/`, with one documented
exception (the HYSPLIT smoke modeling — see *Reproduction boundary* below).

## Layout

```
camden/
├── scripts/        analysis + build scripts (run from this directory)
├── bundle/         the reviewed visualization bundle (2026-06-02) — upstream
│                   source the build scripts read; HTML maps + PNG charts
├── data/
│   ├── raw/        committed inputs: landmark + fire-date CSVs, air_quality.xlsx,
│   │               EPA AQS zips (aqs/), AirNow files (airnow_20260529/)
│   └── processed/  CSVs the scripts derive from raw (regenerable)
├── handoff/        the dev-team deliverable: stylized GeoJSONs + reference
│                   renders + per-folder READMEs (rebuild from data, don't embed)
└── output/         pipeline products (HYSPLIT geojsons/HTML/PNG) + pm25_graphs/
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Reproduce everything

Run from `camden/`. Each script prints what it writes; order matters where one
feeds another.

```bash
# 1. derive processed CSVs from the committed raw inputs
python scripts/extract_aqs_camden.py        # EPA AQS zips  → data/processed/*aqs*.csv
python scripts/extract_fire_timeseries.py   # bundle anims  → data/processed/fire_*_10min.csv

# 2. build the dev handoff (GeoJSONs + references) from bundle + data
python scripts/build_landmarks.py           # landmarks CSV → handoff/02/landmarks_sophia.geojson
python scripts/build_handoff.py             # bundle maps   → handoff/01,02,03 GeoJSONs + refs
python scripts/build_receptors_reference.py # handoff data  → handoff/02/reference.html

# 3. analysis graphs (PM2.5 over time, wind). Needs network for live PHL wind.
python scripts/build_pm25_graphs.py         # → output/pm25_graphs/*.png
```

`build_landmarks.py` geocodes street addresses live (US Census geocoder, with
an OpenStreetMap/Nominatim fallback) — needs network. `build_pm25_graphs.py`
fetches PHL ASOS wind live from the Iowa Environmental Mesonet. Everything else
runs offline from committed inputs. No API keys are required anywhere.

## The HYSPLIT scripts

`scripts/hysplit_*.py` turn raw NOAA HYSPLIT output (a `.kmz` smoke file or a
trajectory shapefile zip) into the maps in `output/`. They each take that raw
file as a command-line argument:

```bash
python scripts/hysplit_trajectory_to_geojson.py path/to/trajectory.zip
python scripts/hysplit_viz_static.py            path/to/trajectory.zip
```

## Reproduction boundary — HYSPLIT smoke modeling

Two distinct HYSPLIT efforts exist; neither regenerates from a committed raw
input, so this is the one place "run everything" stops short:

1. **`output/hysplit_*` (2025-02-21 fire, GDAS 1-deg, trajectory model)** was
   produced on 2026-03-17 by submitting a job to NOAA's **READY web service**
   (https://www.ready.noaa.gov/), downloading the `.kmz`/trajectory zip, and
   running the `hysplit_*.py` scripts on it. READY is a manual web submission,
   not a keyless API, and the raw download was not retained. To regenerate:
   re-submit on READY (source 39.9264, -75.1286; date 2025-02-21; GDAS 1-deg),
   download the result, then run the scripts above on it.

2. **The bundle's plume maps (`bundle/01b`, `02b` — 2026-03-10 fire)** are a
   newer, different run: HYSPLIT v5.4.2 / HRRR 3-km / unit-source tracer,
   produced in the separate claude.ai investigation pipeline (not with the
   `hysplit_*.py` scripts here). Regenerating these requires that pipeline.

Everything downstream of both — extracting the plume GeoJSONs, styling them,
and all the sensor/monitor charts — reproduces from what's committed here.

A modeling caveat worth carrying into any caption: these are unit-source /
trajectory runs. They show where smoke went given the weather, **not how much**
smoke there was (emission rate / mass burned is not a model input), so the
"% of peak" footprint of a small fire and a large one can look alike. Cross-fire
comparison should lean on measured PM at the monitors + wind direction, not on
footprint size.

## Privacy

`data/raw/camden_landmarks.csv` is a reporter-provided draft. One row — a
resident source's home — has had its **exact street address redacted** to a
~block-level coordinate before being committed here, per the reporter's
instruction to mask it pending source sign-off. The masked location flows
through `build_landmarks.py` into `handoff/.../landmarks_sophia.geojson`
(rounded ~100 m, address dropped, carrying a `location_treatment` note). Do not
re-sharpen it or publish a precise pin without the reporter's and sources' OK.

## Sources

- **PurpleAir** — 10-min `pm2.5_atm`, via the camden pipeline; EPA Barkjohn
  correction (Barkjohn et al. 2021, Atmos. Meas. Tech.) on publication figures.
- **EPA AQS** — pregenerated daily/hourly PM2.5 (param 88101); Camden sites
  34-007-0010 (South Camden, online 2024-08-07), 34-007-0002 (Camden Spruce St,
  last reported 2024-06-18), 34-007-1007 (Pennsauken).
- **EPA AirNow** — public hourly data files (files.airnowtech.org).
- **NOAA HYSPLIT** via READY (GDAS) / HRRR; Stein et al. 2015.
- **PHL ASOS** wind via Iowa Environmental Mesonet.
- **EPA EJScreen** 2024 v2.32 (Public Environmental Data Partners mirror,
  Harvard Dataverse).
- **NCES** schools; **CMS** hospitals/nursing homes; **OpenStreetMap** (© OSM
  contributors) for other receptor context.
- Fire dates and neighborhood landmarks: reporter-provided CSVs in `data/raw/`.

Per-file provenance lives in the `x_sources` field of each GeoJSON and the
`.meta.json` sidecars.
