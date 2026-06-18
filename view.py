#!/usr/bin/env python3
"""Build the "Ethnicities of Africa" explorer -> out/map.html.

Africa is partitioned into organic territory polygons (conventional-map style,
like country borders) coloured by the DOMINANT ethnicity. Under the hood we rank
groups on a fine grid (by population; territory area breaks ties), then dissolve
adjacent same-group cells into smooth bordered polygons. UI: buttons recolour by
the 1st / 2nd / 3rd most common group per region; a selector highlights every
region where one chosen ethnicity appears.

Run: python view.py   (after building out/canonical.parquet)
"""
import hashlib
import json
import warnings

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, box, mapping

warnings.filterwarnings("ignore", message=".*geographic CRS.*")

OUT = "out"
STEP = 0.25     # dominance grid cell (deg, ~28 km). Finer = smoother borders, bigger file.
SMOOTH = 0.18   # buffer round-trip (deg) to round the stair-stepped grid edges.
SIMP = 0.06     # vertex simplification tolerance (deg).
NDIG = 2        # coordinate rounding in the output GeoJSON.


def color_for(name):
    if not name:
        return None
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    return f"hsl({h % 360},{58 + (h // 360) % 30}%,{45 + (h // 11000) % 18}%)"


def _round_geom(g):
    m = mapping(g)

    def rc(c):
        if isinstance(c, (list, tuple)):
            if c and isinstance(c[0], (int, float)):
                return [round(c[0], NDIG), round(c[1], NDIG)]
            return [rc(x) for x in c]
        return c

    m["coordinates"] = rc(m["coordinates"])
    return m


