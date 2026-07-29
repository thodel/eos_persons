# GND linking plan — lobid GND lookup, enrichment & deduplication

## Goal
Attach a **GND id** (Gemeinsame Normdatei) to our person candidates so that
(1) GND becomes a strong, authority-controlled identity key for deduplication
across HBLS / HLS / HGB / Wikidata, and (2) we can pull extra structured data —
roles (professions), external ids (VIAF, Deutsche Biographie, ISNI), biographical
notes, relations, and **publications** — onto the merged records.

## API analysis — lobid GND (https://lobid.org/gnd/api)

| Need | Endpoint / field |
|---|---|
| Search | `https://lobid.org/gnd/search?q=…&filter=type:DifferentiatedPerson&format=json&size=N&from=…` |
| Single record | `https://lobid.org/gnd/<gndIdentifier>.json` |
| Publications/works | `https://lobid.org/resources/search?q=contribution.agent.id:"https://d-nb.info/gnd/<id>"&format=json` |
| Reconciliation (review) | `https://reconcile.gnd.network/` (OpenRefine API) |

- **Query syntax**: Elasticsearch `query_string`, colon fields, boolean `AND/OR`.
  ASCII-folded name fields (`preferredName.ascii`, `variantName.ascii`) for OCR
  robustness. `filter=type:DifferentiatedPerson` excludes name-only stubs.
- **Person fields**: `gndIdentifier`, `preferredName`, `variantName`,
  `dateOfBirth`/`dateOfDeath` (messy strings: `"1670"`, `"um 1500"`,
  `"XX.XX.1788"` — parse leading 4-digit year), `placeOfBirth/Death/Activity`,
  **`professionOrOccupation` [{id,label}]** (roles), `gender`,
  `biographicalOrHistoricalInformation`, **`sameAs` [{id,collection}]** (Wikidata,
  VIAF, Deutsche Biographie, ISNI…), relations (`familialRelationship`,
  `relatedPerson`, `affiliation`). The GND record carries **no works** — those
  come from the separate lobid-resources index.
- **Limits/bulk**: no hard published rate limit; policy asks for a descriptive
  User-Agent and prefers bulk dumps for large jobs. → throttle + cache for the
  candidate set; use the full GND JSONL dump only if scaling to the whole corpus.

## Strategy — three tiers

### Tier 0 — transitive GND via HLS → Wikidata → GND  *(implemented: `../link_hbls_gnd.py`)*
The repo already bridges HLS → Wikidata (Wikidata stores the HLS id as **P902**)
and reads GND from **P227** (`enrich_wikidata.py`). Our Stage-1 HBLS↔HLS links
therefore yield GND for free: for every linked HLS id we run one batched WDQS
query and read back `qid`, `gnd` (P227), `viaf` (P214), Wikidata birth/death
(P569/P570) and occupations (P106). No lobid traffic; highest precision; also
**cross-validates** the HBLS↔HLS chain (Wikidata life dates must agree with ours).

*Result:* 2,319 GND links for **2,141 HBLS persons** (of 2,300 linked HLS ids,
2,108 carried a GND on Wikidata). The date cross-check flags each link
`ok` / `MISMATCH`: **1,518 ok**, 431 mismatch. Mismatches surface genuine
problems — mis-parsed HBLS date ranges (e.g. a 1-year "lifespan"), wrong family
member, or homonym — so `date_check == "ok"` is the auto-accept gate and
`MISMATCH` routes to review (and back-flags the suspect Stage-1 HLS link).

This cross-check is the most useful independent measure the pipeline has, since
it validates against Wikidata's dates rather than against our own scoring. It
is what confirmed the given-name fix (see DEDUP_PLAN.md, Stage 4): mismatches
fell 533 → 431 (−19%) while confirmed-good links held at 1,513 → 1,518 — bad
links removed, good links kept. It also sharpened the split by link confidence
to **12% mismatch for unambiguous score ≥ 0.9 vs 81% for weaker links** (was
13% vs 37%), so Stage-1 link strength is now a genuinely predictive gate rather
than a weak correlate.

### Tier 1 — direct lobid lookup for the remainder  *(done — `../link_hbls_gnd_lobid.py`)*
For HBLS persons not covered by Tier 0 and carrying ≥1 life year:
1. Query `preferredName.ascii`/`variantName.ascii` with `surname`+`given`,
   `filter=type:DifferentiatedPerson`, `size=10`.
2. Score each hit with the **same model** as Stages 1–2 (surname/given
   `SequenceMatcher` + birth/death ±4, floruit-in-span fallback); reuse
   `link_hls.py` helpers.
3. Accept only when name+dates uniquely identify one person (`n_candidates==1`,
   score ≥ threshold); else → review CSV. Date agreement is decisive (homonyms).

*Result (Basel slice, API mode):* of 3,327 dated persons unresolved by Tier 0,
**345 matched a GND (320 unambiguous)** — an ~10% hit rate that confirms GND's
modern/notable skew (floruit-only medieval persons are skipped by default; they
yield virtually no GND). Throttled lobid calls are cached under
`.lobid_cache/` so reruns are free.

