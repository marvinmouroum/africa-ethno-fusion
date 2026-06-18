"""Build the `links` crosswalk between group records across sources.

Two kinds of links:
  * exact-code joins on a shared key (ea_society_id / glottocode / iso639_3)
    -> confidence 1.0
  * fuzzy name matches between the polygon datasets (murdock_map / greg / geoepr),
    which carry NO language codes -> confidence = score / 100

The fuzzy step is optional (needs `rapidfuzz`); if unavailable we skip it.
"""
from __future__ import annotations

import itertools
import warnings

import pandas as pd

from . import schema

EXACT_KEYS = ["ea_society_id", "glottocode", "iso639_3"]
POLYGON_SOURCES = ["murdock_map", "greg", "geoepr"]


def _exact_links(groups: pd.DataFrame) -> list[tuple]:
    out = []
    for key in EXACT_KEYS:
        sub = groups[groups[key].notna() & (groups[key].astype(str).str.len() > 0)]
        for val, idx in sub.groupby(key).groups.items():
            recs = sub.loc[idx, ["record_id", "source"]].to_dict("records")
            for a, b in itertools.combinations(recs, 2):
                if a["source"] == b["source"]:
                    continue
                out.append(
                    (a["record_id"], b["record_id"], a["source"], b["source"], key, str(val), 1.0)
                )
    return out


def _fuzzy_name_links(groups: pd.DataFrame, threshold: int = 88) -> list[tuple]:
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        warnings.warn("rapidfuzz not installed -- skipping fuzzy name crosswalk.")
        return []

    out = []
    present = [s for s in POLYGON_SOURCES if (groups["source"] == s).any()]
    for sa, sb in itertools.combinations(present, 2):
        A = groups[(groups["source"] == sa) & groups["name"].notna()]
        B = groups[(groups["source"] == sb) & groups["name"].notna()]
        if A.empty or B.empty:
            continue
        names_a = A["name"].tolist()
        names_b = B["name"].tolist()
        # for each A name, take the single best B match above threshold
        matches = process.cdist(
            names_a, names_b, scorer=fuzz.token_sort_ratio, score_cutoff=threshold
        )
        a_ids = A["record_id"].tolist()
        b_ids = B["record_id"].tolist()
        for i, row in enumerate(matches):
            j = int(row.argmax())
            score = float(row[j])
            if score < threshold:
                continue
            out.append(
                (a_ids[i], b_ids[j], sa, sb, "fuzzy_name", names_b[j], round(score / 100, 3))
            )
    return out


def build_links(groups, fuzzy: bool = True, fuzzy_threshold: int = 88) -> pd.DataFrame:
    rows = _exact_links(groups)
    if fuzzy:
        rows += _fuzzy_name_links(groups, fuzzy_threshold)
    df = pd.DataFrame(rows, columns=schema.LINK_COLUMNS)
    return df.drop_duplicates(subset=["record_id_a", "record_id_b", "method"]).reset_index(
        drop=True
    )
