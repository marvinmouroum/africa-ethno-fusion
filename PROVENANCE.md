# Provenance, licensing & how to cite

This project is an **integration layer**. It does not create new primary data — it
fuses existing open datasets and adds entity resolution, a crosswalk, and a map.
If you use it in research, **cite the upstream datasets you rely on**, not just this
tool. See `CITATION.cff` for how to cite the software itself.

## What we redistribute (and what we don't)

- **Redistributed in this repo:** the **pipeline code**, the **ID-level crosswalk**
  (`links`, keyed by each source's own identifiers), and a derived **interactive
  visualisation** (`docs/index.html`).
- **Not redistributed as bulk data:** the **merged corpus** itself. Several inputs
  are **non-commercial / custom-licensed** (below), so the merged tables are meant
  to be **rebuilt from source** by running `build.py`. Anyone redistributing the
  fused data must check the upstream terms.

## Source datasets

| source (key) | what we use | license | cite |
|---|---|---|---|
| Murdock map (`murdock_map`) | ethnic homeland polygons (~1830–1900), EA society codes | CC BY-NC-SA 3.0 (sboysel digitisation) | Murdock (1959); Nunn digitisation |
| GREG (`greg`) | ethnic territory polygons (Atlas Narodov Mira, 1964) | free for research, cite | Weidmann, Rød & Cederman (2010) |
| GeoEPR (`geoepr`) | time-varying settlement areas of politically relevant groups | free for research, cite | Vogt et al. (2015); Wucherpfennig et al. (2011) |
| D-PLACE Ethnographic Atlas (`dplace_ea`) | society points + cultural traits | CC BY-NC 4.0 | Kirby et al. (2016); Murdock (1967) |
| Glottolog (`glottolog`) | language reference points; ISO 639-3 ⇄ glottocode bridge | CC BY 4.0 | Hammarström et al. (Glottolog) |
| Glottography (`glottography`) | open language-area polygons (Asher & Moseley atlas) | mostly CC BY 4.0 | Asher & Moseley (2007); Glottography project |
| Joshua Project (`joshua_project`) | contemporary people-group points: population, religion | custom terms of use | Joshua Project |

> ⚠️ **Commercial use:** Murdock/Nunn (CC BY-**NC**-SA) and D-PLACE (CC BY-**NC**) are
> NonCommercial; Joshua Project has its own terms. Glottolog (CC BY 4.0) and
> GREG/GeoEPR (cite-only) are the most permissive. Review before any commercial reuse.

## Related work (what already exists, and how this differs)

- **LEDA — Linking Ethnic Data from Africa** (Müller-Crepon, Pengl & Bormann, 2022,
  *Journal of Peace Research*; R package, GPL-3). The reference solution for the
  **group-identity reconciliation** problem: links 8,100+ ethnic categories across 11
  datasets via the Ethnologue linguistic tree, returning **dyadic link tables**. It
  does **not** attach cultural traits, fuse single-geometry-per-group territories,
  add population/religion, use Glottolog/Glottography, or ship a map. This project is
  **complementary**: it solves the **fusion + spatialisation + presentation** problem.
  LEDA's crosswalk could serve as a more rigorous linkage backbone in future work
  (not integrated here, to keep the runtime pure-Python and MIT-clean — LEDA is GPL-3).
- **Database of Global Cultural Evolution** (Harvard) — links Glottolog IDs to the
  Ethnographic Atlas (trait side only; not spatial/African-territory-focused).
- **Nunn (2025) Murdock↔EA concordance** — one seam (map polygons ↔ EA societies).
- **Glottography / Atlas of the World's Languages** — language-area polygons; one seam.

None of these packages territory + traits + language-area + demography into a single
open, reproducible, map-ready spatial product with a public explorer.

## Caveats researchers must respect

- Boundaries are approximate and contested; each territory source freezes a moment
  (Murdock ~1900, GREG 1964, GeoEPR time-varying). Treat them as operationalisations.
- Entity resolution embeds choices; the **canonical table** (with `needs_review` and
  per-link `merge_confidence`) is the research asset. The map's population-ranked
  dominance colouring is **illustrative**, not a claim about who "really" dominates.
- The integration inherits each upstream dataset's biases (e.g. Joshua Project's
  missionary origin; the Soviet-atlas lens of GREG).
