"""
Rebuild the receptors-view reference map for the Camden handoff.
================================================================
Per the 2026-06-05 editorial decision: the "who lives near EMR" map is the
EJScreen demographic choropleths + the reporter's curated landmarks. The
bulk OSM receptor layers are gone. NCES schools and CMS hospitals / nursing
homes remain as default-off context layers.

Built entirely from the handoff's own geojsons (run build_handoff.py and
build_landmarks.py first), so the reference always matches the data files.

Writes: handoff/02_receptors_demographics/reference.html

    python camden/scripts/build_receptors_reference.py
"""

import json
from pathlib import Path

import folium

REPO = Path(__file__).resolve().parents[1]
DIR = REPO / "handoff" / "02_receptors_demographics"
OUT = DIR / "reference.html"

# EMR Eastern marker from the bundle maps (see emr_site.geojson)
EMR_LAT, EMR_LON = 39.926309013731036, -75.12862946332181

DEMO_LAYERS = [  # (layer name, baked fill column, display value column)
    ("Demographics: % low income", "fill_low_income", "LOWINCPCT_display"),
    ("Demographics: % people of color", "fill_people_of_color", "PEOPCOLORPCT_display"),
    ("Demographics: % under age 5", "fill_under_age_5", "UNDER5PCT_display"),
    ("Demographics: % age 65+", "fill_age_65_plus", "OVER64PCT_display"),
]

CONTEXT_LAYERS = [  # default-off NCES/CMS receptor layers kept for context
    ("Schools (K-12, NCES)", "receptors_schools_k_12_nces.geojson"),
    ("Hospitals (CMS-certified)", "receptors_hospitals_cms_certified.geojson"),
    ("Nursing homes (CMS)", "receptors_nursing_homes_cms.geojson"),
]

TITLE_HTML = """
<div style="position: fixed; top: 12px; left: 60px; z-index: 9999;
            background: #EFEEED; border: 1px solid #c8c6c4; border-radius: 4px;
            padding: 8px 14px; font-family: Arial, sans-serif; max-width: 460px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15);">
  <div style="font-size: 15px; font-weight: 700; color: #373737;
              text-transform: uppercase; letter-spacing: 0.5px;">
    Who lives near EMR</div>
  <div style="font-size: 12px; color: #474747; margin-top: 2px;">
    Reporter-curated landmarks over EJScreen 2024 demographics (toggle layers
    at right). Landmark colors: <span style="color:#c60101;">&#9679;</span> EMR
    &nbsp;<span style="color:#5b3256;">&#9679;</span> industrial polluter
    &nbsp;<span style="color:#2c5f7c;">&#9679;</span> sensitive receptor
    &nbsp;<span style="color:#5b8c5a;">&#9679;</span> neighborhood asset
    &nbsp;<span style="color:#888888;">&#9679;</span> resident home (generalized)
  </div>
</div>
"""


def load(name):
    return json.loads((DIR / name).read_text())


def main():
    m = folium.Map(location=[EMR_LAT, EMR_LON], zoom_start=15,
                   tiles="cartodbpositron", control_scale=True)

    # -- EJScreen choropleths, fills baked per block group (default off)
    demo = load("ejscreen_demographics.geojson")
    for layer_name, fill_col, display_col in DEMO_LAYERS:
        fg = folium.FeatureGroup(name=layer_name, show=False)
        folium.GeoJson(
            demo,
            style_function=lambda f, col=fill_col: {
                "color": "#666", "weight": 0.4,
                "fillColor": f["properties"][col], "fillOpacity": 0.65},
            tooltip=folium.GeoJsonTooltip(
                fields=["NAMELSAD", "CNTY_NAME", display_col],
                aliases=["", "", layer_name.replace("Demographics: ", "")]),
        ).add_to(fg)
        fg.add_to(m)

    # -- EMR site + distance rings (always on)
    for f in load("emr_site.geojson")["features"]:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        if "radius_m" in p:
            folium.Circle([lat, lon], radius=p["radius_m"], color="#c60101",
                          weight=0.8, opacity=0.45, fill=False, dash_array="4 4",
                          tooltip=p["name"]).add_to(m)
        else:
            folium.Marker([lat, lon], tooltip=p["name"], z_index_offset=1000,
                          icon=folium.Icon(color="red", icon="fire", prefix="fa")
                          ).add_to(m)

    # -- Reporter landmarks (default on)
    fg = folium.FeatureGroup(name="Reporter landmarks", show=True)
    for f in load("landmarks_sophia.geojson")["features"]:
        if f["geometry"] is None:
            continue
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        popup = (f"<b>{p['name']}</b><br><i>{p['category']}</i>"
                 + (f"<br>{p['significance']}" if p.get("significance") else "")
                 + f"<br>{p['distance_mi_from_emr_shredder']} mi from EMR shredder"
                 + (f"<br><b>{p['location_treatment']}</b>"
                    if p.get("location_treatment") else ""))
        folium.Marker(
            [lat, lon], tooltip=p["name"],
            popup=folium.Popup(popup, max_width=320),
            icon=folium.Icon(color=p["icon"]["markerColor"],
                             icon=p["icon"]["icon"], prefix="fa"),
        ).add_to(fg)
    fg.add_to(m)

    # -- NCES/CMS context layers (default off)
    for layer_name, fname in CONTEXT_LAYERS:
        fg = folium.FeatureGroup(name=layer_name, show=False)
        for f in load(fname)["features"]:
            lon, lat = f["geometry"]["coordinates"]
            p = f["properties"]
            popup = (f"<b>{p['name']}</b><br><i>{p.get('category', layer_name)}</i>"
                     + (f"<br>{p['address']}" if p.get("address") else "")
                     + (f"<br>{p['distance_mi_from_emr']} mi from EMR"
                        if p.get("distance_mi_from_emr") is not None else ""))
            folium.Marker(
                [lat, lon], tooltip=p["name"],
                popup=folium.Popup(popup, max_width=320),
                icon=folium.Icon(color=p["icon"]["markerColor"],
                                 icon=p["icon"]["icon"], prefix="fa"),
            ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(TITLE_HTML))
    m.save(str(OUT))
    print(f"{OUT.name}: {OUT.stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
