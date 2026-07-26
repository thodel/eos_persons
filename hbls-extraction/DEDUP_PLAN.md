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

### Stage 3 — Build identity clusters  *(done — `../build_identity_clusters.py`)*
Model every accepted link as an edge in a graph whose nodes are
`(corpus, local_id)` **plus the shared authority ids** (`gnd:<id>`, `wd:<qid>`),
so two records pointing at the same GND/Wikidata id merge transitively — the
strongest dedup signal. Connected components = one real person. Guard against
over-merging:
  - never merge two records from the **same** corpus into one node unless an
    intra-corpus dedup step says so (HBLS already numbers family members
    separately; HGB is pre-resolved);
  - reject a component if it contains life-date-incompatible members
    (birth years spread > ~15 y), flag for review instead;
  - keep `n_candidates > 1` edges out of auto-merge.

*Result (Basel slice):* 2,463 components (size ≥ 2) → **1,782 conflict-free
cross-corpus identities** (`identity_clusters.csv`), **1,949 carrying a GND id**,
70 spanning all three source corpora (HBLS+HGB+HLS). 422 components are flagged
for review (301 multi-HGB homonyms, 80 birth-spread, 47 multi-HBLS, 19 each
multi-HLS/GND/Wikidata) — exactly the cases the guards are meant to catch.

### Stage 4 — Merge & emit  *(done — `../build_merged_persons.py`)*
For each cluster emit a merged person: preferred display name (HLS form if
present, else HBLS), union of life dates (prefer HLS precision), occupations
(HGB), family links (HBLS genealogy + existing `families_*`), and a
`sources[]` array with `{corpus, id, url/backlink}` for full provenance.

Field precedence is HLS → GND → HBLS for name and life dates (the online
lexicon is the corrected successor of the printed one); each record carries a
`provenance` block naming the corpus every chosen value came from. Occupations
pool the HGB register terms with the GND authority roles but stay separately
addressable (`occupations_hgb`, `roles_gnd`).

*Result (Basel slice):* 2,463 clusters → **2,012 merged persons**
(`merged_persons.json`, flat summary in `merged_persons.csv`), 1,991 with life
dates, 1,722 with a GND id, 1,227 with occupations, 373 with publications, 13
spanning all three source corpora. 451 go to review. All corpus joins resolve
(0 dangling members). Names come from HLS for 1,689 and HBLS for 323.

**Given-name gate.** Stage 4 adds a check the earlier stages cannot make:
`link_hls.split_name` compares `toks[0]` only, so "Hans Ulrich" and "Johann
Jakob" match perfectly (both canonicalise to `johann`) — yet in early-modern
Swiss naming the *second* given name is the distinguishing one. Merged records
are therefore re-scored on the common prefix of **all** given tokens (particles
and HLS noble epithets stripped, so "Escher vom Luchs" does not leak in); below
`--name-min` (default 0.6) the cluster is flagged `name_disagreement` instead of
merged. A missing middle name does not count against a cluster, a conflicting
one does. This catches 27 clusters that every upstream gate passed — e.g.
HLS *Konrad Fässler* ↔ HGB *Johannes Faser*, and HBLS *Hans Heinrich Müller* ↔
HGB *Hanß Otmar Müller*. Manual inspection of all 27 found 26 genuine
mis-merges and 1 OCR artifact (`Joh.Jakob` ↔ `Jakob`), so the flag is worth
its review cost — and it indicates the same blind spot inflates the Stage 1–2
link counts, which the planned precision sampling should quantify.

Still to do: surface the merged records in the site the way the existing
HLS/Wikidata chips work in `index.html` (`merged_persons.json` is not yet read
by any page).

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
