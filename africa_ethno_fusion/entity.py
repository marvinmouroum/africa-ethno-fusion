"""Entity resolution: collapse per-source records into canonical ethnic-group
entities -- the "one data source" layer.

Strategy (the "balanced" policy):
  1. Union-find over all EXACT-code links (ea_society_id / glottocode / iso639_3).
     Transitivity is trusted here -- shared codes are authoritative.
  2. Fold in fuzzy name matches between the code-less polygon sources
     (murdock_map / greg / geoepr) only when they are RECIPROCAL best matches
     with score >= 0.92, AND at least one endpoint is still a singleton.
     The singleton rule means a fuzzy edge can ATTACH a lone territory to an
     existing entity but can never FUSE two already-built entities -> no
     transitive chaining / giant-component blow-up.
  3. Everything weaker (below threshold, non-reciprocal, or a rejected
     would-fuse-two-entities edge) is emitted to `review_candidates` instead.

Outputs:
  canonical        -- GeoDataFrame, one row per resolved entity
  review_candidates -- DataFrame of fuzzy pairs that were NOT auto-merged
  groups           -- the input groups with a `canonical_id` column added
"""
from __future__ import annotations

import itertools
import json
import warnings

import geopandas as gpd
import pandas as pd
from shapely import wkt as shapely_wkt

EXACT_METHODS = ["ea_society_id", "glottocode", "iso639_3"]
POLYGON_SOURCES = ["murdock_map", "greg", "geoepr"]
# sources matched by NAME. The code-less polygons (murdock/greg/geoepr) carry no
# language codes and split off into a "territory cluster" whenever the EA-code
# bridge is missing; D-PLACE/Glottolog/Joshua Project carry codes. Including the
# coded sources here lets a code-less territory ATTACH (by ethnonym) to the coded
# entity for the same group -- closing the Hausa / Beja split.
#
# Glottolog labels are LANGUAGE names ("Amharic" not the ethnonym "Amhara") and
# are noisier; it is included because empirically it does not over-merge here
# (the code-conflict guard + literal-first ordering keep it precise), and it
# supplies the unambiguous full-literal bridge for cases like Beja where Joshua
# Project only carries qualified names.
NAME_MATCH_SOURCES = ["murdock_map", "greg", "geoepr", "dplace_ea", "glottolog", "joshua_project"]
# sources that carry authoritative language/society codes; their NAMES are only
# trusted as an exact-name bridge when the qualifier-stripped key is unambiguous.
CODED_SOURCES = ["dplace_ea", "glottolog", "joshua_project"]
# preferred_name is taken from the highest-priority source present in a cluster
NAME_PRIORITY = ["dplace_ea", "glottolog", "murdock_map", "joshua_project", "geoepr", "greg"]


def _match_key(name) -> str | None:
    """Match-only normalization of a group name (the STORED name is never
    changed -- this key is used solely to decide whether two names match).

    Joshua Project people-group labels carry a trailing qualifier after a comma
    ("Hausa, Yerwa", "Beja, Amarar", "Amhara, Wollo"); the ethnonym is the head
    before the first comma. We lower-case and take that head so "Hausa, X" keys
    to the same value as the bare "Hausa" territory polygon. Parenthetical
    qualifiers ("Fur (Sudan)") are stripped too. The full string is kept when
    there is no comma so multi-word ethnonyms ("Hausa-Fulani ...") are untouched.
    """
    if not isinstance(name, str):
        return None
    s = name.split("(", 1)[0]          # drop "(Sudan)"-style parentheticals
    s = s.split(",", 1)[0]             # head before the first comma qualifier
    s = " ".join(s.split()).strip().lower()
    return s or None


# key Ethnographic Atlas traits surfaced onto the canonical row
TRAIT_VARS = {
    "trait_subsistence": "EA042",
    "trait_settlement": "EA030",
    "trait_politics": "EA033",
    "trait_descent": "EA043",
    "trait_class": "EA066",
}

CANON_COLUMNS = [
    "canonical_id", "preferred_name", "alt_names", "sources", "n_sources",
    "glottocode", "iso639_3", "ea_society_id", "language_family",
    "lat", "lon", "area_sqkm", "has_historical", "has_modern",
    "historical_wkt", "modern_wkt",
    "population_total", "primary_religion",
    "trait_subsistence", "trait_settlement", "trait_politics", "trait_descent", "trait_class",
    "member_record_ids", "merge_confidence", "needs_review", "geometry",
]


class UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}
        self.sz = {i: 1 for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if self.sz[ra] < self.sz[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.sz[ra] += self.sz[rb]
        return ra

    def size(self, x):
        return self.sz[self.find(x)]


def _fuzzy_candidates(groups, recall=0.85):
    """Top-1 fuzzy name matches (both directions) between name-matched sources,
    annotated with score and whether the match is reciprocal.

    Matching is done on the qualifier-stripped `_match_key` (so "Hausa, Maouri"
    matches the bare "Hausa" territory), but the original names are reported.
    `literal` flags pairs whose RAW names are identical -- those are unambiguous
    ethnonym hits and are processed before qualifier-stripped exact-name hits so
    a territory attaches to the right coded cluster first."""
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        warnings.warn("rapidfuzz not installed -- entity resolution uses exact links only.")
        return []
    present = [s for s in NAME_MATCH_SOURCES if (groups["source"] == s).any()]
    cand = []
    for sa, sb in itertools.combinations(present, 2):
        A = groups[(groups["source"] == sa) & groups["name"].notna()].copy()
        B = groups[(groups["source"] == sb) & groups["name"].notna()].copy()
        A["_k"] = A["name"].map(_match_key)
        B["_k"] = B["name"].map(_match_key)
        A = A[A["_k"].notna()]
        B = B[B["_k"].notna()]
        if A.empty or B.empty:
            continue
        na, nb = A["name"].tolist(), B["name"].tolist()
        ka, kb = A["_k"].tolist(), B["_k"].tolist()
        ida, idb = A["record_id"].tolist(), B["record_id"].tolist()
        M = process.cdist(ka, kb, scorer=fuzz.token_sort_ratio)  # compare on keys
        best_b = M.argmax(axis=1)
        best_a = M.argmax(axis=0)
        seen = set()

        def _emit(i, j, reciprocal):
            s = float(M[i, j]) / 100
            if s < recall:
                return
            cand.append({"a": ida[i], "b": idb[j], "score": round(s, 3),
                         "name_a": na[i], "name_b": nb[j],
                         "reciprocal": bool(reciprocal),
                         "literal": na[i] == nb[j]})

        for i, j in enumerate(best_b):
            _emit(i, j, best_a[j] == i)
            seen.add((i, j))
        for j, i in enumerate(best_a):  # reverse direction, avoid dupes
            if (i, j) in seen:
                continue
            _emit(i, j, best_b[i] == j)
    return cand


def _ambiguous_match_keys(groups):
    """Match keys that, within the coded sources, point at MORE THAN ONE distinct
    authoritative code (glottocode or iso639_3). Joshua Project re-uses one head
    ethnonym across unrelated languages ("Beja, Amarar"=bej vs "Beja, Beni Amer"
    =tig; "Daza"=dzg vs hau), so such a key is NOT a safe exact-name bridge for a
    code-less territory -- it could attach to the wrong language. We let these
    fall to review unless a LITERAL full-name hit already pinned the right code.
    """
    by_key = {}
    coded = groups[groups["source"].isin(CODED_SOURCES)]
    for nm, glo, iso in coded[["name", "glottocode", "iso639_3"]].itertuples(index=False):
        k = _match_key(nm)
        if not k:
            continue
        d = by_key.setdefault(k, set())
        if isinstance(glo, str) and glo:
            d.add(("g", glo))
        if isinstance(iso, str) and iso:
            d.add(("i", iso))
    return {k for k, codes in by_key.items() if len(codes) > 1}


def _root_code_sets(groups, uf):
    """Per current-root sets of authoritative codes, for the conflict guard."""
    sets = {}
    for rec, glo, ea in groups[["record_id", "glottocode", "ea_society_id"]].itertuples(index=False):
        r = uf.find(rec)
        d = sets.setdefault(r, {"glotto": set(), "ea": set()})
        if isinstance(glo, str) and glo:
            d["glotto"].add(glo)
        if isinstance(ea, str) and ea:
            d["ea"].add(ea)
    return sets


def _code_conflict(sets, ra, rb):
    """True if the two clusters carry disjoint, non-empty code sets (same name
    but provably different language/society -> do not merge)."""
    da, db = sets.get(ra, {}), sets.get(rb, {})
    for key in ("glotto", "ea"):
        sa, sb = da.get(key, set()), db.get(key, set())
        if sa and sb and sa.isdisjoint(sb):
            return True
    return False


def _merge_code_sets(sets, root, ra, rb):
    da, db = sets.get(ra, {"glotto": set(), "ea": set()}), sets.get(rb, {"glotto": set(), "ea": set()})
    sets[root] = {"glotto": da["glotto"] | db["glotto"], "ea": da["ea"] | db["ea"]}


def resolve_entities(groups, links, traits=None, *, fuzzy_merge=0.92, fuzzy_recall=0.85):
    groups = groups.reset_index(drop=True).copy()
    uf = UnionFind(groups["record_id"].tolist())

    # --- 1. exact-code unions ---
    exact = links[links["method"].isin(EXACT_METHODS)]
    for a, b in exact[["record_id_a", "record_id_b"]].itertuples(index=False):
        if a in uf.parent and b in uf.parent:
            uf.union(a, b)

    # --- 2. name-based merges ---
    # EXACT normalized-name matches may fuse two clusters outright (the
    # continent-wide ethnolinguistic policy), UNLESS the clusters carry
    # conflicting authoritative codes (different glottocode / EA id) -- a same
    # name over two different languages signals genuinely different groups.
    # APPROXIMATE matches still need reciprocity, score >= fuzzy_merge, and the
    # singleton rule (attach a lone territory, never fuse two built entities).
    code_sets = _root_code_sets(groups, uf)  # root -> {"glotto": set, "ea": set}
    cand = _fuzzy_candidates(groups, recall=fuzzy_recall)
    ambiguous = _ambiguous_match_keys(groups)  # match keys with >1 coded meaning
    name_scores = {}   # root -> min score of name edges used
    review = []
    # Process LITERAL exact-name hits before qualifier-stripped exact-name hits
    # (both score ~1.0): a bare ethnonym match pins a code-less territory to the
    # correct coded cluster first, so any later ambiguous stripped edge to a
    # different language is then caught by the code-conflict guard.
    cand.sort(key=lambda x: (-x["score"], not x.get("literal", False)))
    for c in cand:
        a, b, s = c["a"], c["b"], c["score"]
        if a not in uf.parent or b not in uf.parent:
            continue
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        exact_name = s >= 0.999
        if exact_name:
            if _code_conflict(code_sets, ra, rb):
                review.append({**c, "decision": "name_code_conflict"})
                continue
            # A qualifier-stripped (non-literal) exact-name hit whose head is
            # ambiguous across coded sources is NOT a safe bridge -- defer it.
            if not c.get("literal", False) and _match_key(c["name_a"]) in ambiguous:
                review.append({**c, "decision": "ambiguous_stripped_name"})
                continue
            root = uf.union(a, b)
            _merge_code_sets(code_sets, root, ra, rb)
            name_scores[root] = min(name_scores.get(root, 1.0), s)
        elif s >= fuzzy_merge and c["reciprocal"] and min(uf.size(ra), uf.size(rb)) == 1:
            root = uf.union(a, b)
            _merge_code_sets(code_sets, root, ra, rb)
            name_scores[root] = min(name_scores.get(root, 1.0), s)
        else:
            reason = ("would_merge_two_entities" if (s >= fuzzy_merge and c["reciprocal"])
                      else "non_reciprocal" if not c["reciprocal"]
                      else "below_threshold")
            review.append({**c, "decision": reason})

    # propagate name-score minima to final roots (roots can change after later unions)
    final_fuzzy = {}
    for root, s in name_scores.items():
        fr = uf.find(root)
        final_fuzzy[fr] = min(final_fuzzy.get(fr, 1.0), s)

    # --- 3. assign stable canonical ids ---
    groups["_root"] = groups["record_id"].map(uf.find)
    order = (groups.groupby("_root").size().sort_values(ascending=False).index.tolist())
    root2id = {r: f"AEG-{i + 1:05d}" for i, r in enumerate(order)}
    groups["canonical_id"] = groups["_root"].map(root2id)

    # --- 4. build canonical rows ---
    trait_map = None
    if traits is not None and len(traits):
        tsel = traits[traits["var_id"].isin(TRAIT_VARS.values())]
        trait_map = tsel.pivot_table(index="ea_society_id", columns="var_id",
                                      values="value_label", aggfunc="first")

    rows = []
    for root, members in groups.groupby("_root"):
        cid = root2id[root]
        rows.append(_build_entity(cid, members, trait_map, final_fuzzy.get(root)))
    canonical = gpd.GeoDataFrame(rows, columns=CANON_COLUMNS, geometry="geometry",
                                 crs="EPSG:4326")

    review_df = pd.DataFrame(
        review, columns=["a", "b", "name_a", "name_b", "score", "reciprocal", "decision"]
    ).sort_values("score", ascending=False).reset_index(drop=True)

    groups = groups.drop(columns=["_root"])
    return {"canonical": canonical, "review_candidates": review_df, "groups": groups}


def _mode(series):
    s = series.dropna()
    s = s[s.astype(str).str.len() > 0]
    return s.mode().iloc[0] if not s.empty else None


def _union_geom(members, source):
    sub = members[(members["source"] == source) & members.geometry.notna()]
    if sub.empty:
        return None
    geoms = sub.geometry
    invalid = ~geoms.is_valid  # source polygons are often self-intersecting
    if invalid.any():
        geoms = geoms.copy()
        geoms.loc[invalid] = geoms.loc[invalid].buffer(0)
    try:
        geom = geoms.union_all()
    except Exception:
        geom = geoms.buffer(0).union_all()  # last-ditch repair
    return geom if (geom is not None and not geom.is_empty) else None


def _build_entity(cid, members, trait_map, fuzzy_min):
    sources = sorted(members["source"].unique().tolist())
    # preferred name: the MOST COMMON member name (so the recognizable ethnonym
    # wins over a single source's technical label, e.g. "Hausa" not the EA
    # society's "Zazzagawa Hausa"). Ties broken by source priority, then by the
    # shorter name.
    named = members.dropna(subset=["name"])
    pref = cid
    if not named.empty:
        counts = named["name"].value_counts()
        top = counts[counts == counts.max()].index.tolist()
        if len(top) == 1:
            pref = top[0]
        else:
            pri = {s: i for i, s in enumerate(NAME_PRIORITY)}
            cand = named[named["name"].isin(top)].copy()
            cand["_pri"] = cand["source"].map(lambda s: pri.get(s, 99))
            cand["_len"] = cand["name"].str.len()
            pref = cand.sort_values(["_pri", "_len"]).iloc[0]["name"]
    alt = sorted({n for n in members["name"].dropna().tolist() if n != pref})

    glotto = _mode(members["glottocode"])
    iso = _mode(members["iso639_3"])
    ea = _mode(members["ea_society_id"])

    # language family glottocode from glottolog members' attrs
    fam = None
    gl = members[members["source"] == "glottolog"]
    for attr in gl["source_attrs"].dropna():
        try:
            fam = json.loads(attr).get("Family_ID") or fam
        except Exception:
            pass

    hist = _union_geom(members, "murdock_map")
    modern = _union_geom(members, "geoepr")
    primary = hist or modern
    if primary is None:  # fall back to a representative point
        pts = members[members.geometry.notna()]
        primary = pts.geometry.union_all().centroid if not pts.empty else None

    area = None
    if hist is not None:
        area = float(gpd.GeoSeries([hist], crs=4326).to_crs(6933).area.iloc[0] / 1e6)

    rep = primary.centroid if (primary is not None and primary.geom_type != "Point") else primary
    lat = rep.y if rep is not None else _mode(members["lat"])
    lon = rep.x if rep is not None else _mode(members["lon"])

    jp = members[members["source"] == "joshua_project"]
    pop = float(jp["population"].dropna().sum()) if not jp.empty else None
    religion = _mode(jp["primary_religion"]) if not jp.empty else None

    traits_out = {k: None for k in TRAIT_VARS}
    if trait_map is not None and ea in getattr(trait_map, "index", []):
        trow = trait_map.loc[ea]
        for col, var in TRAIT_VARS.items():
            if var in trait_map.columns:
                v = trow.get(var)
                traits_out[col] = None if pd.isna(v) else v

    # name_min is None for pure code-linked entities, else the weakest name edge.
    # Any name-based merge is flagged for review (even an exact-name one).
    conf = 1.0 if fuzzy_min is None else round(fuzzy_min, 3)
    needs_review = fuzzy_min is not None
    return {
        "canonical_id": cid,
        "preferred_name": pref,
        "alt_names": json.dumps(alt, ensure_ascii=False) if alt else None,
        "sources": json.dumps(sources),
        "n_sources": len(sources),
        "glottocode": glotto,
        "iso639_3": iso,
        "ea_society_id": ea,
        "language_family": fam,
        "lat": lat,
        "lon": lon,
        "area_sqkm": area,
        "has_historical": hist is not None,
        "has_modern": modern is not None,
        "historical_wkt": hist.wkt if hist is not None else None,
        "modern_wkt": modern.wkt if modern is not None else None,
        "population_total": pop,
        "primary_religion": religion,
        **traits_out,
        "member_record_ids": json.dumps(members["record_id"].tolist()),
        "merge_confidence": conf,
        "needs_review": needs_review,
        "geometry": primary,
    }
