"""Canonical schema for the fused African ethnographic dataset.

The fused product is a *star schema* of three tables:

  groups  -- GeoDataFrame (EPSG:4326). One row per ethnic-group / society record
             from one source. This is the spine: geometry + identity + the three
             crosswalk keys (iso639_3, glottocode, ea_society_id).
  traits  -- tidy/long DataFrame. Ethnographic attributes (mainly the Ethnographic
             Atlas) keyed by ea_society_id / glottocode.
  links   -- crosswalk DataFrame. How records in `groups` connect across sources,
             with the method used and a confidence score.

There is NO universal join key across all sources, so we keep every record as its
own row and express relationships through `links` rather than forcing a brittle
wide join. See README.md for the rationale.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd

# --- controlled vocabulary of sources -------------------------------------
SOURCES = {
    "murdock_map":    "Murdock 1959 ethnolinguistic map of Africa (Nunn digitization) -- territory polygons, pre/early-colonial (~1830-1900).",
    "greg":           "Geo-referencing of Ethnic Groups (Soviet Atlas Narodov Mira, 1964) -- territory polygons.",
    "geoepr":         "Geographic Ethnic Power Relations -- politically relevant groups, time-varying settlement areas (1946-).",
    "dplace_ea":      "D-PLACE Ethnographic Atlas -- society focal points + cultural trait data.",
    "glottolog":      "Glottolog languoids -- language reference points (the iso639_3 <-> glottocode bridge).",
    "joshua_project": "Joshua Project -- contemporary people-group points (population, religion).",
    "glottography":   "Glottography (Asher & Moseley 2007, 'Atlas of the World's Languages') -- open language-AREA polygons (open alternative to commercial WLMS), one per Glottolog language-level languoid, keyed on glottocode; traditional/historical layer by default.",
    # gated, local-file only:
    "afrobarometer":  "Afrobarometer geocoded -- self-reported ethnicity at locality level (gated).",
    "dhs":            "DHS -- ethnicity (V131) at displaced cluster centroids (gated).",
    "ipums":          "IPUMS International -- country-specific ethnicity at harmonized admin units (gated).",
}

# --- table 1: groups (the spine) -------------------------------------------
GROUP_COLUMNS = [
    "record_id",        # str  : "{source}:{source_id}", globally unique
    "source",           # str  : key of SOURCES
    "source_id",        # str  : native identifier within the source
    "name",             # str  : normalized display name
    "name_raw",         # str  : original name string from the source
    "name_alt",         # str  : JSON list of alternative spellings (or None)
    "geom_kind",        # str  : "territory_polygon" | "point"
    "lat",              # float: representative / centroid latitude
    "lon",              # float: representative / centroid longitude
    "country_iso3",     # str  : ISO 3166-1 alpha-3 where derivable (else None)
    "country_raw",      # str  : source-native country code/name
    "iso639_3",         # str  : ISO 639-3 language code (crosswalk key) or None
    "glottocode",       # str  : Glottolog code (crosswalk key) or None
    "ea_society_id",    # str  : Ethnographic Atlas OWC code, e.g. "Aa1" / "Ca34" (crosswalk key) or None
    "period_from",      # int  : start year the record represents
    "period_to",        # int  : end year the record represents
    "population",        # float: population estimate where available (Joshua Project)
    "area_sqkm",        # float: territory area (equal-area) for polygons
    "settlement_type",  # str  : e.g. GeoEPR settlement pattern, EA settlement type
    "primary_religion", # str  : where available (Joshua Project)
    "source_attrs",     # str  : JSON blob of source-specific extra fields
    "geometry",         # shapely geometry, EPSG:4326
]

# --- table 2: traits (tidy/long) -------------------------------------------
TRAIT_COLUMNS = [
    "ea_society_id",    # str  : link to groups.ea_society_id
    "glottocode",       # str  : link to groups.glottocode
    "var_id",           # str  : e.g. "EA033"
    "var_title",        # str  : human title of the variable
    "category",         # str  : e.g. "Politics", "Subsistence"
    "code",             # str  : coded value
    "value_label",      # str  : decoded human label of the code
    "value_num",        # float: numeric value (for ordinal/continuous vars)
    "focal_year",       # int  : the year the coding pertains to
    "source",           # str  : "dplace_ea"
]

# --- table 3: links (crosswalk) --------------------------------------------
LINK_COLUMNS = [
    "record_id_a",      # str
    "record_id_b",      # str
    "a_source",         # str
    "b_source",         # str
    "method",           # str  : "ea_society_id" | "glottocode" | "iso639_3" | "fuzzy_name"
    "key_value",        # str  : the shared key (or the matched name)
    "confidence",       # float: 1.0 for exact-code joins, score/100 for fuzzy
]


# --- helpers ----------------------------------------------------------------
def norm_name(x) -> str | None:
    """Normalize a group name: strip, collapse, title-case ALL-CAPS labels."""
    if x is None:
        return None
    try:
        if isinstance(x, float) and pd.isna(x):
            return None
    except TypeError:
        pass
    s = " ".join(str(x).split()).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    return s.title() if s.isupper() else s


def jsonify_attrs(df: pd.DataFrame, cols) -> list[str]:
    """Serialize selected columns of `df` into one JSON string per row."""
    cols = [c for c in cols if c in df.columns]
    out = []
    for rec in df[cols].to_dict("records"):
        clean = {}
        for k, v in rec.items():
            if v is None:
                continue
            try:
                if isinstance(v, float) and pd.isna(v):
                    continue
            except TypeError:
                pass
            clean[k] = v
        out.append(json.dumps(clean, ensure_ascii=False, default=str))
    return out


def finalize_groups(df: pd.DataFrame, geometry, source: str) -> gpd.GeoDataFrame:
    """Coerce a per-source frame to the canonical GROUP_COLUMNS GeoDataFrame.

    `df` and `geometry` must be in the same ROW ORDER. We drop both indexes and
    align positionally, because attribute columns often inherit the source's
    (non-contiguous) index while geometry is freshly built with a RangeIndex --
    letting the GeoDataFrame constructor align by label would silently NaN out
    the mismatched rows.
    """
    df = df.reset_index(drop=True).copy()
    geom = gpd.GeoSeries(list(geometry), crs="EPSG:4326")  # force positional RangeIndex
    df["source"] = source
    if "name" not in df.columns:
        df["name"] = df["name_raw"].map(norm_name)
    df["record_id"] = df["source"].astype(str) + ":" + df["source_id"].astype(str)
    for col in GROUP_COLUMNS:
        if col != "geometry" and col not in df.columns:
            df[col] = None
    gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")
    return gdf[GROUP_COLUMNS]


def empty_groups() -> gpd.GeoDataFrame:
    cols = {c: pd.Series(dtype="object") for c in GROUP_COLUMNS if c != "geometry"}
    gdf = gpd.GeoDataFrame(cols, geometry=gpd.GeoSeries([], dtype="geometry"), crs="EPSG:4326")
    return gdf[GROUP_COLUMNS]
