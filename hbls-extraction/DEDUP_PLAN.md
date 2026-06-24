# Deduplication plan — using HBLS person records across HLS and EOS data

## Goal

Three person corpora describe overlapping historical Swiss people:

| Corpus | What it is | Records | Key fields |
|---|---|---|---|
| **HBLS** | printed lexicon 1921–34, freshly extracted | 27,838 persons | surname, given, birth/death year, volume/page |
| **HLS** | online successor of HBLS | ~60k bios (life-dated) | family/first name, birth/death date, article id |
| **EOS / HGB** | Historisches Grundbuch Basel mentions | `persons_resolved.json` (resolved clusters) | name + variants, mention span `y`, occupations, dossiers |

The same person frequently appears in two or three of them. We want a single
**cross-corpus identity** so that, e.g., a Basel notary in the HGB property
register, his HBLS family article, and his HLS biography collapse into one node
with merged attributes and provenance back to each source.

HBLS is the natural **hub**: it is the printed parent of HLS (so HBLS↔HLS links
are dense and high-precision) and it is biographical/genealogical (so it links
well to the EOS/HGB persons that are also mostly Basel-region individuals).

## Inputs already produced

- `hbls_persons.json` — 27,838 clean HBLS person records (`build_persons.py`).
- `../link_hbls_hls.py` → `../link_hbls_hls_candidates.csv` — HBLS↔HLS candidates.
- `../link_hls.py` → `../link_candidates_hls.csv` — existing HGB↔HLS candidates.
- `hbls_persons_basel.{csv,json}` — the 4,932 HBLS persons connected to Basel.

## Matching model (shared across all pairs)

Reuse the normalisation already in `link_hls.py` (particle stripping, given-name
canonicalisation, accent folding, `SequenceMatcher` surname/given ratios). A
candidate link requires:

1. **surname** ratio ≥ 0.85 (blocked by surname initial for speed),
2. **given** ratio ≥ 0.74 after canonicalisation,
3. **temporal agreement**:
   - HBLS↔HLS: birth or death year within ±4 (both within ±9), else floruit
     years inside the HLS lifespan. *(implemented in `link_hbls_hls.py`)*
   - HBLS↔HGB: the HGB **mention span** must overlap the HBLS lifespan, with a
     post-mortem grace window (same `date_relation` logic as `link_hls.py`).

Each candidate gets a `score = 0.4·surname + 0.3·given + 0.3·date_closeness`
and an `n_candidates` ambiguity flag.

## Pipeline

### Stage 1 — HBLS ↔ HLS  *(done)*
`python3 link_hbls_hls.py` → `link_hbls_hls_candidates.csv`.
Because HLS *is* the successor of HBLS, expect a high unambiguous rate. Treat
`score ≥ 0.9 AND n_candidates == 1 AND year_match ∈ {birth±0..2, both±0..3}` as
**auto-accept**; the rest go to human review. The accepted links give every
matched HBLS person a stable **HLS id** (and thus an `hls-dhs-dss.ch` URL and,
via HLS, often a GND/Wikidata id already present in the site's enrichment).

### Stage 2 — HBLS ↔ EOS/HGB persons  *(done for the Basel slice — `link_hbls_hgb.py`)*
Run the same matcher with HBLS persons on one side and `persons_resolved.json`
on the other, using the **mention-span** date rule. Two sub-passes:
  a. **direct** name+date match — 406 Basel HBLS persons matched ≥1 HGB person
     (139 unambiguous) → `link_hbls_hgb_candidates.csv`;
  b. **transitive** — if HBLS person *X* ≈ HLS bio *H* (Stage 1) and HGB person
     *P* ≈ *H* (existing `link_candidates_hls.csv`), then *X*↔*P* is implied —
     374 pairs (170 unambiguous on both sides) → `link_hbls_hgb_transitive.csv`.
     These shared-HLS links are the highest-confidence cross-links and need the
     least review. Next: run `--all` to extend beyond Basel.

### Stage 3 — Build identity clusters
Model every accepted link as an edge in a graph whose nodes are
`(corpus, local_id)`. Connected components = one real person. Guard against
over-merging:
  - never merge two records from the **same** corpus into one node unless an
    intra-corpus dedup step says so (HBLS already numbers family members
    separately; HGB is pre-resolved);
  - reject a component if it contains life-date-incompatible members
    (birth years spread > ~15 y), flag for review instead;
  - keep `n_candidates > 1` edges out of auto-merge.

### Stage 4 — Merge & emit
For each cluster emit a merged person: preferred display name (HLS form if
present, else HBLS), union of life dates (prefer HLS precision), occupations
(HGB), family links (HBLS genealogy + existing `families_*`), and a
`sources[]` array with `{corpus, id, url/backlink}` for full provenance.
Surface the HBLS link in the site exactly like the existing HLS/Wikidata
chips in `index.html`.

## Intra-HBLS dedup (prerequisite, lightweight)
The same family is occasionally printed in more than one volume/supplement
(band 8 is a supplement). Collapse HBLS-internal duplicates first: same
`surname` + given ratio ≥ 0.9 + birth/death within ±2 ⇒ same person. This keeps
Stage 3 components clean.

## Validation
- **Header-bounds / alphabetical** sanity already passed at extraction time.
- For links, sample 100 auto-accepted HBLS↔HLS pairs and 100 HBLS↔HGB pairs for
  manual precision estimates before trusting auto-merge thresholds.
- Use the **Basel subset** (`hbls_persons_basel.*`, 4,932 persons) as the first
  evaluation slice: it is the densest overlap region with the HGB (Historisches
  Grundbuch *Basel*) corpus, so HBLS↔HGB precision/recall is most meaningful and
  most useful there. Start dedup on Basel, tune thresholds, then roll out to all
  of Switzerland.

## Why start with Basel
The EOS/HGB data is Basel property-register persons. The realistic, immediately
useful overlap is therefore Basel-connected HBLS people. The Basel subset is
already isolated, so Stage 2 can be run on it alone first — smaller, reviewable,
and directly serving the existing site — before scaling to the full corpus.
