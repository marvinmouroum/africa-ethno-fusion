# africa-ethno-fusion

Fuse the major open datasets that map **which ethnic groups live where in Africa**
into one queryable star schema (pandas / GeoPandas), then export to
GeoParquet, GeoPackage, or CSV.

## Why a star schema (and not one big table)

The datasets do **not** share a universal key. They link through a *chain* of
partial keys, so a flat join would silently drop or duplicate most rows. Instead
we keep every source record as its own row and express relationships explicitly:

```
Murdock polygon ─(EA "CODE")→ Ethnographic Atlas society ─(glottocode)→ Glottolog ─(ISO 639-3)→ Joshua Project
   (territory ~1900)               (cultural traits)            (language)              (people groups, today)

GREG (1964) ┐
            ├─ carry NO language/glotto codes → only joinable by NAME (fuzzy, lower confidence)
GeoEPR  ────┘
```

### Three tables

| table | type | grain | purpose |
|---|---|---|---|
| **`groups`** | GeoDataFrame (EPSG:4326) | one ethnic-group/society record per source | the spine: geometry + identity + crosswalk keys |
| **`traits`** | DataFrame (tidy/long) | society × variable | the ethnographic "situation" (mostly Ethnographic Atlas) |
| **`links`** | DataFrame | record ↔ record | crosswalk with method + confidence |

See `africa_ethno_fusion/schema.py` for the exact column list and docs.

## Sources

| source | key | geometry | join keys it provides | auto-download | license |
|---|---|---|---|---|---|
| `murdock_map` | Murdock 1959 map (Nunn) | polygons (~1830–1900) | `ea_society_id`, name | ✅ GitHub mirror | CC BY-NC-SA 3.0 |
| `greg` | Atlas Narodov Mira 1964 | polygons | name only | ✅ ICR | cite-only |
| `geoepr` | Ethnic Power Relations | polygons (time-varying) | name only | ✅ ICR | cite-only |
| `dplace_ea` | Ethnographic Atlas | points + **traits** | `ea_society_id`, `glottocode` | ✅ GitHub | CC BY-NC 4.0 |
| `glottolog` | Glottolog languoids | points | `glottocode` ↔ `iso639_3` | ✅ GitHub | CC BY 4.0 |
| `joshua_project` | Joshua Project | points | `iso639_3` (ROL3) | ⚠️ free API key | custom terms |
| `glottography` | Asher 2007 atlas | polygons | `glottocode` | ✅ Zenodo (open WLMS alt.) | mostly CC BY 4.0 |
| `afrobarometer`/`dhs`/`ipums` | surveys/census | points | self-reported ethnicity | ❌ gated (local file) | per-provider |

> ⚠️ **Licensing matters for commercial use.** Murdock/Nunn and D-PLACE are
> **NonCommercial**; Joshua Project has custom terms. Glottolog (CC BY 4.0) and
> GREG/GeoEPR (cite-only) are the cleanest. Review before embedding in a product.

## Install & run

```bash
pip install -r requirements.txt          # geopandas, shapely, requests, pyarrow, (rapidfuzz)
python build.py                          # open sources, Africa only -> ./out
python build.py --out data --fmt gpkg    # just a GeoPackage
```

Or from Python:

```python
from africa_ethno_fusion import build, export
frames = build()                         # {"groups","traits","links"}
export(frames, "out")
```

## What it enables

* **Point → identity.** Given a (lat, lon), find the ethnic territory it falls in,
  then its cultural traits and language:
  ```python
  import geopandas as gpd
  from shapely.geometry import Point
  g = gpd.read_parquet("out/groups.parquet")
  poly = g[g.geom_kind == "territory_polygon"]
  hit = poly[poly.contains(Point(36.8, -1.3))]      # Nairobi
  ```
* **Group → everything.** Look up a name and get historical territory (Murdock),
  1964 territory (GREG), modern political settlement (GeoEPR), language, and traits.
* **Ethnographic detail.** Join `traits` on `ea_society_id` to get subsistence
  (EA001–005), political complexity (EA033 jurisdictional hierarchy), descent
  (EA043), settlement, religion, etc.
* **Temporal.** GeoEPR `period_from`/`period_to` show settlement change over time.
* **Cross-border / spatial.** Territory areas, neighbors, groups split by colonial borders.

## License

The code in this repository is released under the **MIT License** — free to use,
modify, and redistribute, **as long as you keep the copyright notice / credit the
author** (Marvin Mouroum). See [`LICENSE`](LICENSE).

> The third-party *datasets* this tool downloads keep their own licenses (see the
> Sources table above); MIT covers this pipeline code, not the underlying data.

## Caveats baked into the data

* Ethnic-homeland polygons imply crisp borders that don't exist; groups overlap & migrate.
* Each polygon source freezes a moment: Murdock ~1900, GREG 1964, GeoEPR per-period.
* GREG/GeoEPR have no language codes — their links to other sources are **fuzzy name
  matches** (`links.method == "fuzzy_name"`, confidence < 1.0). Treat as hints.
* Survey ethnicity is country-specific and not harmonized; needs per-country crosswalks.
* DHS coordinates are randomly displaced (≤2/5/10 km) for privacy.