def main(out_html=None):
    out_html = out_html or f"{OUT}/map.html"
    c = gpd.read_parquet(f"{OUT}/canonical.parquet")
    poly = c[c.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    poly["geometry"] = poly.geometry.buffer(0)
    poly = poly[~poly.geometry.is_empty & poly.geometry.notna()]
    poly["pop"] = pd.to_numeric(poly["population_total"], errors="coerce").fillna(0.0)
    poly["area_"] = pd.to_numeric(poly["area_sqkm"], errors="coerce").fillna(1e12)
    print(f"{len(poly)} territory entities feed the dominance partition")

    # ---- fine grid: rank groups per cell by population, area as tiebreak ----
    minx, miny, maxx, maxy = poly.total_bounds
    xs = np.arange(np.floor(minx), np.ceil(maxx), STEP)
    ys = np.arange(np.floor(miny), np.ceil(maxy), STEP)
    cells, cellxy = [], {}
    k = 0
    for x in xs:
        for y in ys:
            cells.append(box(x, y, x + STEP, y + STEP))
            cellxy[k] = (float(x), float(y))
            k += 1
    grid = gpd.GeoDataFrame({"cell_id": range(k)}, geometry=cells, crs=4326)
    cent = gpd.GeoDataFrame(
        {"cell_id": range(k)},
        geometry=[Point(cellxy[i][0] + STEP / 2, cellxy[i][1] + STEP / 2) for i in range(k)],
        crs=4326,
    )
    j = gpd.sjoin(cent[["cell_id", "geometry"]],
                  poly[["preferred_name", "pop", "area_", "geometry"]], predicate="within")
    j = j.dropna(subset=["preferred_name"]).sort_values(
        ["cell_id", "pop", "area_"], ascending=[True, False, True])
    j = j.drop_duplicates(["cell_id", "preferred_name"])
    j["rank"] = j.groupby("cell_id").cumcount() + 1
    j = j[j["rank"] <= 3]

    cellrank = {1: {}, 2: {}, 3: {}}
    for cid, name, rank in j[["cell_id", "preferred_name", "rank"]].itertuples(index=False):
        cellrank[rank][int(cid)] = name
    print(f"{len(cellrank[1])} populated cells")

    # ---- per-name attributes (representative canonical row = max population) ----
    names_all = {n for r in cellrank.values() for n in r.values()}
    rep = (poly.sort_values("pop", ascending=False)
               .drop_duplicates("preferred_name").set_index("preferred_name"))
    bounds = poly.dissolve(by="preferred_name").geometry.bounds  # minx/miny/maxx/maxy
    ethno = {}
    for nm in sorted(names_all):
        col = color_for(nm)
        bbox = None
        if nm in bounds.index:
            b = bounds.loc[nm]
            bbox = [[float(b.miny), float(b.minx)], [float(b.maxy), float(b.maxx)]]
        r = rep.loc[nm] if nm in rep.index else None
        ethno[nm] = {
            "color": col,
            "bbox": bbox,
            "pop": int(r["pop"]) if (r is not None and r["pop"] > 0) else None,
            "family": (None if r is None or pd.isna(r.get("language_family")) else r.get("language_family")),
        }

    # ---- dissolve same-group cells into organic bordered polygons, per rank ----
    gidx = grid.set_index("cell_id")

    def dissolve_rank(r):
        items = cellrank[r]
        if not items:
            return {"type": "FeatureCollection", "features": []}
        gdf = gidx.loc[list(items)].copy()
        gdf["name"] = list(items.values())
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=4326)
        dis = gdf.dissolve(by="name")
        # round the stair-stepped grid edges into organic borders
        dis["geometry"] = dis.geometry.buffer(SMOOTH).buffer(-SMOOTH).simplify(SIMP)
        dis = dis[~dis.geometry.is_empty & dis.geometry.notna()]
        areas = dis.to_crs(6933).area / 1e6
        feats = []
        for nm, row in dis.iterrows():
            g = row.geometry
            if g is None or g.is_empty:
                continue
            feats.append({"type": "Feature",
                          "properties": {"name": nm, "area": int(areas.loc[nm])},
                          "geometry": _round_geom(g)})
        return {"type": "FeatureCollection", "features": feats}

    data = {str(r): dissolve_rank(r) for r in (1, 2, 3)}
    print("dissolved polygons per rank:", {r: len(fc["features"]) for r, fc in data.items()})

    # ---- assemble map ----
    m = folium.Map(location=[2.5, 19], zoom_start=4, tiles="CartoDB positron",
                   control_scale=True)
    map_var = m.get_name()
    payload = ("<script>window.AFEF=" +
               json.dumps({"data": data, "ethno": ethno}, ensure_ascii=False) +
               ";</script>")
    m.get_root().html.add_child(folium.Element(payload))
    m.get_root().header.add_child(folium.Element(_CSS))
    m.get_root().html.add_child(folium.Element(_PANEL))
    m.get_root().html.add_child(folium.Element(_JS.replace("__MAP__", map_var)))
    import os
    os.makedirs(os.path.dirname(out_html) or ".", exist_ok=True)
    m.save(out_html)
    print(f"wrote {out_html}  ({len(ethno)} ethnicities)")


_CSS = """
<style>
#afef-panel{position:fixed;top:12px;left:12px;z-index:10000;font-family:sans-serif;
  width:300px;background:#fff;border-radius:8px;box-shadow:0 1px 8px rgba(0,0,0,.3);
  padding:12px 14px}
#afef-panel h3{margin:0 0 2px;font-size:15px}
#afef-panel .sub{color:#777;font-size:11px;margin-bottom:8px}
.afef-modes{display:flex;gap:6px;margin-bottom:8px}
.afef-modes button{flex:1;padding:6px 0;border:1px solid #ccc;background:#f7f7f7;
  border-radius:5px;font-size:12px;cursor:pointer}
.afef-modes button.on{background:#333;color:#fff;border-color:#333}
#afef-q{width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid #bbb;
  border-radius:6px;font-size:13px}
#afef-res{list-style:none;margin:3px 0 0;padding:0;max-height:34vh;overflow:auto;
  border-radius:6px;display:none;border:1px solid #eee}
#afef-res li{padding:6px 9px;font-size:12px;cursor:pointer;display:flex;
  align-items:center;gap:7px;border-bottom:1px solid #f2f2f2}
#afef-res li:hover,#afef-res li.on{background:#f0f0f0}
.afef-sw{width:12px;height:12px;border-radius:3px;flex:none}
#afef-clear{display:none;margin-top:8px;width:100%;padding:6px 0;border:0;
  background:#d7263d;color:#fff;border-radius:5px;font-size:12px;cursor:pointer}
#afef-legend{position:fixed;bottom:14px;left:12px;z-index:10000;background:#fff;
  font-family:sans-serif;font-size:11px;border-radius:8px;padding:8px 11px;
  box-shadow:0 1px 8px rgba(0,0,0,.3);max-width:250px}
#afef-legend b{font-size:12px}
#afef-legend-list{max-height:52vh;overflow-y:auto;margin-top:5px;padding-right:2px}
#afef-legend .row{display:flex;align-items:center;gap:6px;margin-top:2px;cursor:pointer;
  padding:2px 3px;border-radius:3px}
#afef-legend .row:hover{background:#f0f0f0}
#afef-legend .row.on{background:#fde7ea;font-weight:600}
</style>
"""

