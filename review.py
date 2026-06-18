#!/usr/bin/env python3
"""Render an HTML review sheet (out/review.html) for adjudicating entity-resolution merges.

The canonical layer (see africa_ethno_fusion/entity.py) collapses per-source records
into one row per real-world ethnic group. Any merge that leaned on a NAME edge -- even
an exact normalized-name match -- is flagged with ``needs_review = True`` and a
``merge_confidence`` score (1.0 for an exact-name merge, < 1.0 for a fuzzy one). Pure
code-linked entities (EA id / glottocode / ISO 639-3) are trusted and not flagged.

This script produces a self-contained, dependency-free HTML page a human can open to
decide, for each flagged entity, "is this really one group?", plus the list of fuzzy
name pairs that were rejected outright (review_candidates).

Run:
    python review.py                 # reads out/*.parquet -> writes out/review.html
    python review.py --out some_dir   # use a different output directory
"""
from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime

import pandas as pd


# --------------------------------------------------------------------------- #
# data loading
# --------------------------------------------------------------------------- #
def review_load(out_dir):
    """Load the three parquet inputs. canonical/groups are required; candidates optional."""
    import os

    def _path(name):
        return os.path.join(out_dir, name)

    canonical = pd.read_parquet(_path("canonical.parquet"))
    groups = pd.read_parquet(_path("groups.parquet"))
    cand_path = _path("review_candidates.parquet")
    if os.path.exists(cand_path):
        candidates = pd.read_parquet(cand_path)
    else:
        candidates = pd.DataFrame(
            columns=["a", "b", "name_a", "name_b", "score", "reciprocal", "decision"]
        )
    return canonical, groups, candidates


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def review_loads_list(val):
    """Parse a JSON-list column value into a Python list (tolerant of None / already-list)."""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        return list(val)
    if isinstance(val, float) and math.isnan(val):
        return []
    try:
        out = json.loads(val)
        return out if isinstance(out, list) else [out]
    except (TypeError, ValueError):
        return [val]


def review_record_name_map(groups):
    """record_id -> display name (falls back to the record_id itself when nameless)."""
    if "record_id" not in groups.columns:
        return {}
    name_col = "name" if "name" in groups.columns else None
    out = {}
    for row in groups.itertuples(index=False):
        rid = getattr(row, "record_id")
        nm = getattr(row, name_col) if name_col else None
        if nm is None or (isinstance(nm, float) and math.isnan(nm)):
            nm = rid
        out[rid] = str(nm)
    return out


def review_member_names(member_ids, name_map):
    """Resolve a list of "source:id" record ids to '<name> (<source:id>)' strings."""
    parts = []
    for rid in member_ids:
        nm = name_map.get(rid)
        if nm and nm != rid:
            parts.append(f"{nm} ({rid})")
        else:
            parts.append(str(rid))
    return parts


