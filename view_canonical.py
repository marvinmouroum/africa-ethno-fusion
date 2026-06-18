#!/usr/bin/env python3
"""Canonical-layer rendering + self-contained name search for view.py.

`add_canonical_layers` draws the resolved entities (one row per real-world
group) as the map centrepiece:

  * Territory polygons (historical/modern) -> a single simplified GeoJson layer,
    coloured by n_sources (corroboration), with a rich popup per feature.
  * Society/people points -> a MarkerCluster of CircleMarkers, same colour ramp.

Each rendered feature is tagged with a stable ``canonical_id`` so the search
box can fly to it. `add_search_box` injects a dependency-free (no CDN) search
widget that indexes every entity by preferred name and zooms to the match.
"""
import json

import folium
import pandas as pd
from folium.plugins import MarkerCluster

# Sequential purple (1–2 sources) -> orange/brown (3+) ramp. More sources that
# independently place a group = warmer, more "trustworthy" colour.
_SOURCE_COLORS = {
    1: "#9e9ac8",
    2: "#6a51a3",
    3: "#fd8d3c",
    4: "#e6550d",
    5: "#a63603",
}


def _color_for(n_sources) -> str:
    try:
        n = int(n_sources)
    except (TypeError, ValueError):
        n = 1
    if n >= 5:
        return _SOURCE_COLORS[5]
    return _SOURCE_COLORS.get(n, _SOURCE_COLORS[1])


def _as_list(raw):
    """sources / alt_names are stored as JSON strings; decode defensively."""
    if isinstance(raw, list):
        return raw
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [str(v)]
    except (TypeError, ValueError):
        s = str(raw).strip()
        return [s] if s and s.lower() != "nan" else []


