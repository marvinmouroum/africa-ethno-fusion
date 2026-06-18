#!/usr/bin/env python3
"""Render the fused dataset as an interactive Leaflet map (out/map.html).

The CANONICAL layer is the centrepiece: one resolved entity per real-world
ethnic group (out/canonical.parquet), drawn as its representative geometry
(historical/modern territory polygon where one exists, else a society/people
point). Colour encodes corroboration (how many sources agree); a rich popup
shows identity, language, population, key Ethnographic Atlas traits, the merge
confidence and a needs-review badge.

Layers (toggle in the top-right control):
  * Canonical entities — polygons (territories)        [ON by default]
  * Canonical entities — points (society/people)       [ON by default]
  * Murdock ethnic territories (~1900) + EA traits     [off]
  * GeoEPR modern settlement areas                     [off]
  * Ethnographic Atlas societies (raw points)          [off]
  * Joshua Project people groups (today)               [off]

A self-contained name SEARCH box (top-left, no external CDN) locates and zooms
to any canonical entity by preferred name.

Entry point:  python view.py   ->  writes out/map.html
"""
import json

import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import MarkerCluster

from view_canonical import add_canonical_layers, add_search_box

OUT = "out"

# --------------------------------------------------------------------------- #
#  Base map
# --------------------------------------------------------------------------- #
m = folium.Map(
    location=[3, 20],
    zoom_start=4,
    tiles="CartoDB positron",
    control_scale=True,
)

# --------------------------------------------------------------------------- #
#  CENTREPIECE — the canonical (resolved) layer
# --------------------------------------------------------------------------- #
canonical = gpd.read_parquet(f"{OUT}/canonical.parquet")
search_index, n_poly, n_pt = add_canonical_layers(m, canonical)

# --------------------------------------------------------------------------- #
#  Raw source layers (kept, all OFF by default)
# --------------------------------------------------------------------------- #
g = gpd.read_parquet(f"{OUT}/groups.parquet")
traits = pd.read_parquet(f"{OUT}/traits.parquet")

# key Ethnographic Atlas traits, pivoted to one row per society
KEY_VARS = {
    "EA005": "Agriculture",
    "EA030": "Settlement",
    "EA033": "Politics",
    "EA043": "Descent",
    "EA066": "Class",
}
tt = traits[traits.var_id.isin(KEY_VARS)].copy()
tt["lab"] = tt.var_id.map(KEY_VARS)
piv = tt.pivot_table(
    index="ea_society_id", columns="lab", values="value_label", aggfunc="first"
)

# --- Murdock territories + traits ---
mur = g[g.source == "murdock_map"].copy()
mur["geometry"] = mur.geometry.simplify(0.03)
mur = mur.merge(piv, left_on="ea_society_id", right_index=True, how="left")
trait_cols = list(KEY_VARS.values())
show_cols = ["name", "ea_society_id"] + trait_cols
for c in show_cols:
    mur[c] = mur[c].fillna("—").astype(str)
folium.GeoJson(
    mur[show_cols + ["geometry"]],
    name="Murdock territories (~1900) + traits",
    show=False,
    style_function=lambda f: {
        "fillColor": "#3186cc",
        "color": "#13496f",
        "weight": 0.5,
        "fillOpacity": 0.35,
    },
    highlight_function=lambda f: {"weight": 2, "fillOpacity": 0.6},
    tooltip=folium.GeoJsonTooltip(
        fields=show_cols,
        aliases=[
            "Group",
            "EA id",
            "Agriculture",
            "Settlement",
            "Political complexity",
            "Descent",
            "Class",
        ],
        sticky=True,
        max_width=420,
    ),
).add_to(m)

# --- GeoEPR modern settlement areas (latest period per group) ---
ge = g[g.source == "geoepr"].copy()
ge["period_to"] = pd.to_numeric(ge["period_to"], errors="coerce")
ge = ge.sort_values("period_to").groupby("name", as_index=False).tail(1)
ge["geometry"] = ge.geometry.simplify(0.03)
ge["period"] = (
    ge["period_from"].astype("Int64").astype(str)
    + "–"
    + ge["period_to"].astype("Int64").astype(str)
)
folium.GeoJson(
    ge[["name", "settlement_type", "period", "geometry"]],
    name="GeoEPR settlement areas (modern)",
    show=False,
    style_function=lambda f: {
        "fillColor": "#cc5b31",
        "color": "#7a3413",
        "weight": 0.5,
        "fillOpacity": 0.30,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["name", "settlement_type", "period"],
        aliases=["Group", "Settlement", "Period"],
    ),
).add_to(m)

