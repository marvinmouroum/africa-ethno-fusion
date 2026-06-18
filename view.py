#!/usr/bin/env python3
"""Build an interactive 'dominant ethnicity' explorer for Africa -> out/map.html.

Africa is tiled into a grid. For each cell we rank the canonical ethnic groups
whose territory covers the cell centre, by population (territory area breaks
ties / fills gaps). The map colours each cell by its #1 group; UI buttons switch
the colouring to the 2nd / 3rd most common group; and a selector highlights every
cell where one chosen ethnicity appears.

Run: python view.py   (after building out/canonical.parquet)
"""
import hashlib
import json

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

OUT = "out"
STEP = 0.7  # grid cell size in degrees (~78 km). Smaller = finer + bigger file.


def color_for(name):
    """Deterministic, well-spread colour per ethnicity name (CSS hsl string)."""
    if not name:
        return None
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    hue = h % 360
    sat = 58 + (h // 360) % 30        # 58–88
    lig = 45 + (h // 11000) % 18      # 45–63
    return f"hsl({hue},{sat}%,{lig}%)"


def main():
    c = gpd.read_parquet(f"{OUT}/canonical.parquet")
    poly = c[c.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    poly["geometry"] = poly.geometry.buffer(0)  # repair invalid
    poly = poly[~poly.geometry.is_empty & poly.geometry.notna()]
    poly["pop"] = pd.to_numeric(poly["population_total"], errors="coerce").fillna(0.0)
    poly["area_"] = pd.to_numeric(poly["area_sqkm"], errors="coerce").fillna(1e12)
    print(f"{len(poly)} territory entities feed the dominance grid")

    # ---- build the grid (only cells whose centre falls in some territory) ----
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
    grid = gpd.GeoDataFrame({"cell_id": list(range(k))}, geometry=cells, crs=4326)
    # cell centres computed directly from the box origin (avoids the geographic-CRS
    # centroid warning and is exact for axis-aligned boxes).
    from shapely.geometry import Point
    cent = gpd.GeoDataFrame(
        {"cell_id": list(range(k))},
        geometry=[Point(cellxy[i][0] + STEP / 2, cellxy[i][1] + STEP / 2) for i in range(k)],
        crs=4326,
    )

    # ---- rank ethnicities per cell: population desc, then smaller territory ----
    j = gpd.sjoin(
        cent[["cell_id", "geometry"]],
        poly[["preferred_name", "pop", "area_", "geometry"]],
        predicate="within",
    )
    j = j.dropna(subset=["preferred_name"])
    j = j.sort_values(["cell_id", "pop", "area_"], ascending=[True, False, True])
    j = j.drop_duplicates(["cell_id", "preferred_name"])
    j["rank"] = j.groupby("cell_id").cumcount() + 1
    top = j[j["rank"] <= 3]

    cellinfo = {}
    for cid, name, pop, rank in top[["cell_id", "preferred_name", "pop", "rank"]].itertuples(index=False):
        d = cellinfo.setdefault(int(cid), {})
        d[f"r{rank}"] = name
        d[f"p{rank}"] = int(pop) if pop and pop > 0 else 0
    print(f"{len(cellinfo)} populated grid cells")

    # ---- per-name bbox (for the 'find this ethnicity' zoom) ----
    names_all = {d[f"r{r}"] for d in cellinfo.values() for r in (1, 2, 3) if d.get(f"r{r}")}
    bounds = poly.groupby("preferred_name").agg(
        minx=("geometry", lambda g: g.total_bounds[0]),
        miny=("geometry", lambda g: g.total_bounds[1]),
        maxx=("geometry", lambda g: g.total_bounds[2]),
        maxy=("geometry", lambda g: g.total_bounds[3]),
    )
    ethno = {}
    for nm in sorted(names_all):
        col = color_for(nm)
        bbox = None
        if nm in bounds.index:
            b = bounds.loc[nm]
            bbox = [[float(b.miny), float(b.minx)], [float(b.maxy), float(b.maxx)]]
        ethno[nm] = {"color": col, "bbox": bbox}

    # ---- grid GeoJSON ----
    def ring(x, y, s):
        return [[round(x, 3), round(y, 3)], [round(x + s, 3), round(y, 3)],
                [round(x + s, 3), round(y + s, 3)], [round(x, 3), round(y + s, 3)],
                [round(x, 3), round(y, 3)]]

    feats = []
    for cid, d in cellinfo.items():
        x, y = cellxy[cid]
        props = {}
        for r in (1, 2, 3):
            nm = d.get(f"r{r}")
            props[f"r{r}"] = nm
            props[f"p{r}"] = d.get(f"p{r}", 0)
            props[f"c{r}"] = color_for(nm) if nm else None
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [ring(x, y, STEP)]}})
    grid_geojson = {"type": "FeatureCollection", "features": feats}

    # ---- assemble map ----
    m = folium.Map(location=[2.5, 19], zoom_start=4, tiles="CartoDB positron",
                   control_scale=True)
    map_var = m.get_name()
    payload = (
        "<script>window.AFEF=" +
        json.dumps({"grid": grid_geojson, "ethno": ethno}, ensure_ascii=False) +
        ";</script>"
    )
    m.get_root().html.add_child(folium.Element(payload))
    m.get_root().header.add_child(folium.Element(_CSS))
    m.get_root().html.add_child(folium.Element(_PANEL))
    m.get_root().html.add_child(folium.Element(_JS.replace("__MAP__", map_var)))

    m.save(f"{OUT}/map.html")
    print(f"wrote {OUT}/map.html  ({len(feats)} cells, {len(ethno)} ethnicities)")


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
  box-shadow:0 1px 8px rgba(0,0,0,.3);max-width:230px}
