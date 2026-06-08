# 03 — All EMR Fires, PM2.5 Small Multiples

Reference chart (`reference.png`): one panel per fire window, 2022–2026, showing every PurpleAir sensor within 2 mi of EMR at 10-minute resolution, ±3–4 days around each fire. Shared 0–150 µg/m³ y-axis; dotted line = EPA 24-hr NAAQS (35 µg/m³); red shading = fire window.

| File | Purpose |
|------|---------|
| `reference.png` | The rendering to match (EPA Barkjohn-corrected values) |
| `fire_<date>_pm25_10min.csv` | Underlying 10-minute per-sensor data for 4 of the 10 fire windows (see warning below). Long format: timestamp, sensor_id, sensor_name, miles_from_emr, in_primary, pm25_raw_atm |
| `*.meta.json` | Sources per CSV |

## ⚠️ Raw vs corrected — read before rebuilding

The CSVs are the **RAW uncorrected PurpleAir ATM channel**. The reference PNG shows **EPA Barkjohn-corrected** values — corrected runs lower (this set's biggest peak: 1,195 raw ≈ 942 corrected). Do not rebuild from these CSVs and label the result "corrected," and do not mix raw lines onto corrected axes. Publication-grade corrected series need a rerun from the analysis pipeline (the correction requires per-reading humidity, which these extracts don't carry).

## Coverage

- **In this folder (4 windows):** 2022-10-18, 2025-02-21, 2026-02-26, 2026-03-10 — recovered from the bundle's fire-animation files, which inline the pipeline data verbatim (`scripts/extract_fire_timeseries.py`).
- **Pipeline-only (6 windows):** 2022-02-28, 2022-07-21, 2022-07-22, 2024-07-29, 2025-08-12, 2025-10-17 — no local source; request from the pipeline rather than digitizing the image.
- Off-scale peaks annotated on the reference: 2025-02-21 → 942 µg/m³ corrected; 2026-03-10 → 162 µg/m³. "(primary)" in panel titles = sensors within the primary 2-mi radius.

## Sources

PurpleAir API (10-min `pm2.5_atm`) via the camden investigation pipeline; CSVs extracted by `scripts/extract_fire_timeseries.py` from the 2026-06-02 bundle animations · EPA Barkjohn correction (Barkjohn et al. 2021, Atmos. Meas. Tech.) applied in the reference PNG only · fire dates from the EMR incident timeline compiled for this story.
