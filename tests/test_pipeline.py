"""Offline unit tests for the core pipeline logic (no network / no downloads).

Covers the bits most likely to silently break: name normalisation, the
positional-alignment contract in finalize_groups (a real bug we fixed), exact-key
crosswalk links, and entity resolution (merge by shared code + needs_review).
"""
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from africa_ethno_fusion import crosswalk, entity, schema


def _make_groups(rows):
    """Build a canonical GROUP_COLUMNS GeoDataFrame from simple dicts."""
    frames = []
    for r in rows:
        df = pd.DataFrame([{
            "source_id": r["source_id"],
            "name_raw": r["name_raw"],
            "geom_kind": "point",
            "glottocode": r.get("glottocode"),
            "iso639_3": r.get("iso639_3"),
            "ea_society_id": r.get("ea_society_id"),
        }])
        frames.append(schema.finalize_groups(df, [r["geom"]], r["source"]))
    out = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs="EPSG:4326")


def test_norm_name():
    assert schema.norm_name("HAUSA") == "Hausa"
    assert schema.norm_name("  Zulu  ") == "Zulu"
    assert schema.norm_name("nan") is None
    assert schema.norm_name(None) is None


def test_finalize_groups_positional_alignment():
    # attribute frame carries a NON-default index; geometry is a plain list.
    # finalize_groups must align positionally (else geometries get NaN'd).
    df = pd.DataFrame(
        {"source_id": ["a", "b"], "name_raw": ["X", "Y"], "geom_kind": ["point", "point"]},
        index=[5, 9],
    )
    g = schema.finalize_groups(df, [Point(0, 0), Point(1, 1)], "test")
    assert list(g.columns) == schema.GROUP_COLUMNS
    assert g.geometry.isna().sum() == 0
    assert g.crs.to_epsg() == 4326
    assert g["record_id"].tolist() == ["test:a", "test:b"]
    assert g["name"].tolist() == ["X", "Y"]


def test_exact_glottocode_link():
    g = _make_groups([
        dict(source="dplace_ea", source_id="Aa1", name_raw="Foo",
             glottocode="abcd1234", geom=Point(0, 0)),
        dict(source="glottolog", source_id="abcd1234", name_raw="Foo",
             glottocode="abcd1234", geom=Point(0, 0)),
    ])
    links = crosswalk.build_links(g, fuzzy=False)
    hit = links[(links.method == "glottocode") & (links.key_value == "abcd1234")]
    assert len(hit) == 1
    assert hit.iloc[0]["confidence"] == 1.0


def test_resolve_merges_shared_code():
    g = _make_groups([
        dict(source="dplace_ea", source_id="Aa1", name_raw="Foo",
             glottocode="abcd1234", ea_society_id="Aa1", geom=Point(0, 0)),
        dict(source="glottolog", source_id="abcd1234", name_raw="Foo",
             glottocode="abcd1234", iso639_3="foo", geom=Point(0, 0)),
    ])
    links = crosswalk.build_links(g, fuzzy=False)
    res = entity.resolve_entities(g, links, traits=None)
    canon = res["canonical"]
    assert len(canon) == 1                       # two records -> one entity
    row = canon.iloc[0]
    assert row["n_sources"] == 2
    assert row["glottocode"] == "abcd1234"
    assert bool(row["needs_review"]) is False    # pure code merge -> no review


def test_resolve_keeps_distinct_groups_separate():
    g = _make_groups([
        dict(source="dplace_ea", source_id="Aa1", name_raw="Foo",
             glottocode="aaaa1111", geom=Point(0, 0)),
        dict(source="glottolog", source_id="bbbb2222", name_raw="Bar",
             glottocode="bbbb2222", geom=Point(10, 10)),
    ])
    links = crosswalk.build_links(g, fuzzy=False)
    res = entity.resolve_entities(g, links, traits=None)
    assert len(res["canonical"]) == 2            # different codes -> not merged


def test_unionfind_basic():
    uf = entity.UnionFind(["a", "b", "c"])
    uf.union("a", "b")
    assert uf.find("a") == uf.find("b")
    assert uf.find("a") != uf.find("c")
    assert uf.size("a") == 2
