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
├── src/            shared config/helpers for the unit-source HYSPLIT pipeline
│                   (config.py = coords/paths, fires.py = fire windows + met,
│                   qc.py = stuck-sensor filter)
├── bundle/         the reviewed visualization bundle (2026-06-02) — upstream
│                   source the build scripts read; HTML maps + PNG charts
├── data/
│   ├── raw/        committed inputs: landmark + fire-date CSVs, air_quality.xlsx,
│   │               EPA AQS zips (aqs/), AirNow files (airnow_20260529/),
│   │               sensors_metadata.csv, noaa/ wind, fire_events.csv
│   └── processed/  CSVs the scripts derive from raw (regenerable) +
│                   hysplit_footprint_*.geojson + corrected PurpleAir parquets
├── handoff/        the dev-team deliverable: stylized GeoJSONs + reference
│                   renders + per-folder READMEs (rebuild from data, don't embed)
├── tools/hysplit/  output/fire_2026-03-10/ = committed model grids (the post-run
│                   checkpoint); met/ (HRRR, multi-GB) is gitignored
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

Two distinct HYSPLIT efforts live here, with two distinct script families.

**A. Trajectory / READY scripts — `scripts/hysplit_*.py`** (2025-02-21 fire).
Turn raw NOAA HYSPLIT output (a `.kmz` smoke file or a trajectory shapefile zip)
from a READY web submission into the maps in `output/`. Each takes that raw file
as a command-line argument:

```bash
python scripts/hysplit_trajectory_to_geojson.py path/to/trajectory.zip
python scripts/hysplit_viz_static.py            path/to/trajectory.zip
```

**B. Unit-source dispersion pipeline — `scripts/run_hysplit.py` +
`scripts/build_hysplit_*.py`** (2026-03-10 fire; the `bundle/01b`, `02b` plume
maps). This is the full programmatic pipeline that actually *runs* the model —
it is the "separate pipeline" the earlier handoff referred to, now committed
here. `src/{config,fires,qc}.py` are its only shared dependencies.

```bash
# 1. run the model: writes the CONTROL file, runs hycs_std, con2asc → ASCII grids
#    in tools/hysplit/output/fire_2026-03-10/. Needs a local HYSPLIT install +
#    HRRR met (see boundary below). The grids it produces are committed, so
#    steps 2-3 run from a fresh checkout with no HYSPLIT install.
python scripts/run_hysplit.py            --fire 2026-03-10
# 2. ASCII grids → cumulative-footprint GeoJSONs in data/processed/
python scripts/build_hysplit_footprint.py --fire 2026-03-10
# 3. footprint + corrected PurpleAir + wind → the still/animated plume maps
python scripts/build_hysplit_still.py     --fire 2026-03-10 --corrected
python scripts/build_hysplit_animation.py --fire 2026-03-10 --corrected
```

The model is a unit-source (1,000 g/hr tracer) dispersion across four release
heights (10/30/100/200 m AGL); output is *relative* plume shape only, never
calibrated µg/m³ (see the modeling caveat below).

## Reproduction boundary — HYSPLIT smoke modeling

One step does not regenerate from a committed input — running the dispersion
model itself, which needs software and weather data too large/external to commit:

1. **`output/hysplit_*` (2025-02-21 fire, GDAS 1-deg, trajectory model)** was
   produced on 2026-03-17 by submitting a job to NOAA's **READY web service**
   (https://www.ready.noaa.gov/), downloading the `.kmz`/trajectory zip, and
   running the `hysplit_*.py` scripts on it. READY is a manual web submission,
   not a keyless API, and the raw download was not retained. To regenerate:
   re-submit on READY (source 39.9264, -75.1286; date 2025-02-21; GDAS 1-deg),
   download the result, then run the scripts above on it.

2. **The bundle's plume maps (`bundle/01b`, `02b` — 2026-03-10 fire)** come from
   the family-B pipeline above. The single non-checkout step is
   `run_hysplit.py`, which needs a local **NOAA HYSPLIT v5.4.2** install
   (looks in `/Applications/hysplit`, `~/hysplit`, … or pass `--hysplit-dir`)
   and the **HRRR met** it auto-downloads from the NOAA ARL archive (6-hour
   chunks, ~3.4 GB each — gitignored under `tools/hysplit/met/`). Its output —
   the ASCII concentration grids in `tools/hysplit/output/fire_2026-03-10/` — **is
   committed**, so `build_hysplit_footprint/still/animation.py` regenerate the
   footprint GeoJSONs and both plume maps from a fresh checkout with no HYSPLIT
   install (verified: the regenerated footprint GeoJSONs are byte-identical to
   the committed ones). To redo the model run from scratch: install HYSPLIT,
   then `python scripts/run_hysplit.py --fire 2026-03-10`.

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
