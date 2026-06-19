---
title: 'africa-ethno-fusion: a reproducible pipeline fusing open datasets on African ethnic groups into a map-ready spatial dataset'
tags:
  - Python
  - Africa
  - ethnic groups
  - ethnolinguistic geography
  - data integration
  - entity resolution
  - GeoPandas
authors:
  - name: Marvin Mouroum
    affiliation: 1
    # TODO before submission: add orcid: 0000-0000-0000-0000
affiliations:
  - name: Independent researcher
    index: 1
date: 19 June 2026
bibliography: paper.bib
---

# Summary

Research on African human geography draws on several open datasets that each map
*which ethnic groups live where* from a different angle: ethnic homeland polygons
[@murdock1959africa; @weidmann2010greg], time-varying settlement areas of
politically relevant groups [@vogt2015epr; @wucherpfennig2011geoepr], coded cultural
traits [@kirby2016dplace; @murdock1967ea], language references [@glottolog], language
areas [@asher2007atlas], and contemporary demography [@joshuaproject]. These datasets
do not share a common key — they are joined through a chain of partial identifiers
(group names, ISO 639-3 codes, Glottocodes, Ethnographic Atlas society codes) — so
combining them is a recurring, error-prone, manual task.

`africa-ethno-fusion` is a reproducible Python pipeline that downloads these sources,
normalises them into a GeoPandas *star schema* (`groups`, `traits`, `links`), and
resolves the per-source records into a **canonical, one-row-per-group layer** through
connected-components over a crosswalk. Each canonical entity carries a representative
territory geometry (historical homeland → modern settlement → language area), cultural
traits, language family, population, and the provenance of every contributing source,
with a per-link `merge_confidence` and a `needs_review` flag. The tool also produces an
auditable crosswalk and a self-contained interactive web map that partitions Africa
into bordered territory polygons coloured by the dominant ethnicity, with toggles for
the 2nd/3rd most common group and a per-ethnicity locator.

# Statement of need

Teams that want to ask cross-cutting questions — for example, *does pre-colonial
political complexity predict modern conflict or development?* — must first reconcile
incompatible ethnic-group datasets. This integration work is repeatedly redone and
rarely shared in a transparent, reproducible form. `africa-ethno-fusion` provides:
(1) a one-command rebuild from primary sources; (2) a fused, map-ready spatial layer
that pairs territory with traits, language, and demography; (3) an *auditable* crosswalk
that records how each cross-source link was made and how confident it is; and (4) an
interactive map for exploration and teaching. It lowers the barrier for development
economists, conflict and political scientists, cross-cultural anthropologists,
linguists, demographers, and digital-humanities and GIS users.

# State of the field

The closest prior work is **LEDA** [@mullercrepon2022leda], which solves the
*group-identity reconciliation* problem: it links 8,100+ ethnic categories across 11
datasets via the Ethnologue linguistic tree and returns dyadic link tables. LEDA is the
reference standard for *linking*, and is intentionally not reimplemented here.
`africa-ethno-fusion` is **complementary**: rather than producing category-to-category
links, it produces a fused, *spatial*, trait-enriched product — one geometry per group
plus cultural, linguistic, and demographic attributes — and a public map. LEDA does not
attach cultural traits, dissolve sources into a single per-group territory, add
population/religion, use Glottolog/Glottography, or provide a map; conversely, LEDA's
curated linguistic crosswalk is a more rigorous linkage backbone than the name- and
code-matching used here, and integrating it is identified as future work (LEDA is
GPL-3; this project is MIT and keeps a pure-Python runtime). Adjacent efforts cover
single seams: the Database of Global Cultural Evolution links Glottolog to the
Ethnographic Atlas, and Glottography [@asher2007atlas] provides language-area polygons.
To our knowledge no existing open tool packages territory, traits, language area, and
demography into one reproducible, map-ready spatial product.

# Functionality

- **Loaders** for seven open sources, each normalised to a canonical schema.
- **Crosswalk** linking records by exact keys (Ethnographic Atlas society code,
  Glottocode, ISO 639-3) and, for the code-less polygon sources, by reciprocal-best
  fuzzy name matching with a code-conflict guard.
- **Entity resolution** via union-find, producing the canonical layer with confidence
  and review flags.
- **Exports** to GeoParquet, GeoPackage, and CSV.
- **Visualisation**: an interactive dominance map and an HTML review sheet.

The package is built on GeoPandas [@jordahl2020geopandas]. Gated survey/census sources
(Afrobarometer, DHS, IPUMS) are supported via local-file loaders.

# Acknowledgements

This tool redistributes only code and an ID-level crosswalk; the merged corpus is
rebuilt from primary sources, several of which are non-commercial (see `PROVENANCE.md`).
We thank the maintainers of all upstream datasets.

# References
