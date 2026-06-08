# Camden EMR Fires — Dev Team Handoff

Three deliverables for the EMR Eastern (Camden scrap yard) story. Facility location: **39.9263 N, 75.1286 W**. Each folder has the rendered reference plus stylized GeoJSONs — rebuild from the data, don't embed the references.

| # | Deliverable | What it is |
|---|-------------|------------|
| 1 | [HYSPLIT exposure map](./01_hysplit_exposure_map/) | 2026-03-10 fire: modeled smoke footprint + sensor maxima |
| 2 | [Landmarks + demographics](./02_receptors_demographics/) | Who lives near EMR: reporter-curated landmarks + EJScreen choropleths |

## Conventions

- All GeoJSON is WGS84 lon/lat.
- Styling is baked into each feature: polygons and circle markers carry a `style` object (the exact Leaflet options from our reference); icon markers carry an `icon` object (`markerColor`, `icon` = Font Awesome name).
- Distance rings are Point features with `radius_m` / `radius_mi` — re-draw as circles around the point.
- Every file carries its own `x_description` and `x_sources` at the top level.

## Brand

Match themargin.us: background `#EFEEED`, body `#474747`, accent (Margin Red) `#c60101`, blocky uppercase sans display + serif body.

## Sourcing standard

Every value here is traceable to a named source (see `x_sources` in each file).
