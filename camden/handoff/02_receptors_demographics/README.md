# 02 — Landmarks + EJScreen Demographics

Who lives near EMR. The map is the EJScreen demographic choropleths plus the reporter's curated landmarks list (19 locations: EMR sites, major air permittees, sensitive receptors, neighborhood assets, narrative locations). Per the 2026-06-05 editorial decision this replaces the earlier bulk OSM receptor layers.

| File | Purpose |
|------|---------|
| `landmarks_sophia.geojson` | **The locations to map.** Reporter-curated, geocoded, categorized, styled |
| `ejscreen_demographics.geojson` | 798 block groups, EJScreen 2024 indicators + the four choropleth fills baked in as `fill_*` columns |
| `receptors_*.geojson` | NCES schools / CMS hospitals / CMS nursing homes — kept as supporting context layers |
| `emr_site.geojson` | EMR point + 0.5/1/2/5-mi rings |
| `reference.html` | Rendering of exactly this folder's data: landmarks on by default, four choropleths + NCES/CMS context layers toggleable. Built by `scripts/build_receptors_reference.py` |

## ⚠️ Privacy

The "Felicia Biles & Christina Allen's home" feature is **generalized to ~100 m** and carries a `location_treatment` note. Do not sharpen it, do not publish a pin without sign-off from the reporter and the sources.

## Context

- Landmark categories and styling: EMR (red), Industrial polluter (dark purple), Sensitive receptor (blue), Neighborhood asset (green), Resident home (gray, masked). The reporter's raw `Type` is preserved in `type_raw`; `significance` is her text — treat it as sourced to her reporting.
- Three landmarks were geocoded via Nominatim fallback (flagged in `geocode_source`) — verify those before publication. Two carry her "Roughly" qualifier (`approximate: true`).
- Demographic values are fractions 0–1 (`LOWINCPCT`, `PEOPCOLORPCT`, `UNDER5PCT`, `OVER64PCT`); `*_display` columns are pre-formatted strings. To render a choropleth, use the matching `fill_*` column as the fill (outline: `#666`, weight 0.4, fillOpacity 0.65).

## Sources

Reporter-provided landmarks CSV (2026-06-05, DRAFT) · US Census Bureau geocoder (Nominatim/OSM fallback where flagged) · EPA EJScreen 2024 v2.32 via the Public Environmental Data Partners mirror on Harvard Dataverse (EPA removed EJScreen from its website 2025-02-05) · NCES school directories · CMS provider directories.