def _fmt(v, dash="—"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    s = str(v).strip()
    return s if s and s.lower() != "nan" else dash


def _popup_html(r) -> str:
    """Rich popup for one canonical entity."""
    name = _fmt(r.get("preferred_name"), "(unnamed)")
    sources = _as_list(r.get("sources"))
    alt = _as_list(r.get("alt_names"))
    n_src = _fmt(r.get("n_sources"))

    review = ""
    if bool(r.get("needs_review")):
        review = (
            " <span style='background:#d7263d;color:#fff;padding:1px 6px;"
            "border-radius:3px;font-size:10px;vertical-align:middle'>⚑ NEEDS REVIEW</span>"
        )

    pop = r.get("population_total")
    pop_s = f"{pop:,.0f}" if (pop is not None and pd.notna(pop)) else "—"

    conf = r.get("merge_confidence")
    conf_s = f"{conf:.2f}" if (conf is not None and pd.notna(conf)) else "—"

    geom_kind = (
        "territory polygon"
        if r["geometry"].geom_type in ("Polygon", "MultiPolygon")
        else "point only"
    )
    span = []
    if bool(r.get("has_historical")):
        span.append("historical (~1900)")
    if bool(r.get("has_modern")):
        span.append("modern")
    span_s = " + ".join(span) if span else "—"

    area = r.get("area_sqkm")
    area_s = f"{area:,.0f} km²" if (area is not None and pd.notna(area)) else "—"

    rows = [
        ("Sources", f"{', '.join(sources) if sources else '—'} ({n_src})"),
        ("Language family", _fmt(r.get("language_family"))),
        ("Glottocode", _fmt(r.get("glottocode"))),
        ("ISO 639-3", _fmt(r.get("iso639_3"))),
        ("EA society id", _fmt(r.get("ea_society_id"))),
        ("Population", pop_s),
        ("Primary religion", _fmt(r.get("primary_religion"))),
        ("Subsistence", _fmt(r.get("trait_subsistence"))),
        ("Settlement", _fmt(r.get("trait_settlement"))),
        ("Political complexity", _fmt(r.get("trait_politics"))),
        ("Descent", _fmt(r.get("trait_descent"))),
        ("Class stratification", _fmt(r.get("trait_class"))),
        ("Geometry", f"{geom_kind} · {span_s}"),
        ("Area", area_s),
        ("Merge confidence", conf_s),
    ]
    body = "".join(
        f"<tr><td style='color:#666;padding-right:8px;white-space:nowrap;"
        f"vertical-align:top'>{k}</td><td>{v}</td></tr>"
        for k, v in rows
    )

    alt_s = ""
    if alt:
        shown = ", ".join(alt[:8]) + (" …" if len(alt) > 8 else "")
        alt_s = (
            f"<div style='color:#888;font-size:10px;margin-top:4px'>"
            f"also: {shown}</div>"
        )

    return (
        "<div style='font-family:sans-serif;font-size:12px;max-width:340px'>"
        f"<div style='font-size:14px;font-weight:600'>{name}{review}</div>"
        f"<table style='border-collapse:collapse;margin-top:6px'>{body}</table>"
        f"{alt_s}"
        "</div>"
    )


def add_canonical_layers(m, canonical):
    """Add the canonical polygon + point layers to map ``m``.

    Returns ``(search_index, n_polygons, n_points)`` where ``search_index`` is a
    list of dicts {name, id, lat, lon, bbox|null, n} consumed by the search box.
    """
    c = canonical.copy()

    is_poly = c.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    polys = c[is_poly].copy()
    pts = c[~is_poly].copy()

    search_index = []

    # ---------------- territory polygons (one GeoJson layer) ---------------- #
    if not polys.empty:
        # Simplify for display performance (data is preserved in parquet).
        polys["geometry"] = polys.geometry.simplify(0.02)

        fg_poly = folium.FeatureGroup(
            name="Canonical entities — territories (polygons)", show=True
        )

        def _style(feat):
            n = feat["properties"].get("n_sources", 1)
            col = _color_for(n)
            return {
                "fillColor": col,
                "color": col,
                "weight": 0.8,
                "fillOpacity": 0.45,
            }

        def _highlight(_feat):
            return {"weight": 2.5, "fillOpacity": 0.7}

        # Build features carrying canonical_id (for search) + popup html.
        feats = []
        for _, r in polys.iterrows():
            geom = r["geometry"]
            if geom is None or geom.is_empty:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "geometry": geom.__geo_interface__,
                    "properties": {
                        "canonical_id": r.get("canonical_id"),
                        "preferred_name": _fmt(r.get("preferred_name"), "(unnamed)"),
                        "n_sources": int(r.get("n_sources") or 1),
                        "_popup": _popup_html(r),
                    },
                }
            )
            b = geom.bounds  # (minx, miny, maxx, maxy)
            search_index.append(
                {
                    "name": _fmt(r.get("preferred_name"), "(unnamed)"),
                    "id": r.get("canonical_id"),
                    "lat": (b[1] + b[3]) / 2.0,
                    "lon": (b[0] + b[2]) / 2.0,
                    "bbox": [[b[1], b[0]], [b[3], b[2]]],
                    "n": int(r.get("n_sources") or 1),
                }
            )

        gj = folium.GeoJson(
            {"type": "FeatureCollection", "features": feats},
            name="Canonical territories",
            style_function=_style,
            highlight_function=_highlight,
            popup=folium.GeoJsonPopup(fields=["_popup"], labels=False, max_width=360),
            tooltip=folium.GeoJsonTooltip(
                fields=["preferred_name", "n_sources"],
                aliases=["", "sources"],
                sticky=True,
            ),
        )
        gj.add_to(fg_poly)
        fg_poly.add_to(m)

    # ---------------- society / people points (clustered) ------------------ #
    if not pts.empty:
        fg_pt = folium.FeatureGroup(
            name="Canonical entities — points", show=True
        )
        cluster = MarkerCluster(
            name="Canonical points", options={"maxClusterRadius": 45}
        ).add_to(fg_pt)
        for _, r in pts.iterrows():
            geom = r["geometry"]
            if geom is None or geom.is_empty:
                continue
            lat, lon = geom.y, geom.x
            n = int(r.get("n_sources") or 1)
            radius = 4 + min(n, 5)  # bigger = more corroborated
            folium.CircleMarker(
                [lat, lon],
                radius=radius,
                color=_color_for(n),
                weight=1,
                fill=True,
                fill_color=_color_for(n),
                fill_opacity=0.85,
                popup=folium.Popup(_popup_html(r), max_width=360),
                tooltip=_fmt(r.get("preferred_name"), "(unnamed)"),
            ).add_to(cluster)
            search_index.append(
                {
                    "name": _fmt(r.get("preferred_name"), "(unnamed)"),
                    "id": r.get("canonical_id"),
                    "lat": lat,
                    "lon": lon,
                    "bbox": None,
                    "n": n,
                }
            )
        fg_pt.add_to(m)

    return search_index, len(polys), len(pts)