def _esc(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return html.escape(str(val))


def _fmt_pop(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    try:
        return f"{float(val):,.0f}"
    except (TypeError, ValueError):
        return _esc(val)


def _fmt_conf(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    try:
        return f"{float(val):.3f}"
    except (TypeError, ValueError):
        return _esc(val)


def _sources_str(val):
    """Render the JSON sources list compactly: 'dplace_ea, greg, murdock_map'."""
    items = review_loads_list(val)
    return ", ".join(_esc(x) for x in items)


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --ink: #1c2530; --muted: #667;
  --line: #e2e6eb; --accent: #13496f; --warn: #b3541e; --ok: #2b7a2b;
  --chip: #eef2f6;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  margin: 0; background: var(--bg); color: var(--ink); font-size: 14px; line-height: 1.45;
}
.wrap { max-width: 1400px; margin: 0 auto; padding: 28px 22px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 36px 0 10px; color: var(--accent); }
.sub { color: var(--muted); margin: 0 0 22px; }
.legend {
  background: #fff8ef; border: 1px solid #f0dcc4; color: #6b4a23;
  padding: 9px 13px; border-radius: 8px; margin: 0 0 24px; font-size: 13px;
}
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 8px; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 16px; min-width: 150px; flex: 1 1 150px;
}
.card .n { font-size: 24px; font-weight: 700; }
.card .l { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
.card.warn .n { color: var(--warn); }
table {
  border-collapse: collapse; width: 100%; background: var(--card);
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden; font-size: 13px;
}
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
thead th {
  background: #eef2f6; cursor: pointer; user-select: none; white-space: nowrap;
  position: sticky; top: 0;
}
thead th:hover { background: #e2e9f0; }
thead th .arrow { color: var(--accent); font-size: 11px; }
tbody tr:hover { background: #f4f8fb; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.members { color: #334; }
.members .m { display: inline-block; background: var(--chip); border-radius: 4px;
  padding: 1px 6px; margin: 1px 3px 1px 0; font-size: 12px; }
.tag { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.tag.exact { background: #e4f0e4; color: var(--ok); }
.tag.fuzzy { background: #fbe7d8; color: var(--warn); }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
.empty { color: var(--muted); font-style: italic; padding: 14px; }
.foot { color: var(--muted); font-size: 12px; margin-top: 40px; }
code { background: var(--chip); padding: 1px 4px; border-radius: 4px; }
"""

SORT_JS = """
// Lightweight client-side table sort. Click a <th> to sort by that column.
// Numeric columns (data-type="num") sort numerically; everything else lexically.
function afefSortable(table) {
  const heads = table.tHead.rows[0].cells;
  for (let i = 0; i < heads.length; i++) {
    heads[i].addEventListener('click', () => afefSort(table, i, heads[i]));
  }
}
function afefSort(table, col, th) {
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const numeric = th.dataset.type === 'num';
  const cur = th.dataset.dir === 'asc' ? 'asc' : (th.dataset.dir === 'desc' ? 'desc' : '');
  const dir = cur === 'asc' ? 'desc' : 'asc';
  // clear arrows on siblings
  for (const h of th.parentNode.cells) { h.dataset.dir = ''; const a = h.querySelector('.arrow'); if (a) a.textContent = ''; }
  th.dataset.dir = dir;
  const arrow = th.querySelector('.arrow'); if (arrow) arrow.textContent = dir === 'asc' ? ' ▲' : ' ▼';
  const val = (r) => {
    const cell = r.cells[col];
    const raw = cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
    return numeric ? (raw === '' ? NaN : parseFloat(raw)) : raw.toLowerCase();
  };
  rows.sort((a, b) => {
    let x = val(a), y = val(b);
    if (numeric) {
      const xn = isNaN(x), yn = isNaN(y);
      if (xn && yn) return 0; if (xn) return 1; if (yn) return -1;  // blanks last
      return dir === 'asc' ? x - y : y - x;
    }
    if (x < y) return dir === 'asc' ? -1 : 1;
    if (x > y) return dir === 'asc' ? 1 : -1;
    return 0;
  });
  for (const r of rows) tbody.appendChild(r);
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('table.sortable').forEach(afefSortable);
});
"""


def _th(label, dtype="str", num=False):
    cls = ' class="num"' if num else ""
    dt = ' data-type="num"' if dtype == "num" else ""
    return f'<th{cls}{dt}>{html.escape(label)}<span class="arrow"></span></th>'


def review_flagged_table(canonical, name_map):
    """Build the flagged-entities (needs_review==True) sortable table HTML."""
    if "needs_review" not in canonical.columns:
        return '<p class="empty">No needs_review column in canonical.parquet.</p>'
    flagged = canonical[canonical["needs_review"] == True].copy()  # noqa: E712
    if flagged.empty:
        return '<p class="empty">No flagged entities -- nothing needs review.</p>'
    if "merge_confidence" in flagged.columns:
        flagged = flagged.sort_values("merge_confidence", ascending=True, kind="mergesort")

    cols = [
        ("preferred_name", "Preferred name", "str", False),
        ("merge_confidence", "Confidence", "num", True),
        ("n_sources", "# src", "num", True),
        ("sources", "Sources", "str", False),
        ("ea_society_id", "EA id", "str", False),
        ("glottocode", "Glottocode", "str", False),
        ("iso639_3", "ISO 639-3", "str", False),
        ("population_total", "Population", "num", True),
        ("members", "Member records (names)", "str", False),
    ]
    head = "".join(_th(label, dtype, num) for _, label, dtype, num in cols)

    body_rows = []
    for r in flagged.itertuples(index=False):
        d = r._asdict()
        conf = d.get("merge_confidence")
        is_exact = conf is not None and not (isinstance(conf, float) and math.isnan(conf)) and float(conf) >= 1.0
        tag = '<span class="tag exact">exact</span>' if is_exact else '<span class="tag fuzzy">fuzzy</span>'

        members = review_member_names(review_loads_list(d.get("member_record_ids")), name_map)
        members_html = "".join(f'<span class="m">{_esc(m)}</span>' for m in members) or '<span class="empty">—</span>'

        conf_val = "" if conf is None or (isinstance(conf, float) and math.isnan(conf)) else float(conf)
        pop = d.get("population_total")
        pop_val = "" if pop is None or (isinstance(pop, float) and math.isnan(pop)) else float(pop)
        n_src = d.get("n_sources")
        n_src_val = "" if n_src is None or (isinstance(n_src, float) and math.isnan(n_src)) else int(n_src)

        cells = [
            f'<td>{_esc(d.get("preferred_name"))}</td>',
            f'<td class="num" data-sort="{conf_val}">{_fmt_conf(conf)} {tag}</td>',
            f'<td class="num" data-sort="{n_src_val}">{_esc(n_src_val)}</td>',
            f'<td>{_sources_str(d.get("sources"))}</td>',
            f'<td class="mono">{_esc(d.get("ea_society_id"))}</td>',
            f'<td class="mono">{_esc(d.get("glottocode"))}</td>',
            f'<td class="mono">{_esc(d.get("iso639_3"))}</td>',
            f'<td class="num" data-sort="{pop_val}">{_fmt_pop(pop)}</td>',
            f'<td class="members">{members_html}</td>',
        ]
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<table class="sortable"><thead><tr>' + head + "</tr></thead><tbody>"
        + "".join(body_rows) + "</tbody></table>"
    )


def review_candidates_table(candidates):
    """Build the rejected-candidates sortable table HTML."""
    if candidates is None or candidates.empty:
        return '<p class="empty">No rejected candidates.</p>'

    cols = [
        ("name_a", "Name A", "str", False),
        ("name_b", "Name B", "str", False),
        ("score", "Score", "num", True),
        ("reciprocal", "Reciprocal", "str", False),
        ("decision", "Decision", "str", False),
    ]
    head = "".join(_th(label, dtype, num) for _, label, dtype, num in cols)

    df = candidates.copy()
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False, kind="mergesort")

    body_rows = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        score = d.get("score")
        score_val = "" if score is None or (isinstance(score, float) and math.isnan(score)) else float(score)
        recip = d.get("reciprocal")
        recip_str = "" if recip is None or (isinstance(recip, float) and math.isnan(recip)) else ("yes" if bool(recip) else "no")
        cells = [
            f'<td>{_esc(d.get("name_a"))}</td>',
            f'<td>{_esc(d.get("name_b"))}</td>',
            f'<td class="num" data-sort="{score_val}">{_fmt_conf(score)}</td>',
            f'<td>{recip_str}</td>',
            f'<td class="mono">{_esc(d.get("decision"))}</td>',
        ]
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        '<table class="sortable"><thead><tr>' + head + "</tr></thead><tbody>"
        + "".join(body_rows) + "</tbody></table>"
    )


def review_summary(canonical, candidates):
    """Compute header counts. Returns a dict of integers."""
    total = len(canonical)
    n_multi = 0
    if "n_sources" in canonical.columns:
        n_multi = int((pd.to_numeric(canonical["n_sources"], errors="coerce") > 1).sum())

    flagged_exact = flagged_fuzzy = 0
    if "needs_review" in canonical.columns:
        flagged = canonical[canonical["needs_review"] == True]  # noqa: E712
        conf = pd.to_numeric(flagged.get("merge_confidence"), errors="coerce")
        flagged_exact = int((conf >= 1.0).sum())
        flagged_fuzzy = int((conf < 1.0).sum())
    n_candidates = 0 if candidates is None else len(candidates)
    return {
        "total": total,
        "multi": n_multi,
        "flagged_total": flagged_exact + flagged_fuzzy,
        "flagged_exact": flagged_exact,
        "flagged_fuzzy": flagged_fuzzy,
        "candidates": n_candidates,
    }


def review_render(canonical, groups, candidates):
    name_map = review_record_name_map(groups)
    s = review_summary(canonical, candidates)
    flagged_html = review_flagged_table(canonical, name_map)
    cand_html = review_candidates_table(candidates)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = f"""
    <div class="cards">
      <div class="card"><div class="n">{s['total']:,}</div><div class="l">Total entities</div></div>
      <div class="card"><div class="n">{s['multi']:,}</div><div class="l">Multi-source</div></div>
      <div class="card warn"><div class="n">{s['flagged_total']:,}</div><div class="l">Needs review (total)</div></div>
      <div class="card"><div class="n">{s['flagged_exact']:,}</div><div class="l">&nbsp;&nbsp;exact-name (conf 1.0)</div></div>
      <div class="card"><div class="n">{s['flagged_fuzzy']:,}</div><div class="l">&nbsp;&nbsp;fuzzy (conf &lt; 1.0)</div></div>
      <div class="card"><div class="n">{s['candidates']:,}</div><div class="l">Rejected candidates</div></div>
    </div>"""

    legend = (
        '<div class="legend"><b>needs_review</b> is set when an entity was assembled '
        'using at least one <i>name</i> edge (no shared authoritative code). '
        '<span class="tag exact">exact</span> = exact normalized-name merge '
        '(<code>merge_confidence == 1.0</code>); '
        '<span class="tag fuzzy">fuzzy</span> = approximate name match '
        '(<code>merge_confidence &lt; 1.0</code>). '
        'Pure code-linked entities (EA id / glottocode / ISO 639-3) are trusted and not flagged.</div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>africa-ethno-fusion — entity-resolution review sheet</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Entity-resolution review sheet</h1>
  <p class="sub">africa-ethno-fusion · adjudicate which merged entities are really one group · generated {now}</p>
  {cards}
  {legend}

  <h2>Flagged entities ({s['flagged_total']:,}) — sorted by merge_confidence ↑</h2>
  {flagged_html}

  <h2>Rejected candidates ({s['candidates']:,}) — fuzzy name pairs not auto-merged</h2>
  {cand_html}

  <p class="foot">Click any column header to sort. Member records are resolved
  from <code>member_record_ids</code> ("source:id") against <code>out/groups.parquet</code>.</p>
</div>
<script>{SORT_JS}</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser(description="Generate out/review.html from the fused parquet outputs.")
    ap.add_argument("--out", default="out", help="directory holding *.parquet and receiving review.html (default: out)")
    args = ap.parse_args()

    import os

    canonical, groups, candidates = review_load(args.out)
    htmldoc = review_render(canonical, groups, candidates)
    dest = os.path.join(args.out, "review.html")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(htmldoc)

    s = review_summary(canonical, candidates)
    print(f"wrote {dest}")
    print(f"  total entities         : {s['total']:,}")
    print(f"  multi-source           : {s['multi']:,}")
    print(f"  needs_review (total)   : {s['flagged_total']:,}  "
          f"(exact={s['flagged_exact']:,}, fuzzy={s['flagged_fuzzy']:,})")
    print(f"  rejected candidates    : {s['candidates']:,}")


if __name__ == "__main__":
    main()
