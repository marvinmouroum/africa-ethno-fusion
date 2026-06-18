"""Glottography (Asher & Moseley 2007) CLDF access helpers.

The `Glottography/asher2007world` repo (Zenodo record 15287258) ships a CLDF
StructureDataset whose *media* are GeoJSON FeatureCollections. The repo holds
two parallel datasets:

  cldf/traditional/   -- "Traditional speaker areas derived from Asher & Moseley
                          2007 'Atlas of the World's Languages'" (the historical
                          reconstruction; the ethnographic-homeland view).
  cldf/contemporary/  -- the same areas reprojected to contemporary extents.

For each dataset the cleanest, most robust programmatic surface is the
`languages.geojson` media file: ONE (Multi)Polygon per Glottolog language-level
languoid, with properties:

    cldf:languageReference  -> glottocode  (our critical join key; 100% populated)
    title                   -> languoid name
    family                  -> language-family name (extra)

We default to the *traditional* layer because it lines up with the other
historical homeland polygon sources (Murdock 1959, GREG 1964) already in the
fusion. `languages.csv` (ID == glottocode) carries no ISO codes (empty in the
release) but does carry the source `Maps` reference and `Family`, which we fold
into `source_attrs` as extras. ISO639-3 is intentionally left to the crosswalk:
the fusion's Glottolog source already bridges glottocode <-> iso639_3, and these
language-areas link in automatically on the glottocode.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

# Raw GitHub URLs are stable and match how the other GitHub-hosted sources are
# wired (Murdock mirror, Glottolog CLDF). The Zenodo record (15287258) is the
# archival fallback, but the repo's main branch is the live, citeable surface.
_REPO_RAW = "https://raw.githubusercontent.com/Glottography/asher2007world/main/cldf"

# layer -> (languages.geojson url, languages.csv url)
LAYERS = {
    "traditional": (
        f"{_REPO_RAW}/traditional/languages.geojson",
        f"{_REPO_RAW}/traditional/languages.csv",
    ),
    "contemporary": (
        f"{_REPO_RAW}/contemporary/languages.geojson",
        f"{_REPO_RAW}/contemporary/languages.csv",
    ),
}

# Nominal period the Asher & Moseley 2007 traditional reconstruction depicts.
# (Atlas of the World's Languages, 2nd ed. 2007 -- "traditional" pre-modern
#  speaker areas; we tag a coarse 20th-c. nominal window, mirroring how the
#  other homeland sources carry nominal period bounds.)
PERIOD_FROM = 1900
PERIOD_TO = 2007

GEOJSON_GLOTTOCODE_PROP = "cldf:languageReference"


def language_areas(layer: str, geojson_path, csv_path=None) -> gpd.GeoDataFrame:
    """Read a Glottography languages.geojson into a GeoDataFrame with normalized
    columns: glottocode, name, family, maps (source-map ref), plus geometry.

    `geojson_path` / `csv_path` are local files (already cached by the caller).
    `csv_path` is optional and only used to enrich the `maps` source reference.
    """
    if layer not in LAYERS:
        raise ValueError(f"unknown Glottography layer {layer!r}; use one of {list(LAYERS)}")

    g = gpd.read_file(geojson_path)
    if g.crs is None:
        g.set_crs(4326, inplace=True)
    else:
        g = g.to_crs(4326)

    glotto_col = GEOJSON_GLOTTOCODE_PROP if GEOJSON_GLOTTOCODE_PROP in g.columns else None
    if glotto_col is None:
        # Defensive: some GDAL versions flatten the namespaced key.
        for cand in ("cldf_languageReference", "languageReference", "Language_ID"):
            if cand in g.columns:
                glotto_col = cand
                break
    if glotto_col is None:
        raise RuntimeError(
            "Glottography languages.geojson missing the language-reference / "
            f"glottocode property (looked for {GEOJSON_GLOTTOCODE_PROP!r}); "
            f"got columns {list(g.columns)}"
        )

    g = g.rename(columns={glotto_col: "glottocode"})
    g["glottocode"] = g["glottocode"].astype("string").str.strip()
    g = g[g["glottocode"].notna() & (g["glottocode"].str.len() > 0)].copy()

    g["name"] = g["title"] if "title" in g.columns else g["glottocode"]
    g["family"] = g["family"] if "family" in g.columns else None

    # Optional enrichment: the source-map reference from languages.csv (ID==glottocode).
    g["maps"] = None
    if csv_path is not None:
        try:
            meta = pd.read_csv(csv_path, dtype=str)
            id_col = "ID" if "ID" in meta.columns else (
                "Glottocode" if "Glottocode" in meta.columns else None
            )
            if id_col is not None and "Maps" in meta.columns:
                maps_by_glotto = (
                    meta.dropna(subset=[id_col]).set_index(id_col)["Maps"].to_dict()
                )
                g["maps"] = g["glottocode"].map(maps_by_glotto)
        except Exception:
            pass  # enrichment is best-effort; the geojson is authoritative

    g = g[~g.geometry.isna() & ~g.geometry.is_empty].copy()
    return g