# --------------------------------------------------------------------------- #
#  Self-contained name search (no external CDN — pure Leaflet + vanilla JS)
# --------------------------------------------------------------------------- #
def add_search_box(m, search_index):
    """Inject a dependency-free search widget that filters by preferred name
    and flies/zooms the map to the matched canonical entity."""
    map_var = m.get_name()
    index_json = json.dumps(search_index, ensure_ascii=False)

    css = """
    <style>
    #afef-search{position:fixed;top:10px;left:10px;z-index:10000;
      font-family:sans-serif;width:280px}
    #afef-search input{width:100%;box-sizing:border-box;padding:7px 10px;
      border:1px solid #bbb;border-radius:6px;font-size:13px;
      box-shadow:0 1px 4px rgba(0,0,0,.25)}
    #afef-results{list-style:none;margin:2px 0 0;padding:0;background:#fff;
      border-radius:6px;box-shadow:0 1px 6px rgba(0,0,0,.25);max-height:50vh;
      overflow:auto;display:none}
    #afef-results li{padding:6px 10px;font-size:12px;cursor:pointer;
      border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between}
    #afef-results li:last-child{border-bottom:none}
    #afef-results li:hover,#afef-results li.afef-active{background:#f0eaf7}
    #afef-results .afef-badge{color:#fff;border-radius:3px;padding:0 5px;
      font-size:10px;line-height:18px;height:18px}
    #afef-results .afef-empty{color:#999;cursor:default}
    </style>
    """

    html = """
    <div id="afef-search">
      <input id="afef-q" type="text" autocomplete="off" spellcheck="false"
             placeholder="Search canonical group by name…" />
      <ul id="afef-results"></ul>
    </div>
    """

    js = f"""
    <script>
    (function() {{
      var IDX = {index_json};
      var COLORS = {{1:"#9e9ac8",2:"#6a51a3",3:"#fd8d3c",4:"#e6550d",5:"#a63603"}};
      function colorFor(n){{ return COLORS[n>=5?5:(n||1)] || COLORS[1]; }}

      function ready(fn){{
        if (typeof {map_var} !== "undefined") {{ fn(); }}
        else {{ setTimeout(function(){{ ready(fn); }}, 60); }}
      }}

      ready(function() {{
        var map = {map_var};
        var q = document.getElementById("afef-q");
        var ul = document.getElementById("afef-results");
        var marker = null;
        var active = -1, current = [];

        function clearMarker(){{ if (marker){{ map.removeLayer(marker); marker = null; }} }}

        function goTo(item){{
          clearMarker();
          if (item.bbox) {{
            map.fitBounds(item.bbox, {{maxZoom: 9, padding:[40,40]}});
          }} else {{
            map.flyTo([item.lat, item.lon], 8);
          }}
          marker = L.circleMarker([item.lat, item.lon], {{
            radius: 11, color: "#d7263d", weight: 3,
            fillColor: colorFor(item.n), fillOpacity: 0.5
          }}).addTo(map);
          marker.bindTooltip(item.name, {{permanent:true, direction:"top",
            className:"afef-found"}}).openTooltip();
          hide();
        }}

        function hide(){{ ul.style.display = "none"; active = -1; }}

        function render(matches){{
          current = matches;
          ul.innerHTML = "";
          if (!matches.length){{
            var li = document.createElement("li");
            li.className = "afef-empty"; li.textContent = "no match";
            ul.appendChild(li); ul.style.display = "block"; return;
          }}
          matches.forEach(function(it, i){{
            var li = document.createElement("li");
            var nm = document.createElement("span"); nm.textContent = it.name;
            var bd = document.createElement("span");
            bd.className = "afef-badge"; bd.style.background = colorFor(it.n);
            bd.textContent = it.n + (it.bbox ? " ▱" : " ●");
            li.appendChild(nm); li.appendChild(bd);
            li.addEventListener("mousedown", function(e){{ e.preventDefault(); goTo(it); }});
            li.addEventListener("mouseenter", function(){{ setActive(i); }});
            ul.appendChild(li);
          }});
          ul.style.display = "block";
        }}

        function setActive(i){{
          var items = ul.querySelectorAll("li");
          items.forEach(function(el){{ el.classList.remove("afef-active"); }});
          active = i;
          if (i>=0 && i<items.length) items[i].classList.add("afef-active");
        }}

        function search(){{
          var s = q.value.trim().toLowerCase();
          if (s.length < 1){{ hide(); return; }}
          var starts = [], contains = [];
          for (var i=0;i<IDX.length;i++){{
            var nm = (IDX[i].name||"").toLowerCase();
            if (nm.indexOf(s) === 0) starts.push(IDX[i]);
            else if (nm.indexOf(s) !== -1) contains.push(IDX[i]);
            if (starts.length + contains.length > 200) break;
          }}
          render(starts.concat(contains).slice(0, 50));
        }}

        q.addEventListener("input", search);
        q.addEventListener("focus", function(){{ if (q.value.trim()) search(); }});
        q.addEventListener("keydown", function(e){{
          var items = ul.querySelectorAll("li");
          if (e.key === "ArrowDown"){{ e.preventDefault(); setActive(Math.min(active+1, items.length-1)); }}
          else if (e.key === "ArrowUp"){{ e.preventDefault(); setActive(Math.max(active-1, 0)); }}
          else if (e.key === "Enter"){{
            e.preventDefault();
            if (active>=0 && current[active]) goTo(current[active]);
            else if (current.length) goTo(current[0]);
          }} else if (e.key === "Escape"){{ hide(); q.blur(); }}
        }});
        document.addEventListener("click", function(e){{
          if (!document.getElementById("afef-search").contains(e.target)) hide();
        }});
        // keep Leaflet from swallowing scroll/keys while interacting with the box
        if (L && L.DomEvent){{
          var box = document.getElementById("afef-search");
          L.DomEvent.disableClickPropagation(box);
          L.DomEvent.disableScrollPropagation(box);
        }}
      }});
    }})();
    </script>
    """

    root = m.get_root()
    root.header.add_child(folium.Element(css))
    root.html.add_child(folium.Element(html))
    root.html.add_child(folium.Element(js))
