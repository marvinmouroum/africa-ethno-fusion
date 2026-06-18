"""Per-source loaders. Each returns canonical GROUP_COLUMNS GeoDataFrame(s).

All field names / URLs were verified against the actual source files
(GeoJSON properties, shapefile .dbf headers, CLDF column headers) in June 2026.
Where a source is gated (Afrobarometer / DHS / IPUMS) we expose a local-file
loader instead of an auto-downloader.
"""
from __future__ import annotations

import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from . import schema
from .io_utils import cached_download, clip_africa, clip_africa_landmass

# ---------------------------------------------------------------------------
# 1. Murdock 1959 map (Nunn digitization)  -- territory polygons
#    GitHub mirror (sboysel/murdock) avoids the bot-challenge on Nunn's host.
#    Traits V1..V99 are already merged in; we take identity + the EA "CODE"
#    bridge and leave canonical traits to D-PLACE (cleaner + labelled).
# ---------------------------------------------------------------------------
MURDOCK_URL = (
    "https://raw.githubusercontent.com/sboysel/murdock/master/"
    "data-raw/Murdock_EA_2011_vkZ.geojson"
)


def load_murdock() -> gpd.GeoDataFrame:
    path = cached_download(MURDOCK_URL, "murdock_ea.geojson")
    g = gpd.read_file(path)
    if g.crs is None:
        g.set_crs(4326, inplace=True)
    g = g.to_crs(4326)

    # The EA society code is only valid where CodeType marks it "EA".
    code_type = g.get("CodeType", pd.Series([None] * len(g))).astype(str).str.replace(
        r"\s+", "", regex=True
    )
    ea_code = g["CODE"].astype(str).str.strip()
    ea_code = ea_code.where(code_type.str.contains("EA", na=False))

    df = pd.DataFrame(
        {
            "source_id": g["NAME"].astype(str).str.strip() + "#" + g.index.astype(str),
            "name_raw": g["NAME"],
            "geom_kind": "territory_polygon",
            "lat": pd.to_numeric(g.get("LAT"), errors="coerce"),
            "lon": pd.to_numeric(g.get("LON"), errors="coerce"),
            "ea_society_id": ea_code,
            "period_from": 1830,   # nominal: Murdock reconstructs pre/early-colonial homelands
            "period_to": 1900,
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    df["area_sqkm"] = g.to_crs(6933).area / 1e6  # EPSG:6933 = equal-area
    df["source_attrs"] = schema.jsonify_attrs(
        g, ["TRIBE_CODE", "CultureGrp", "CodeType", "NOTES", "Name_Displ"]
    )
    return clip_africa(schema.finalize_groups(df, g.geometry, "murdock_map"))


# ---------------------------------------------------------------------------
# 2. GREG (Atlas Narodov Mira, 1964)  -- territory polygons.
#    Up to 3 groups share a polygon -> emit one row per present group.
# ---------------------------------------------------------------------------
GREG_URL = "https://icr.ethz.ch/data/greg/GREG.zip"


def load_greg() -> gpd.GeoDataFrame:
    path = cached_download(GREG_URL, "GREG.zip")
    g = gpd.read_file(f"zip://{path}")
    g = g.set_crs(4326, allow_override=True).to_crs(4326)
    area_sqkm = pd.to_numeric(g.get("AREA"), errors="coerce") / 1e6  # AREA is m^2

    parts = []
    for i in (1, 2, 3):
        gid, short, long_, anm = f"G{i}ID", f"G{i}SHORTNAM", f"G{i}LONGNAM", f"GROUP{i}"
        if gid not in g.columns:
            continue
        mask = pd.to_numeric(g[gid], errors="coerce").fillna(0) > 0
        sub = g[mask]
        if sub.empty:
            continue
        df = pd.DataFrame(
            {
                "source_id": sub["FeatureID"].astype("Int64").astype(str) + "." + str(i),
                "name_raw": sub[short],
                "geom_kind": "territory_polygon",
                "country_raw": sub.get("FIPS_CNTRY"),
                "period_from": 1964,
                "period_to": 1964,
                "area_sqkm": area_sqkm[mask].values,
            }
        )
        df["name"] = df["name_raw"].map(schema.norm_name)
        df["name_alt"] = sub[long_].astype(str).where(sub[long_].notna()).values
        df["source_attrs"] = schema.jsonify_attrs(
            sub.assign(greg_gid=sub[gid], anm_code=sub[anm]),
            ["greg_gid", "anm_code", "COW", "FIPS_CNTRY", "FeatureID"],
        )
        parts.append(schema.finalize_groups(df, sub.geometry, "greg"))
    out = pd.concat(parts, ignore_index=True) if parts else schema.empty_groups()
    out = gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")
    return clip_africa_landmass(out)  # GREG is global -> clip to African landmass


# ---------------------------------------------------------------------------
# 3. GeoEPR 2021  -- time-varying settlement areas of politically relevant groups.
# ---------------------------------------------------------------------------
GEOEPR_GEOJSON = "https://icr.ethz.ch/data/epr/geoepr/GeoEPR-2021.geojson"
GEOEPR_ZIP = "https://icr.ethz.ch/data/epr/geoepr/GeoEPR-2021.zip"


def load_geoepr() -> gpd.GeoDataFrame:
    try:
        path = cached_download(GEOEPR_GEOJSON, "GeoEPR-2021.geojson")
        g = gpd.read_file(path)
    except Exception as exc:  # fall back to the zipped shapefile
        warnings.warn(f"GeoEPR geojson failed ({exc}); trying shapefile zip.")
        path = cached_download(GEOEPR_ZIP, "GeoEPR-2021.zip")
        g = gpd.read_file(f"zip://{path}")
    g = g.set_crs(4326, allow_override=True).to_crs(4326)
    g = g[~g.geometry.isna() & ~g.geometry.is_empty].copy()

    yr_from = pd.to_numeric(g.get("from"), errors="coerce").astype("Int64")
    yr_to = pd.to_numeric(g.get("to"), errors="coerce").astype("Int64")
    gwgid = g.get("gwgroupid").astype("Int64").astype(str)

    df = pd.DataFrame(
        {
            "source_id": gwgid + "_" + yr_from.astype(str) + "-" + yr_to.astype(str),
            "name_raw": g["group"],
            "geom_kind": "territory_polygon",
            "country_raw": g.get("statename"),
            "period_from": yr_from,
            "period_to": yr_to,
            "area_sqkm": pd.to_numeric(g.get("sqkm"), errors="coerce"),
            "settlement_type": g.get("type"),
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    df["source_attrs"] = schema.jsonify_attrs(
        g, ["gwid", "groupid", "gwgroupid", "umbrella", "type"]
    )
    # GeoEPR is global -> clip to the African landmass
    return clip_africa_landmass(schema.finalize_groups(df, g.geometry, "geoepr"))


# ---------------------------------------------------------------------------
# 4. D-PLACE Ethnographic Atlas  -- society focal points + trait long table.
#    Returns (groups_gdf, traits_df). African societies = EA id prefix "A".
# ---------------------------------------------------------------------------
EA_BASE = "https://raw.githubusercontent.com/D-PLACE/dplace-data/master/datasets/EA"


def load_dplace_ea(african_only: bool = True):
    soc = pd.read_csv(f"{EA_BASE}/societies.csv")
    var = pd.read_csv(f"{EA_BASE}/variables.csv")
    cod = pd.read_csv(f"{EA_BASE}/codes.csv")
    dat = pd.read_csv(f"{EA_BASE}/data.csv")

    # --- groups (points) for ALL societies; filter to Africa GEOGRAPHICALLY ---
    # (NOT by id prefix: Murdock codes the Horn / N. Africa / Sahel under "C",
    # so an "A"-prefix filter would drop Amhara=Ca7, Hausa, Beja, etc.)
    lat = pd.to_numeric(soc["Lat"], errors="coerce")
    lon = pd.to_numeric(soc["Long"], errors="coerce")
    geometry = [Point(xy) if pd.notna(xy[0]) and pd.notna(xy[1]) else None
                for xy in zip(lon, lat)]
    year = pd.to_numeric(soc.get("main_focal_year"), errors="coerce").astype("Int64")
    df = pd.DataFrame(
        {
            "source_id": soc["id"],
            "name_raw": soc["pref_name_for_society"],
            "geom_kind": "point",
            "lat": lat.values,
            "lon": lon.values,
            "glottocode": soc.get("glottocode"),
            "ea_society_id": soc["id"],
            "period_from": year,
            "period_to": year,
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    df["name_alt"] = soc.get("alt_names_by_society")
    df["source_attrs"] = schema.jsonify_attrs(soc, ["xd_id", "HRAF_name_ID", "HRAF_link"])
    groups = schema.finalize_groups(df, gpd.GeoSeries(geometry, crs=4326), "dplace_ea")
    if african_only:
        groups = clip_africa_landmass(groups)
    soc_ids = set(groups["ea_society_id"])

    # --- traits (long) ---
    t = dat[dat["soc_id"].isin(soc_ids)].copy()
    t = t.merge(var[["id", "title", "category"]], left_on="var_id", right_on="id", how="left")
    t = t.merge(cod[["var_id", "code", "description"]], on=["var_id", "code"], how="left")
    gloss = soc.set_index("id")["glottocode"]
    traits = pd.DataFrame(
        {
            "ea_society_id": t["soc_id"],
            "glottocode": t["soc_id"].map(gloss),
            "var_id": t["var_id"],
            "var_title": t["title"],
            "category": t["category"],
            "code": t["code"],
            "value_label": t["description"],
            "value_num": pd.to_numeric(t["code"], errors="coerce"),
            "focal_year": pd.to_numeric(t.get("year"), errors="coerce").astype("Int64"),
            "source": "dplace_ea",
        }
    )[schema.TRAIT_COLUMNS]
    return groups, traits


# ---------------------------------------------------------------------------
# 5. Glottolog  -- language reference points (the iso639_3 <-> glottocode bridge).
# ---------------------------------------------------------------------------
GLOTTOLOG_URL = (
    "https://raw.githubusercontent.com/glottolog/glottolog-cldf/master/cldf/languages.csv"
)


def load_glottolog(macroarea: str = "Africa", level: str = "language") -> gpd.GeoDataFrame:
    df0 = pd.read_csv(GLOTTOLOG_URL)
    if macroarea:
        df0 = df0[df0["Macroarea"] == macroarea]
    if level:
        df0 = df0[df0["Level"] == level]
    df0 = df0[df0["Latitude"].notna() & df0["Longitude"].notna()].copy()
    geometry = gpd.GeoSeries(
        [Point(x, y) for x, y in zip(df0["Longitude"], df0["Latitude"])], crs=4326
    )
    df = pd.DataFrame(
        {
            "source_id": df0["Glottocode"],
            "name_raw": df0["Name"],
            "geom_kind": "point",
            "lat": df0["Latitude"].values,
            "lon": df0["Longitude"].values,
            "iso639_3": df0.get("ISO639P3code"),
            "glottocode": df0["Glottocode"],
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    df["source_attrs"] = schema.jsonify_attrs(df0, ["Family_ID", "Macroarea", "Countries"])
    return schema.finalize_groups(df, geometry, "glottolog")


# ---------------------------------------------------------------------------
# 6. Joshua Project (OPTIONAL)  -- contemporary people-group points.
#    API needs a free key (api_key query param). Field names per JP docs;
#    ROL3 == ISO 639-3. Best-effort: returns None on any failure.
# ---------------------------------------------------------------------------
JP_API = "https://api.joshuaproject.net/v1/people_groups.json"


def load_joshua_project(api_key: str | None = None, csv_path: str | None = None):
    if csv_path:
        df0 = pd.read_csv(csv_path)
        return _jp_frame(df0)
    if not api_key:
        warnings.warn("Joshua Project skipped: no api_key and no csv_path provided.")
        return None
    try:
        import requests

        from .io_utils import USER_AGENT

        # The server-side continent filter is unreliable at large page sizes,
        # so we page through everything and filter to Africa client-side.
        rows, page, limit = [], 1, 1000
        while True:
            r = requests.get(
                JP_API,
                params={"api_key": api_key, "limit": limit, "page": page},
                headers={"User-Agent": USER_AGENT},
                timeout=180,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < limit:
                break
            page += 1
        df0 = pd.DataFrame(rows)
        # keep Africa only (ROG2 == "AFR", fall back to Continent)
        if "ROG2" in df0.columns:
            df0 = df0[df0["ROG2"] == "AFR"]
        elif "Continent" in df0.columns:
            df0 = df0[df0["Continent"] == "Africa"]
        return _jp_frame(df0)
    except Exception as exc:
        warnings.warn(f"Joshua Project API fetch failed: {exc}")
        return None


def _jp_frame(df0: pd.DataFrame) -> gpd.GeoDataFrame:
    lat = pd.to_numeric(df0.get("Latitude"), errors="coerce")
    lon = pd.to_numeric(df0.get("Longitude"), errors="coerce")
    geometry = gpd.GeoSeries(
        [Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(lon, lat)],
        crs=4326,
    )
    name_col = "PeopNameInCountry" if "PeopNameInCountry" in df0 else "PeopNameAcrossCountries"
    df = pd.DataFrame(
        {
            "source_id": df0.get("PeopleID3").astype(str) + "-" + df0.get("ROG3").astype(str),
            "name_raw": df0.get(name_col),
            "geom_kind": "point",
            "lat": lat.values,
            "lon": lon.values,
            "country_iso3": df0.get("ISO3"),
            "country_raw": df0.get("ROG3"),
            "iso639_3": df0.get("ROL3"),
            "population": pd.to_numeric(df0.get("Population"), errors="coerce"),
            "primary_religion": df0.get("PrimaryReligion"),
            "period_from": 2020,
            "period_to": 2026,
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    df["source_attrs"] = schema.jsonify_attrs(
        df0, ["PeopleID3", "PeopleID2", "ROL3", "JPScale", "LeastReached"]
    )
    return schema.finalize_groups(df, geometry, "joshua_project")


# ---------------------------------------------------------------------------
# 7. Gated sources (Afrobarometer / DHS / IPUMS) -- LOCAL FILE loaders only.
#    These cannot be auto-downloaded (registration / approval required).
#    You pre-download, then point these at the file + tell us which columns
#    hold ethnicity and coordinates.
# ---------------------------------------------------------------------------
def load_geocoded_survey_local(
    path: str,
    source: str,
    *,
    ethnicity_col: str,
    lat_col: str,
    lon_col: str,
    country_col: str | None = None,
    year: int | None = None,
    id_col: str | None = None,
) -> gpd.GeoDataFrame:
    """Generic loader for a user-supplied geocoded survey/census file.

    Reads .csv / .dta (Stata) / .sav (SPSS, needs pyreadstat). Each respondent
    (or cluster) becomes a `point` record tagged with its self-reported ethnicity.
    """
    if source not in {"afrobarometer", "dhs", "ipums"}:
        raise ValueError(f"source must be one of afrobarometer/dhs/ipums, got {source!r}")
    if path.endswith(".csv"):
        df0 = pd.read_csv(path)
    elif path.endswith(".dta"):
        df0 = pd.read_stata(path, convert_categoricals=True)
    elif path.endswith(".sav"):
        import pyreadstat  # type: ignore

        df0, _ = pyreadstat.read_sav(path)
    else:
        raise ValueError("Unsupported file type; use .csv/.dta/.sav")

    lat = pd.to_numeric(df0[lat_col], errors="coerce")
    lon = pd.to_numeric(df0[lon_col], errors="coerce")
    geometry = gpd.GeoSeries(
        [Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(lon, lat)],
        crs=4326,
    )
    ids = df0[id_col].astype(str) if id_col else pd.Series(df0.index.astype(str))
    df = pd.DataFrame(
        {
            "source_id": ids.values,
            "name_raw": df0[ethnicity_col],
            "geom_kind": "point",
            "lat": lat.values,
            "lon": lon.values,
            "country_raw": df0[country_col] if country_col else None,
            "period_from": year,
            "period_to": year,
        }
    )
    df["name"] = df["name_raw"].map(schema.norm_name)
    return schema.finalize_groups(df, geometry, source)