# --- D-PLACE society points with full trait popup ---
fg = folium.FeatureGroup(name="Ethnographic Atlas societies (raw points)", show=False)
cluster = MarkerCluster().add_to(fg)
dp = g[(g.source == "dplace_ea") & g.geometry.notna()]
for _, r in dp.iterrows():
    soc = r["ea_society_id"]
    rows = traits[traits.ea_society_id == soc]
    items = "".join(
        f"<tr><td><b>{v.var_id}</b> {v.var_title}</td><td>{v.value_label}</td></tr>"
        for v in rows.itertuples()
        if pd.notna(v.value_label)
    )
    html = (
        f"<b>{r['name']}</b> ({soc})<br>glottocode: {r['glottocode']}<br>"
        f"<table style='font-size:11px'>{items}</table>"
    )
    folium.CircleMarker(
        [r.geometry.y, r.geometry.x],
        radius=4,
        color="#2b7a2b",
        fill=True,
        fill_opacity=0.8,
        popup=folium.Popup(html, max_width=480),
        tooltip=r["name"],
    ).add_to(cluster)
fg.add_to(m)

# --- Joshua Project contemporary people groups (clustered) ---
jp = g[(g.source == "joshua_project") & g.geometry.notna()]
if not jp.empty:
    fgj = folium.FeatureGroup(name="Joshua Project people groups (today)", show=False)
    cj = MarkerCluster().add_to(fgj)
    for _, r in jp.iterrows():
        pop = f"{r['population']:,.0f}" if pd.notna(r["population"]) else "—"
        html = (
            f"<b>{r['name']}</b><br>country: {r['country_iso3']}<br>"
            f"language (ISO 639-3): {r['iso639_3']}<br>"
            f"population: {pop}<br>religion: {r['primary_religion']}"
        )
        folium.CircleMarker(
            [r.geometry.y, r.geometry.x],
            radius=3,
            color="#7a2b7a",
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(html, max_width=320),
            tooltip=r["name"],
        ).add_to(cj)
    fgj.add_to(m)

# --------------------------------------------------------------------------- #
#  Controls, search, legend, title
# --------------------------------------------------------------------------- #
folium.LayerControl(collapsed=False).add_to(m)

add_search_box(m, search_index)

legend = (
    "<div style='position:fixed;bottom:18px;right:12px;z-index:9999;background:white;"
    "padding:8px 12px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);"
    "font-family:sans-serif;font-size:12px;line-height:1.5'>"
    "<b>Canonical — sources agreeing</b><br>"
    "<span style='color:#9e9ac8'>●</span> 1 (single source)&nbsp; "
    "<span style='color:#6a51a3'>●</span> 2<br>"
    "<span style='color:#fd8d3c'>●</span> 3&nbsp; "
    "<span style='color:#e6550d'>●</span> 4&nbsp; "
    "<span style='color:#a63603'>●</span> 5+<br>"
    "<span style='color:#888'>▱</span> polygon = territory&nbsp; "
    "<span style='color:#888'>●</span> dot = point only<br>"
    "<span style='background:#d7263d;color:#fff;padding:0 4px;border-radius:3px'>"
    "⚑ review</span> = name-based merge"
    "</div>"
)
m.get_root().html.add_child(folium.Element(legend))

title = (
    "<div style='position:fixed;top:10px;left:50%;transform:translateX(-50%);"
    "z-index:9999;background:white;padding:6px 14px;border-radius:6px;"
    "box-shadow:0 1px 4px rgba(0,0,0,.3);font-family:sans-serif;font-size:13px;"
    "text-align:center'>"
    "<b>Africa — fused ethnographic map</b><br>"
    f"<span style='color:#555;font-size:11px'>{len(canonical):,} canonical entities "
    f"({n_poly:,} territories · {n_pt:,} points) — search by name, top-left</span>"
    "</div>"
)
m.get_root().html.add_child(folium.Element(title))

m.save(f"{OUT}/map.html")
print(
    f"wrote {OUT}/map.html  "
    f"({len(canonical):,} canonical: {n_poly:,} polygons + {n_pt:,} points; "
    f"raw layers: {len(mur)} Murdock, {len(ge)} GeoEPR, {len(dp)} EA pts, "
    f"{len(jp)} JP pts)"
)
