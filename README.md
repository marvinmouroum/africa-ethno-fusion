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

### Tables

| table | type | grain | purpose |
|---|---|---|---|
| **`groups`** | GeoDataFrame (EPSG:4326) | one ethnic-group/society record per source | the spine: geometry + identity + crosswalk keys (+ `canonical_id`) |
| **`traits`** | DataFrame (tidy/long) | society × variable | the ethnographic "situation" (mostly Ethnographic Atlas) |
| **`links`** | DataFrame | record ↔ record | crosswalk with method + confidence |
| **`canonical`** | GeoDataFrame | **one resolved entity per real-world group** | the unified "one data source" layer (see below) |
| **`review_candidates`** | DataFrame | fuzzy pair | name matches that were *not* auto-merged, for review |

See `africa_ethno_fusion/schema.py` and `entity.py` for the exact columns.

### The canonical layer (entity resolution)

`canonical` collapses the per-source records into one row per real-world group by
running connected-components over `links`:

* **Exact-code merges** (EA id / glottocode / ISO 639-3) are trusted fully — this
  is the chain `Murdock → Ethnographic Atlas → Glottolog → Joshua Project`.
* **Code-less territories** (GREG, GeoEPR) attach by name: an *exact* normalized
  name merges directly; an *approximate* name needs to be a reciprocal best match
  with score ≥ 0.92. A **singleton rule** lets a name edge attach a lone territory
  to an entity but never fuse two already-built entities (no giant-component blow-up).
* Everything weaker lands in `review_candidates`; any name-based merge sets
  `needs_review = True` with a `merge_confidence` score.

Each canonical row carries: `preferred_name`, `alt_names`, contributing `sources`,
consensus `glottocode`/`iso639_3`/`ea_society_id`/`language_family`,
`historical`+`modern` geometry, `area_sqkm`, `population_total`, `primary_religion`,
key EA traits (subsistence/settlement/politics/descent/class), and `member_record_ids`.

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
frames = build()                         # {"groups","traits","links","canonical","review_candidates"}
export(frames, "out")

canonical = frames["canonical"]          # one row per resolved ethnic group
canonical[canonical.preferred_name == "Kikuyu"]
```

Pass `--no-resolve` (or `resolve=False`) to skip entity resolution and emit only
the raw `groups`/`traits`/`links` star schema.

Joshua Project needs a free API key (`--jp-api-key KEY`); the other six sources
download without credentials and are built by default.

## See the results

Two self-contained HTML views (build first, then run):

```bash
python view.py      # -> out/map.html    "Ethnicities of Africa" explorer: the
                    #                    continent is tiled into cells, each coloured
                    #                    by the MOST COMMON ethnicity there. Buttons
                    #                    switch to the 2nd/3rd most common; a selector
                    #                    highlights everywhere one ethnicity appears.
python review.py    # -> out/review.html sortable sheet of the needs_review entities
                    #                    + the rejected name-match candidates
```

The explorer ranks, per cell, the canonical groups whose territory covers the cell
centre — by **population** (territory area breaks ties). "Territory" prefers the
historical homeland (Murdock) → modern settlement (GeoEPR) → language-speaker area
(Glottography). Ranking metric and cell size (`STEP`) are easy to tune in `view.py`.

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