#### Bulk-dump mode (`--dump`), required for the full corpus

One API request per person is fine for a 3.3k slice but means ~14k requests
corpus-wide, and lobid's usage policy prefers a bulk download at that size. Two
filtered requests fetch everything instead — a Swiss-area slice and an era
slice, unioned and deduplicated on `gndIdentifier`:

```bash
cd hbls-extraction
curl -sS -G -H 'Accept-Encoding: gzip' -H "User-Agent: <descriptive UA>" \
  --data-urlencode 'q=type:DifferentiatedPerson AND geographicAreaCode.id:"https://d-nb.info/standards/vocab/gnd/geographic-area-code#XA-CH"' \
  --data-urlencode 'format=jsonl' https://lobid.org/gnd/search -o gnd_dump_ch.jsonl.gz
curl -sS -G -H 'Accept-Encoding: gzip' -H "User-Agent: <descriptive UA>" \
  --data-urlencode 'q=type:DifferentiatedPerson AND (dateOfBirth:[1300 TO 1899] OR dateOfDeath:[1300 TO 1899])' \
  --data-urlencode 'format=jsonl' https://lobid.org/gnd/search -o gnd_dump_era.jsonl.gz

python3 ../link_hbls_gnd_lobid.py \
  --dump hbls-extraction/gnd_dump_ch.jsonl.gz,hbls-extraction/gnd_dump_era.jsonl.gz
```

197,781 + 900,087 records → 347 MB gzipped, ~1.42 M indexed name keys. Records
are blocked on the folded surname initial, which is lossless for the `sr ≥ 0.85`
gate because `ratio()` already returns 0 when initials differ.

**Neither slice alone suffices**, and this was measured rather than assumed. The
Swiss slice alone misses 84 of the 380 API-found Basel pairs — Swiss-relevant
people catalogued as "Deutschland" or "Land unbekannt" (e.g. *Grasser, Jonas*,
a perfect-score match). The era slice covers those. Validated on Basel, the
union reproduces **379 of the 380** API pairs and finds **479 additional** ones,
because the API query matched given-name *tokens* literally while the dump path
canonicalises first (so `Hans` ⇄ `Johann` surfaces as a candidate at all).

*Known boundary:* the one uncovered pair is a person who died in 1926 with no
birth date and a German area code, so falls outside both slices. HBLS was
published 1921–34, so its subjects can die into the 1930s; extending the era
slice to 1940 would close this, but that adds ~899k mostly-20th-century records
— roughly doubling index size and runtime to recover 0.26% of links. Not taken.

*Result (full corpus, dump mode):* see the rollout note at the end of
DEDUP_PLAN.md.

### Tier 2 — enrichment for accepted GND ids  *(done — `../gnd_enrich.py`)*
Pass `--dump` with the same slices as Tier 1 and the records come from disk:
only ids outside both slices need the API (3 of 3,362 on the full corpus).
*Result:* **3,362 enriched records** — 2,526 with roles, 3,249 with `sameAs`,
683 with publications — covering 92% of the GND ids in the merged output.

Per accepted `gndIdentifier`, read the record (from the dump, else fetch once
and cache) and pull
`professionOrOccupation` (roles), `sameAs` (VIAF / Deutsche Biographie / ISNI),
bio prose, places, relations; then one lobid-resources query for **publications**.

## Deduplication use
GND ids are the strongest merge key available. In the Stage-3 identity graph
(`DEDUP_PLAN.md`):
- add **GND edges**: any two of our records (HBLS / HGB / HLS / Wikidata)
  resolving to the same `gndIdentifier` collapse into one person;
- **cross-validate** existing links — GND `sameAs`→Wikidata must match our QID,
  GND dates must match ours; disagreement flags a bad earlier link instead of
  silently merging;
- the merged node then carries GND-sourced roles, publications and external ids
  as new attributes (the "add more data" goal), surfaced as chips in `index.html`
  next to the existing HLS/Wikidata links.

## Sequencing & safety
- **Basel slice first** (as in Stages 1–2), then `--all`.
- Tier 0 uses WDQS batched (≈500 ids/query) with the existing 429-backoff; Tier 1
  throttles lobid to ~1–2 req/s with on-disk caching of queries and records.
- Outputs (gitignored, regenerable): `../link_hbls_gnd.csv` (Tier 0),
  later `../link_hbls_gnd_candidates.csv` (Tier 1) and `gnd_enrichment.json`.

## Caveats
- **Coverage skews modern/notable** — GND is publication-driven; good for
  early-modern–modern Basel figures (printers, officials, scholars), sparse for
  undated medieval entries.
- **Homonyms** are the main precision risk → never accept on name alone.
- **Date noise** on both sides (GND `"um …"`, our OCR floruits) → parse leniently,
  prefer Tier 0 where an id already exists.
