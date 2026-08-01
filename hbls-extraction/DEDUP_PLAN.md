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

### Stage 2 — HBLS ↔ EOS/HGB persons  *(done, full corpus — `link_hbls_hgb.py --all`)*
Run the same matcher with HBLS persons on one side and `persons_resolved.json`
on the other, using the **mention-span** date rule. Two sub-passes:
  a. **direct** name+date match — 398 Basel HBLS persons matched ≥1 HGB person
     (145 unambiguous) → `link_hbls_hgb_candidates.csv`;
  b. **transitive** — if HBLS person *X* ≈ HLS bio *H* (Stage 1) and HGB person
     *P* ≈ *H* (existing `link_candidates_hls.csv`), then *X*↔*P* is implied —
     189 pairs → `link_hbls_hgb_transitive.csv`.
     These shared-HLS links are the highest-confidence cross-links and need the
     least review. Next: run `--all` to extend beyond Basel.

  *(Counts are post-`given_ratio`; see "Given-name gate" below. The direct pass
  yields fewer rows but **more** unambiguous ones — 139 → 145 — because the
  false alternatives that made a person ambiguous are gone. The transitive pass
  halves, since it inherits the HGB↔HLS edges that the fix pruned most heavily;
  that drop is not independently sampled yet.)*

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

*Result (Basel slice):* 2,458 components (size ≥ 2) → **1,909 conflict-free
cross-corpus identities** (`identity_clusters.csv`), **2,031 carrying a GND id**,
70 spanning all three source corpora (HBLS+HGB+HLS). 288 components are flagged
for review (177 multi-HGB homonyms, 76 birth-spread, 39 multi-HBLS, 19 multi-GND,
15 each multi-HLS/Wikidata) — exactly the cases the guards are meant to catch.