#afef-legend b{font-size:12px}
#afef-legend .row{display:flex;align-items:center;gap:6px;margin-top:3px}
.afef-tip b{color:#111}
</style>
"""

_PANEL = """
<div id="afef-panel">
  <h3>Ethnicities of Africa</h3>
  <div class="sub" id="afef-modesub">Colour = most common group in each cell</div>
  <div class="afef-modes">
    <button data-m="1" class="on">1st</button>
    <button data-m="2">2nd</button>
    <button data-m="3">3rd</button>
  </div>
  <input id="afef-q" type="text" autocomplete="off" spellcheck="false"
         placeholder="Find one ethnicity → see where they live" />
  <ul id="afef-res"></ul>
  <button id="afef-clear">✕ clear selection — show dominance map</button>
</div>
<div id="afef-legend"></div>
"""

_JS = """
<script>
(function(){
  function ready(fn){ if(typeof __MAP__!=="undefined" && window.AFEF){fn();}
                      else {setTimeout(function(){ready(fn);},60);} }
  ready(function(){
    var map=__MAP__, GRID=window.AFEF.grid, ETHNO=window.AFEF.ethno;
    var mode=1, selected=null, marker=null;
    var EMPTY="#e9e9e9";

    function fmt(n){ return (n&&n>0)? Number(n).toLocaleString() : ""; }

    function cellStyle(f){
      var p=f.properties, fill=EMPTY, op=0.06, line=0.1, lc="#fff";
      if(selected){
        var present=[p.r1,p.r2,p.r3].indexOf(selected);
        if(present>=0){ fill=(ETHNO[selected]||{}).color||"#d7263d"; op=0.85;
                        line=0.6; lc="#7a0010"; }
        else { fill=EMPTY; op=0.05; }
      } else {
        var col=p["c"+mode];
        if(col){ fill=col; op=0.72; } else { fill=EMPTY; op=0.05; }
      }
      return {fillColor:fill,color:lc,weight:line,fillOpacity:op};
    }

    function tip(p){
      var rows=[["1st",p.r1,p.p1],["2nd",p.r2,p.p2],["3rd",p.r3,p.p3]];
      var h="<div class='afef-tip'>";
      rows.forEach(function(r){
        if(r[1]){ var hl=(selected&&r[1]===selected)?";color:#d7263d":"";
          h+="<div style='font-size:11px"+hl+"'>"+r[0]+": <b>"+r[1]+"</b>"+
             (r[2]?" · "+fmt(r[2]):"")+"</div>"; }
      });
      return h+"</div>";
    }

    var layer=L.geoJSON(GRID,{style:cellStyle,
      onEachFeature:function(f,l){ l.bindTooltip(tip(f.properties),{sticky:true}); }
    }).addTo(map);
    function restyle(){ layer.setStyle(cellStyle);
      layer.eachLayer(function(l){ l.setTooltipContent(tip(l.feature.properties)); }); }

    // ---- mode buttons ----
    var sub=document.getElementById("afef-modesub");
    var SUBT={1:"Colour = most common group in each cell",
              2:"Colour = 2nd most common group",
              3:"Colour = 3rd most common group"};
    document.querySelectorAll(".afef-modes button").forEach(function(b){
      b.onclick=function(){
        document.querySelectorAll(".afef-modes button").forEach(function(x){x.classList.remove("on");});
        b.classList.add("on"); mode=+b.dataset.m; sub.textContent=SUBT[mode];
        clearSel(); restyle(); legend();
      };
    });

    // ---- legend: top dominant groups for current mode ----
    function legend(){
      var counts={};
      GRID.features.forEach(function(f){ var n=f.properties["r"+mode];
        if(n) counts[n]=(counts[n]||0)+1; });
      var arr=Object.keys(counts).map(function(n){return [n,counts[n]];})
                .sort(function(a,b){return b[1]-a[1];}).slice(0,12);
      var h="<b>Top groups (rank "+mode+")</b>";
      arr.forEach(function(r){
        h+="<div class='row'><span class='afef-sw' style='background:"+
           (ETHNO[r[0]]||{}).color+"'></span>"+r[0]+" <span style='color:#999'>("+r[1]+")</span></div>";
      });
      document.getElementById("afef-legend").innerHTML=h;
    }

    // ---- selector: find one ethnicity, highlight where it lives ----
    var q=document.getElementById("afef-q"), ul=document.getElementById("afef-res");
    var clearBtn=document.getElementById("afef-clear");
    var NAMES=Object.keys(ETHNO).sort();

    function clearSel(){ selected=null; if(marker){map.removeLayer(marker);marker=null;}
      clearBtn.style.display="none"; ul.style.display="none"; }
    clearBtn.onclick=function(){ clearSel(); q.value=""; restyle(); legend(); };

    function pick(name){
      selected=name; ul.style.display="none"; q.value=name;
      clearBtn.style.display="block";
      var e=ETHNO[name];
      if(e&&e.bbox){ map.fitBounds(e.bbox,{maxZoom:7,padding:[30,30]}); }
      restyle();
      document.getElementById("afef-modesub").textContent="Showing where "+name+" appear (any rank)";
    }

    function search(){
      var s=q.value.trim().toLowerCase();
      if(!s){ ul.style.display="none"; return; }
      var starts=[],has=[];
      for(var i=0;i<NAMES.length;i++){ var nm=NAMES[i].toLowerCase();
        if(nm.indexOf(s)===0) starts.push(NAMES[i]);
        else if(nm.indexOf(s)>=0) has.push(NAMES[i]);
        if(starts.length+has.length>120) break; }
      var all=starts.concat(has).slice(0,40);
      ul.innerHTML="";
      if(!all.length){ ul.style.display="none"; return; }
      all.forEach(function(n){
        var li=document.createElement("li");
        li.innerHTML="<span class='afef-sw' style='background:"+(ETHNO[n]||{}).color+"'></span>"+n;
        li.onmousedown=function(ev){ ev.preventDefault(); pick(n); };
        ul.appendChild(li);
      });
      ul.style.display="block";
    }
    q.addEventListener("input",search);
    q.addEventListener("focus",function(){ if(q.value.trim())search(); });
    q.addEventListener("keydown",function(e){
      if(e.key==="Enter"){ e.preventDefault();
        var first=ul.querySelector("li"); if(first){ first.dispatchEvent(new MouseEvent("mousedown")); } }
      else if(e.key==="Escape"){ ul.style.display="none"; q.blur(); } });

    if(L&&L.DomEvent){ var box=document.getElementById("afef-panel");
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box); }

    legend();
  });
})();
</script>
"""


if __name__ == "__main__":
    main()
