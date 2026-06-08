# 01 — HYSPLIT Exposure Map (2026-03-10 fire)

Single static map of the March 10, 2026 EMR fire: modeled smoke footprint under the sensors that measured it. PurpleAir values are EPA Barkjohn-corrected (peak: Cooper Plaza, 162.4 µg/m³ — Very Unhealthy).

| File | Purpose |
|------|---------|
| `reference.html` | Our rendering (open in a browser; needs internet for tiles). Match the visual; don't embed. |
| `footprint_cumulative.geojson` | Smoothed footprint, 3 bands: ≥1% / ≥10% / ≥50% of peak (light→dark gray) |
| `footprint_raw_cells.geojson` | The 171 raw 500 m HYSPLIT cells behind the bands (`fraction_of_peak` per cell) |
| `sensors_purpleair.geojson` | 32 PurpleAir sensors: max corrected PM2.5, AQI band, peak time |
| `monitors_regulatory.geojson` | 10 regulatory monitors (yellow diamonds in the reference) |
| `site_context.geojson` | EMR point, 1/2/5-mi rings, PHL ASOS station + mean wind vector |

## Context

- The footprint is a **NOAA HYSPLIT v5.4.2 unit-source tracer simulation** (HRRR 3-km meteorology). It is *relative concentration* — never label it µg/m³.
- The sensors are the measurements; the footprint explains the spatial pattern. Keep the two visually distinct (footprint gray, sensors colored by AQI band) as in the reference.
- Wind during the fire: blowing toward 16° at 4.4 kt mean (PHL ASOS) — consistent with the plume heading north over Cooper Plaza.

## Sources

PurpleAir API (10-min, EPA Barkjohn correction — Barkjohn et al. 2021, Atmos. Meas. Tech.) · EPA AirNow via OpenAQ v3 · NOAA HYSPLIT v5.4.2 / HRRR · PHL ASOS (NWS/FAA).