Every number here improved through the two fixes below: clean identities
1,782 → 1,894 (given-name comparison) → **1,909** (authority-edge audit),
flagged 422 → 302 → **288**. Removing false edges both merges *more* (records no
longer pulled into a homonym's component resolve cleanly) and conflicts *less*.

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

*Result (Basel slice):* 2,458 clusters → **2,167 merged persons**
(`merged_persons.json`, flat summary in `merged_persons.csv`), 2,143 with life
dates, 1,848 with a GND id, 1,334 with occupations, 379 with publications, 33
spanning all three source corpora. 291 go to review. All corpus joins resolve
(0 dangling members). Names come from HLS for 1,836 and HBLS for 331.

**HGB-under-resolution promotion.** A cluster whose *only* conflicts are HGB-side
(`multi_hgb` / `hgb_key_ambiguous`) with every HGB mention year inside the life
span (birth − 5 … death + 15) is one person the register mentions across several
dossiers, not a bad merge — so it is promoted to `merged`, the benign flags moved
to an `auto_resolved` field for audit. On the full corpus this moved **88 records
review → merged (335 → 247 review)**; homonym clusters with an out-of-span HGB
record (`TRIM_HGB`) stay in review. `../build_review_worksheet.py` triages the
remaining queue into actions.

**Given-name gate.** Merged records are re-scored on the common prefix of
**all** given tokens (particles and HLS noble epithets stripped, so "Escher vom
Luchs" does not leak in); below `--name-min` (default 0.6) the cluster is
flagged `name_disagreement` instead of merged. A missing middle name does not
count against a cluster, a conflicting one does.

This check originally ran only here, and it surfaced a defect in the shared
matcher: `link_hls.split_name` and its four call sites all compared `toks[0]`
alone, so "Hans Ulrich" and "Johann Jakob" scored a perfect 1.00 (both
canonicalise to `johann`) — precisely the distinction that separates brothers
and cousins inside one Basel patrician family. The comparison is now fixed at
source (`given_key` / `given_ratio` in `link_hls.py`, `--given-mode first`
restores the old rule for A/B work), so Stages 1–2 and both GND tiers no longer
generate that class of link. Measured on the HGB↔HLS pass, the old rule
produced 4,423 candidate rows against 3,303 under the fix; of the 1,060 pairs
it accepted and the fix rejects, **863 had been scored high-confidence**, and a
20-pair random sample of those was 20/20 genuine mis-matches — e.g. HGB *Hanns
Ludwig Wettstein* ⇄ HLS *Johann Rudolf Wettstein*, HGB *Hanns Lux Burkhardt* ⇄
HLS *Johann Balthasar Burckhardt*, both scored 1.00 by the old rule.

The gate is now a pure regression backstop: it flags 21 clusters, **none of
them on the name check alone** (347 → 51 → 0 uniquely-caught, as the two root
causes below were fixed). It costs nothing to keep and will catch the defect
class if it ever returns.

**Authority-edge audit** *(`../audit_authority_edges.py`)*. Stage 3 treats a
shared GND/Wikidata id as its strongest signal — two records on the same
authority node merge transitively with no name or date check. For HGB records
those ids are not independently sourced: `enrich_wikidata.py` assigns them
straight from the HLS article id (`p["wd"] = facts[p["hls"]["id"]]`), which
`apply_hls_links.py` picked out of `link_candidates_hls.csv`. So every HGB
authority edge rested entirely on one HGB↔HLS name match, and if that match was
wrong two different people fused silently.

The audit re-derives what `apply_hls_links.py` would accept from the current
candidates and classifies each baked-in link as confirmed / changed / revoked.
First run: of 809 HGB persons carrying an HLS link, **169 were revoked and 5
changed — 21.5% unsupported**, 171 of them carrying a GND/Wikidata id and **94
also propagating kinship** into the corpus and the family trees.

Root cause was an idempotency bug: `apply_hls_links.py` only ever *set* `hls`
and never cleared it, so a link that stopped being accepted stayed baked in
permanently. It now clears `hls`/`wd`/`kin` for persons whose link no longer
holds (both in `persons_resolved.json` and in `families_graph.json`), and the
audit re-runs clean at **796/796 confirmed, 0 unsupported**.

Two independent signals agree in the audit — re-derivation from the fixed
candidates, and the given-name check — which is why `links failing the
given-name check` and `unsupported links` both reach 0 together.

Still to do:
- **Rebuild `kin`** — `link_wikidata_kin.py` could not complete (WDQS returned
  504s). Stale kinship was *removed* by the `apply_hls_links.py` fix, so the
  data is correct-but-incomplete; the 5 "changed" links are the ones whose
  kinship most warrants recomputation.
- ~~Surface the merged records in the site~~ *(done)* — `make_persons_web.py`
  trims `merged_persons.json` to a 2.7 MB `persons_web.json` (tracked) and the
  **Identitäten** tab (`identitaeten.html`) renders it: search over name,
  occupation, place and work title; filters for tri-corpus / GND / publications
  / occupation / attested in the Grundbuch; and every card links back to its
  HBLS scan page, HLS article, GND, Wikidata and VIAF.

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


## Full-corpus rollout  *(done)*

Stage 1 and GND Tier 0 always ran corpus-wide. What was Basel-scoped was Stage 2
(`--all`) and GND Tier 1 (bulk-dump mode, see GND_LINKING_PLAN.md).

| | Basel slice | full corpus |
|---|---|---|
| Stage 2 HBLS↔HGB persons matched | 398 | **1,068** |
| ...unambiguous | 145 | **431** |
| Stage 2 transitive pairs | 189 | **796** |
| GND Tier 1 persons matched | 345 | **2,422** |
| ...unambiguous | 320 | **1,916** |
| Stage 3 clusters (size ≥ 2) | 2,458 | **3,723** |
| Stage 3 conflict-free multi-corpus | 1,909 | **2,003** |
| Stage 3 carrying a GND id | 2,031 | **3,319** |
| Stage 3 spanning all 3 corpora | 70 | **85** |
| Stage 4 merged persons | 2,167 | **3,388** |
| ...with life dates | 2,143 | **3,312** |
| ...with a GND id | 1,848 | **3,068** |
| Stage 4 review queue | 291 | 335 |

The Stage 4 name gate still uniquely catches nothing (26 flagged, 0 on the name
check alone), so the corpus-wide expansion did not reintroduce the defect class.

**Tier 2 enrichment rolled out too** (`gnd_enrich.py --dump`). It reads the GND
records from the same bulk dumps, falling back to the API only for accepted ids
outside both slices — in practice **3 of 3,362**, since Tier 0 ids arrive via
Wikidata and can be any GND. `gnd_enrichment.json` grows 1,813 → **3,362**
records (2,526 with roles, 3,249 with `sameAs`, 683 with publications), lifting
coverage of the merged output's 3,343 GND ids from 52% to **92%**.

Re-running Stage 4 on it:

| Stage 4 attribute | Basel | corpus, pre-Tier-2 | corpus, final |
|---|---|---|---|
| merged persons | 2,167 | 3,388 | **3,388** |
| with occupations | 1,334 | 1,355 | **2,426** |
| with publications | 379 | 374 | **602** |
| with places | — | — | **1,701** |
| with external ids (VIAF/DB/ISNI/LC) | — | — | **2,975** |

Publications are the only part still fetched per id, from the separate
lobid-resources index.
