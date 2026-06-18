"""Orchestrate the loaders into the fused 3-table star schema and export it."""
from __future__ import annotations

import pathlib
import warnings

import geopandas as gpd
import pandas as pd

from . import crosswalk, entity, schema, sources

# Open, auto-downloadable sources built by default.
DEFAULT_SOURCES = ["murdock_map", "greg", "geoepr", "dplace_ea", "glottolog"]


def build(
    source_list=None,
    *,
    african_only: bool = True,
    fuzzy_crosswalk: bool = True,
    resolve: bool = True,
    jp_api_key: str | None = None,
    jp_csv: str | None = None,
) -> dict:
    """Build the fused dataset.

    Returns {"groups", "traits", "links"} and, when resolve=True, also
    {"canonical", "review_candidates"} -- the unified one-row-per-entity layer.
    """
    source_list = source_list or DEFAULT_SOURCES
    group_frames: list[gpd.GeoDataFrame] = []
    traits = pd.DataFrame(columns=schema.TRAIT_COLUMNS)

    for src in source_list:
        try:
            if src == "murdock_map":
                group_frames.append(sources.load_murdock())
            elif src == "greg":
                group_frames.append(sources.load_greg())
            elif src == "geoepr":
                group_frames.append(sources.load_geoepr())
            elif src == "glottolog":
                group_frames.append(sources.load_glottolog())
            elif src == "dplace_ea":
                g, traits = sources.load_dplace_ea(african_only=african_only)
                group_frames.append(g)
            elif src == "joshua_project":
                g = sources.load_joshua_project(api_key=jp_api_key, csv_path=jp_csv)
                if g is not None:
                    group_frames.append(g)
            else:
                warnings.warn(f"source {src!r} has no auto-loader (gated?) -- skipping.")
            print(f"  [ok] {src}: {len(group_frames[-1]) if group_frames else 0} records so far")
        except Exception as exc:
            warnings.warn(f"source {src!r} failed to load: {exc}")

    if group_frames:
        groups = pd.concat(group_frames, ignore_index=True)
        groups = gpd.GeoDataFrame(groups, geometry="geometry", crs="EPSG:4326")
    else:
        groups = schema.empty_groups()

    links = crosswalk.build_links(groups, fuzzy=fuzzy_crosswalk)
    out = {"groups": groups, "traits": traits, "links": links}

    if resolve:
        res = entity.resolve_entities(groups, links, traits)
        out["groups"] = res["groups"]          # now carries canonical_id
        out["canonical"] = res["canonical"]
        out["review_candidates"] = res["review_candidates"]
    return out


def export(frames: dict, outdir: str, fmt: str = "all") -> None:
    """Write the fused tables. fmt: 'parquet' | 'gpkg' | 'csv' | 'all'."""
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    groups = frames["groups"]
    traits = frames["traits"]
    links = frames["links"]
    canonical = frames.get("canonical")
    review = frames.get("review_candidates")

    if fmt in ("parquet", "all"):
        # GeoParquet preserves geometry; tabular frames as plain parquet.
        groups.to_parquet(out / "groups.parquet")
        traits.to_parquet(out / "traits.parquet")
        links.to_parquet(out / "links.parquet")
        if canonical is not None:
            canonical.to_parquet(out / "canonical.parquet")
            review.to_parquet(out / "review_candidates.parquet")
    if fmt in ("gpkg", "all"):
        # One GeoPackage with the spine + resolved entities as spatial layers.
        groups.to_file(out / "africa_ethno.gpkg", layer="groups", driver="GPKG")
        if canonical is not None:
            canonical.to_file(out / "africa_ethno.gpkg", layer="canonical", driver="GPKG")
    if fmt in ("csv", "all"):
        # CSV with geometry as WKT for non-GIS consumers.
        # .to_wkt() returns a plain DataFrame (geometry serialized), no geom-dtype warning.
        groups.to_wkt().to_csv(out / "groups.csv", index=False)
        traits.to_csv(out / "traits.csv", index=False)
        links.to_csv(out / "links.csv", index=False)
        if canonical is not None:
            canonical.to_wkt().to_csv(out / "canonical.csv", index=False)
            review.to_csv(out / "review_candidates.csv", index=False)

    print(f"Exported to {out.resolve()}")
    print(f"  groups   : {len(groups):>6} source records  ({groups['source'].nunique()} sources)")
    print(f"  traits   : {len(traits):>6} rows")
    print(f"  links    : {len(links):>6} crosswalk edges")
    if canonical is not None:
        multi = (canonical["n_sources"] > 1).sum()
        flagged = int(canonical["needs_review"].sum())
        print(f"  canonical: {len(canonical):>6} resolved entities "
              f"({multi} multi-source, {flagged} need review)")
        print(f"  review   : {len(review):>6} fuzzy candidates flagged")