_PANEL = """
<div id="afef-panel">
  <h3>Ethnicities of Africa</h3>
  <div class="sub" id="afef-modesub">Each region coloured by its most common ethnicity</div>
  <div class="afef-modes">
    <button data-m="1" class="on">1st</button>
    <button data-m="2">2nd</button>
    <button data-m="3">3rd</button>
  </div>
  <input id="afef-q" type="text" autocomplete="off" spellcheck="false"
         placeholder="Find one ethnicity → see where they live" />
  <ul id="afef-res"></ul>
  <button id="afef-clear">✕ clear — show dominance map</button>
</div>
<div id="afef-legend"></div>
"""

_JS = """
<script>
(function(){
  function ready(fn){ if(typeof __MAP__!=="undefined" && window.AFEF){fn();}
                      else {setTimeout(function(){ready(fn);},60);} }
  ready(function(){
    var map=__MAP__, DATA=window.AFEF.data, ETHNO=window.AFEF.ethno;
    var mode=1, selected=null, layers={}, hi=null;
    var EMPTY="#e9e9e9";
    function fmt(n){ return (n&&n>0)? Number(n).toLocaleString() : ""; }
    var RANKW={1:"most common",2:"2nd most common",3:"3rd most common"};

    function baseStyle(f){
      var nm=f.properties.name, col=(ETHNO[nm]||{}).color||EMPTY;
      var dim = selected && nm!==selected;
      return {fillColor:col,color:"#ffffff",weight:0.7,
              fillOpacity: dim?0.10:0.80};
    }
    function tip(nm){
      var e=ETHNO[nm]||{}, h="<b>"+nm+"</b><br><span style='color:#666'>"+RANKW[mode]+" here</span>";
      if(e.pop) h+="<br>population ≈ "+fmt(e.pop);
      if(e.family) h+="<br>family: "+e.family;
      return h;
    }
    function mk(r){ return L.geoJSON(DATA[String(r)],{style:baseStyle,
      onEachFeature:function(f,l){ l.bindTooltip(tip(f.properties.name),{sticky:true});
        l.on("click",function(){ pick(f.properties.name); }); }}); }
    for(var r=1;r<=3;r++) layers[r]=mk(r);
    layers[1].addTo(map);

    function setMode(n){
      map.removeLayer(layers[mode]); mode=n; layers[mode].addTo(map);
      if(selected){ layers[mode].setStyle(baseStyle); buildHi(); }
      legend();
      layers[mode].eachLayer(function(l){ l.setTooltipContent(tip(l.feature.properties.name)); });
    }
    var sub=document.getElementById("afef-modesub");
    document.querySelectorAll(".afef-modes button").forEach(function(b){
      b.onclick=function(){
        document.querySelectorAll(".afef-modes button").forEach(function(x){x.classList.remove("on");});
        b.classList.add("on"); setMode(+b.dataset.m);
        if(!selected) sub.textContent="Each region coloured by its "+RANKW[+b.dataset.m]+" ethnicity";
      };
    });

    // ---- selector: highlight EVERY region where a group appears (any rank) ----
    var q=document.getElementById("afef-q"), ul=document.getElementById("afef-res");
    var clearBtn=document.getElementById("afef-clear");
    var NAMES=Object.keys(ETHNO).sort();

    function buildHi(){
      if(hi){ map.removeLayer(hi); hi=null; }
      if(!selected) return;
      var feats=[];
      ["1","2","3"].forEach(function(r){
        DATA[r].features.forEach(function(f){ if(f.properties.name===selected) feats.push(f); });
      });
      hi=L.geoJSON({type:"FeatureCollection",features:feats},{
        style:{fillColor:(ETHNO[selected]||{}).color||"#d7263d",color:"#7a0010",
               weight:1.6,fillOpacity:0.88}, interactive:false}).addTo(map);
    }
    function clearSel(){ selected=null; if(hi){map.removeLayer(hi);hi=null;}
      clearBtn.style.display="none"; ul.style.display="none";
      layers[mode].setStyle(baseStyle);
      sub.textContent="Each region coloured by its "+RANKW[mode]+" ethnicity"; legend(); }
    clearBtn.onclick=function(){ q.value=""; clearSel(); };

    function pick(name){
      selected=name; q.value=name; ul.style.display="none"; clearBtn.style.display="block";
      layers[mode].setStyle(baseStyle); buildHi();
      var e=ETHNO[name];
      if(e&&e.bbox) map.fitBounds(e.bbox,{maxZoom:7,padding:[30,30]});
      sub.textContent="Showing where "+name+" appear (any rank)"; legend();
    }
    function search(){
      var s=q.value.trim().toLowerCase();
      if(!s){ ul.style.display="none"; return; }
      var a=[],b=[];
      for(var i=0;i<NAMES.length;i++){ var nm=NAMES[i].toLowerCase();
        if(nm.indexOf(s)===0)a.push(NAMES[i]); else if(nm.indexOf(s)>=0)b.push(NAMES[i]);
        if(a.length+b.length>120)break; }
      var all=a.concat(b).slice(0,40); ul.innerHTML="";
      if(!all.length){ ul.style.display="none"; return; }
      all.forEach(function(n){ var li=document.createElement("li");
        li.innerHTML="<span class='afef-sw' style='background:"+(ETHNO[n]||{}).color+"'></span>"+n;
        li.onmousedown=function(ev){ ev.preventDefault(); pick(n); }; ul.appendChild(li); });
      ul.style.display="block";
    }
    q.addEventListener("input",search);
    q.addEventListener("focus",function(){ if(q.value.trim())search(); });
    q.addEventListener("keydown",function(e){
      if(e.key==="Enter"){ e.preventDefault(); var f=ul.querySelector("li");
        if(f)f.dispatchEvent(new MouseEvent("mousedown")); }
      else if(e.key==="Escape"){ ul.style.display="none"; q.blur(); } });

    function legend(){
      var arr=DATA[String(mode)].features.map(function(f){return [f.properties.name,f.properties.area||0];})
                .sort(function(a,b){return b[1]-a[1];});
      var el=document.getElementById("afef-legend"); el.innerHTML="";
      var head=document.createElement("div");
      head.innerHTML="<b>Groups · rank "+mode+"</b> <span style='color:#999'>("+arr.length+")</span>"+
        "<div style='color:#999;font-size:10px'>scroll · click a group to locate it</div>";
      el.appendChild(head);
      var list=document.createElement("div"); list.id="afef-legend-list";
      arr.forEach(function(r){
        var row=document.createElement("div");
        row.className="row"+(r[0]===selected?" on":"");
        var sw=document.createElement("span"); sw.className="afef-sw";
        sw.style.background=(ETHNO[r[0]]||{}).color;
        var nm=document.createElement("span"); nm.textContent=r[0];
        row.appendChild(sw); row.appendChild(nm);
        row.onmousedown=function(ev){ ev.preventDefault(); pick(r[0]); };
        list.appendChild(row);
      });
      el.appendChild(list);
    }

    if(L&&L.DomEvent){
      ["afef-panel","afef-legend"].forEach(function(id){ var e=document.getElementById(id);
        L.DomEvent.disableClickPropagation(e); L.DomEvent.disableScrollPropagation(e); });
    }
    legend();
  });
})();
</script>
"""


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
