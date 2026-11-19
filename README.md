# Historisches Grundbuch Basel (HGB)

A web-based exploration tool for person mentions and property records in the historical land register of Basel, ca. 1400–1700. Developed at the Universities of Bern and Basel.

## Pages

| Page | Description |
|------|-------------|
| [`index.html`](index.html) | Searchable index of all persons, filterable by name, year, and occupation |
| [`persons_sparql.html`](persons_sparql.html) | Live person lookup against the Economies of Space SPARQL endpoint — mention counts, year ranges, roles, and co-appearing names |
| [`map.html`](map.html) | Property map — dossiers plotted on a modern basemap, coloured by person count, date range, or archival source |
| [`korrelationsanalyse.html`](korrelationsanalyse.html) | **Korrelationsanalyse** — statistical pattern analysis of the corpus: comparability transforms, correlation matrix, PCA, document-type clusters, event co-occurrence, and the centre/periphery spatial gradient |
| [`centre_periphery.html`](centre_periphery.html) | Interactive centre/periphery map — value vs. in-kind obligations per geolocated dossier (linked from the Korrelationsanalyse page) |
| [`viz.html`](viz.html) | Occupation visualisations — trajectories, co-occurrence, and frequency charts |
| [`movements.html`](movements.html) | **Personenbewegungen** — two-mode movement map on the historical Situationsplan Basel 1862 |
| [`jahrrechnungen.html`](jahrrechnungen.html) | **Jahrrechnungen** — the Basel city accounts 1535–1610 (GAMS Graz) cross-linked with HGB persons: cited bookings, street-level and corpus-level candidates on a map, the geo-referenced bailiwick accounts |

## Personenbewegungen

The movement map supports two modes:

**Personensuche** — search for up to 10 persons by name or ID. Each person is assigned a colour; their trajectory is drawn as a polyline with role-coded markers (▲ Anfang / ● Präsenz / ▼ Ende). A 30-year sliding window highlights the active period; an animate button steps through time automatically.

**Heatmap** — plots all persons simultaneously as a density layer. Supports two views:
- *Gleitendes Fenster* — 30-year moving window
- *Kumulativ* — accumulates all events from 1400 up to the selected year

### Input CSV

The movement map reads `movements.csv`. Expected columns:

| # | Field | Description |
|---|-------|-------------|
| 1 | `person_id` | Unique person identifier |
| 2 | `name` | Normalised name |
| 3 | `coordinates` | `"lat,lon"` (WGS84) or LV95 Swiss coordinates |
| 4 | `year` | Year of the event |
| 5 | `event_role` | One of `start`, `present`, `end` |

## Data & Build

### Source corpus

The name list is built from the street-split BeNASch XML published in
[DHBern/economies-of-space-automatically-annotated-data](https://github.com/DHBern/economies-of-space-automatically-annotated-data)
(`street_data/street_HGB_1_001.xml` … `street_HGB_1_229.xml`, 120 files, 75,447
documents, release 0.3.0 of 2026-09-25). Clone that repository next to this one
(or point `$HGB_STREET_DIR` at its `street_data/` folder); every build script
finds it through `hgb_corpus.py`, which streams the street files and presents
each document with its dossier metadata (LV95 point, address, dossier type —
these sit on the `<collection>` element in the new layout) in one uniform dict.
The earlier single-file export `hgb_full_*.xml` is still readable through the same
module, but is no longer the reference.

### Person pipeline

| step | script | output |
|---|---|---|
| 1 | `extract_persons.py` | `persons.csv` (one row per named person reference: name, year, dossier, occupation text/norm/OhdAB, title, family relation, location, affiliation, deceased marker, event roles, page image URL — gitignored, regenerable), `documents.csv` (one row per register card with its page images, gitignored) and `dossiers.csv` (one row per property: coordinates, address, type, street, history, doc count, years, sources) |
| 2 | `build_data.py` | `persons_resolved.json` (dossier-scoped identity resolution → person index for `index.html`), `guild_data.json` |
| 3 | `build_families.py` | `families_graph.json`, `families_index.json` (kinship edges from the `family` / inheritance event groups) |
| 4 | `link_hls.py` → `apply_hls_links.py` | `link_candidates_hls.csv` → `hls` field on persons and tree nodes |
| 5 | `enrich_wikidata.py`, `link_wikidata_kin.py` | `wd` (QID, dates, GND, kin) and `kin` cross-references |
| 6 | `dedupe_persons.py`, `dedupe_corpus.py --apply`, `dedupe_offices.py --apply`, `dedupe_rare_surnames.py --apply` | deduplicated `persons_resolved.json` |
| 6b | `link_bli_hgb.py` → `dedupe_spelling.py --apply`, repeated until the dry run merges nothing | spelling variants merged on the evidence of BLI owners, the street-level index and shared name variants (see below) |
| 7 | `build_families.py`, `apply_hls_links.py`, `link_wikidata_kin.py`, `link_hls_families.py` | family data refreshed from the deduplicated index |
| 8 | `build_roles.py`, `build_movements.py`, `build_flowfield.py`, `build_prices.py`, `build_dossiers_geo.py` | `roles_data.json`, `movements.csv`, `flowfield.json`, `prices.json`, `dossiers_geo.json` |
| 9 | `link_hbls_hgb.py --all`, `build_identity_clusters.py`, `build_merged_persons.py`, `make_persons_web.py` | cross-corpus identities (`merged_persons.json`, `persons_web.json`; see `hbls-extraction/DEDUP_PLAN.md`) |

Figures of the current build (street corpus 0.3.0): 238,957 person mentions in
75,447 documents → 152,250 resolved names → 137,454 persons after the name-based
dedupe passes → **127,089 persons** after `dedupe_spelling.py`;
614 carry an HLS/Wikidata link (1,651 confident links before dedupe, from 3,253
candidates); 3,694 geolocated dossiers; 14,934 persons with movement between
≥2 properties; 3,631 cross-corpus identities (525 attested in the register).

### Cross-check against *Basler Liegenschaften 1400–1700 Interaktiv*

[Basler Liegenschaften Interaktiv](https://dhbern.github.io/basler-liegenschaften-interaktiv/)
(BLI, repository DHBern/basler-liegenschaften-interaktiv) builds the ownership
history of every property from the same register cards and resolves its 179,982
actors per property and its neighbours. `link_bli_hgb.py` joins that actor list
with the two eos lists — the city-wide `persons_resolved.json` and the
street-level `hgb_street_persons.json` — and reports where the three
resolutions contradict each other. BLI is only read; nothing is written there.

```bash
python3 extract_persons.py            # persons.csv, documents.csv
python3 build_hgb_street_persons.py   # hgb_street_persons.json (optional)
python3 link_bli_hgb.py               # BLI from a sibling checkout, $BLI_DIR or --fetch
```

| file | content |
|---|---|
| `link_bli_hgb.csv` | one row per named BLI person actor (124,890): dossier, owner documents, the eos persons and street persons it resolves to |
| `bli_doc_crosswalk.csv` | 1,864 register cards that the corpus re-issued under a new id (page order corrected), matched by their page images |
| `bli_hgb_findings.csv` | the discrepancies, typed, with the side the error most likely sits on (18,911 at the first comparison, 9,878 now) |
| `dedupe_spelling_candidates.csv` | pairs of city-wide persons whose names differ only in spelling and that a BLI owner or a street-level person holds as one, or that carry the same name variant in one dossier at the same time (gitignored: tied to one state of the index) |
| `bli_hgb_report.md` | counts, a description and examples per finding type |

The join is exact rather than fuzzy: an owner actor carries its documents, so its
name variants are looked up among the eos mentions of those very documents
(99.5 % of 91,897 owner references are found there); actors without documents
are placed through BLI's id order, which follows the dossiers. 99.7 % of the
named person actors are linked.

What the comparison showed, and what has been done about it. The figures in
brackets are those of the first comparison, on the index of 136,470 persons.

- **Spelling variants not merged** — one BLI owner was two or more eos persons
  whose names differ only by spelling or HTR noise (*Emanuel Schönauwer /
  Schönawer / Schönauer* on one property in the same years; 6,902 person
  pairs), and the street-level index held 3,430 persons that the city-wide
  index split. *Fixed:* `dedupe_spelling.py` merges such pairs under the guards
  of the index — one lifespan of 80 years, nobody joins more than 15 years
  after the group's earliest death, different HLS/Wikidata identities never
  merge, nothing joins an HLS-linked person from outside that person's known
  life. On the current build: 137,454 → **127,089 persons** in five rounds; 690
  pairs stay apart because a guard refuses them.
- **Same name, same dossier, same years, two persons** [1,107 groups]. *Fixed
  where the evidence is clean:* the pair is a third source for
  `dedupe_spelling.py` when the shared variant is a full name, the canonical
  names are spelling variants and neither person is first mentioned after the
  other is called deceased. 676 groups remain: bare names, differing given
  names, death splits, and 241 pairs a guard refuses.
- **Persons spanning more than a lifespan** [62, all HLS-linked, up to 187
  years]. *Fixed:* `link_hls.date_relation` only links a cluster whose whole
  mention span fits the life (not before birth − 5, not beyond death + 60, not
  as living more than 15 years after a known death, not called deceased more
  than 5 years before it), `dedupe_persons.py` takes what lies inside the life
  envelope instead of everything overlapping it, and every later pass asks
  `link_hls.fits_life` before merging into an HLS-linked person. No person
  exceeds 80 years outside a known life any more; 15 do inside one, through
  post-mortem mentions. The stricter rule costs links: 1,651 confident ones
  instead of 2,193, on 449 HLS articles instead of 472.
- **Bare given names merged across generations inside a dossier** [34 pure
  bare names, 30 attached to a fuller name]. *Fixed:* `build_data.person_runs`
  replaces the fixed 80-year bins. A bare name starts a new person after 15
  years of silence, and is attached to the single fuller name of its dossier
  only within 15 years of it. The threshold is measured against BLI's owners:
  consecutive mentions of one bare name in a dossier are the same owner in
  86 % of cases when 0–4 years apart, 46 % at 15–19, never from 50 on. Full
  names are one owner in 97 % or more up to 40 years of silence and still only
  obey the lifespan; 50 cases where BLI has same-named owners more than 40
  years apart remain reported.
- **Bookkeeping in `build_data.py`.** *Fixed:* the death split works on the
  mentions, so Σ `c` equals the 238,957 mentions (it was 241,083); `dos` lists
  every dossier instead of the first 30, and `d` counts dossiers, not
  (dossier, name) pairs.
- **On the BLI side** (reported, nothing changed there): it is built from the
  earlier corpus release (1,864 cards with the old page order, 174 cards and
  19 dossiers missing), 53 owner actors run over more than a lifespan or past
  a recorded death, 494 corpus dossiers with 3,337 documents appear only as
  "Ghost Record", and 322 placeholder actors are named "None of …".

After a rebuild of the index, run the pair until it is stable:

```bash
python3 link_bli_hgb.py && python3 dedupe_spelling.py            # dry run
python3 dedupe_spelling.py --apply && python3 link_bli_hgb.py    # repeat while clusters > 0
```

### One command

`./rebuild.sh` runs the whole pipeline in the order above — `./rebuild.sh --list`
shows the stages (`extract data links dedupe spelling families identities srbas
report`), `./rebuild.sh links` starts at a stage, `./rebuild.sh links dedupe`
runs a range.

### HLS data without the private export

The HLS metadata export (`hls_articles.csv`) that the linkers were written
against is not redistributable. `build_hls_table.py` rebuilds the columns the
linkers use from Wikidata (every HLS biography carries the HLS id as property
P902) into `hls_bios_wikidata.csv` (tracked: 25,157 biographies, 23,877 with
life dates, 22,846 with a GND id). `link_hls.default_hls()` returns the private
export when present and this table otherwise, so the link stage runs from public
data. The export is looked for in `$HLS_ARTICLES`, then in
`private_inputs/hls_articles.csv` (gitignored — it must not be committed). Caveat: the given name is taken from the Wikidata label, which for 339 of the
472 linked articles is a single token ("Johannes Wettstein") where the export's
`bio.first_name` may carry the full form; since the matcher only compares the
common prefix of the given names, such an article can absorb register persons
that differ in their second given name (105 of the 472 linked articles collect
more than one given-name sequence). Re-run `link_hls.py` with the private export
to tighten this. Two more things the table does not have: the article text — so
the text-mining passes `extract_genealogy.py`, `extract_spouses.py` need the real
export — and the family articles, for which `link_hls_families.py` falls back to
`hls_family_links.csv`, the surname → HLS family article links accepted on an
earlier run.

Likewise `hbls-extraction/rebuild_hbls_persons.py` recovers the link-ready HBLS
person records from the tracked `hbls_web.json` when the PDF-derived
`hbls_persons.json` is absent, and `freeze_authority_edges.py` writes the
HBLS/HLS/GND/Wikidata side of the identity clusters out of `merged_persons.json`
(`authority_edges.csv`) so that a rebuild of the land-register persons keeps
the lexicon-and-authority identities and only re-attaches the HGB records.

### Correlation analysis pipeline

Statistical pattern analysis of the full corpus (75,447 documents). The pipeline is
script-based and reproducible from the source XML:

1. `extract_features.py` — streams the street files (via `hgb_corpus.py`) and emits
   `features_doc.parquet`, a document-level feature matrix (75,447 × 154). Every
   count is also exposed as a length-normalised rate, money is unified to a single
   base unit (Schilling; **Gulden/Taler rates are approximate and editable** at the
   top of the file), and it adds participant-structure, temporal (25-year bins),
   event-combination, status, and ratio columns.
2. `analyze_features.py` — correlation matrix (Spearman, residualised against
   archive + era), PCA, KMeans document-type clusters, event co-occurrence (PMI/lift),
   and Moran's I spatial autocorrelation → `analysis_report.md` + `figures/`.
3. `centre_periphery.py` — centre/periphery spatial analysis of value and in-kind
   obligation share → `centre_periphery.csv` (read by `centre_periphery.html`) + figures.

Results, methodology, and caveats are presented on the
[Korrelationsanalyse](korrelationsanalyse.html) page. The headline spatial finding:
transaction value falls and in-kind obligations rise from the urban core to the
periphery (Spearman ρ = −0.155 / +0.107, both p < 1e-9).
- `build_sparql_index.py` — **run on demand** to pre-build `persons_sparql_index.json`, a cached index for `persons_sparql.html`. The page works without it by querying the SPARQL endpoint live, but the cache makes searching instant. Depends on endpoint availability; re-run when the graph is updated.

## SPARQL endpoint

`persons_sparql.html` and `build_sparql_index.py` query the Economies of Space LOD endpoint at `https://sparql-gdb.lod4hss.org/eos` ([graph docs](https://github.com/history-unibas/economies-of-space-lod)). When no cached index is present the page falls back to live queries, with a 20 s client-side timeout so an unreachable endpoint surfaces a clear error rather than hanging.

### Person roles

`PERSON_ROLES` in `build_sparql_index.py` is the single source of truth for which event roles denote a person. The page needs the same set twice — for its live-SPARQL filter and for its role dropdown — and is served statically, so rather than fetching the list at runtime the two regions are generated into the HTML between `BEGIN/END generated:` markers:

```bash
python3 build_sparql_index.py --sync-page     # rewrite the page from PERSON_ROLES
python3 build_sparql_index.py --check-page    # exit non-zero if it has drifted
```

Edit the Python list, run `--sync-page`, commit both files. `tests/test_person_roles_sync.py` fails if they diverge.

## Jahrrechnungen der Stadt Basel 1535–1610 (srbas)

Cross-link of the Basel city accounts (GAMS Graz, `context:srbas`) with the HGB
persons and places. The edition has no person/place markup, so names are
recovered from the booking texts and places from the account hierarchy; see
[`srbas-extraction/README.md`](srbas-extraction/README.md) for the source, the
access URLs and the pipeline.

| file | what |
|---|---|
| `srbas-extraction/srbas_name_mentions.csv` | heuristic person-name mentions in 78,728 bookings, with citable GAMS URI |
| `srbas-extraction/srbas_account_places.csv` | the Ämter/Vogteien accounts geo-referenced via Wikidata (review column) |
| `build_hgb_street_persons.py` | street-level HGB person index from the DHBern annotated release (read-only input), HGB identity resolution applied per street → `hgb_street_persons.json` (gitignored) |
| `link_srbas_hgb.py` | srbas names → HGB persons: `link_srbas_hgb_candidates.csv` (corpus) and `link_srbas_hgb_street_candidates.csv` (street level, with coordinates) |
| `make_srbas_web.py` | joins mentions, booking excerpts, account places and both candidate tables into `srbas_web.json` for `jahrrechnungen.html` |
| `tests/test_srbas_names.py`, `tests/test_street_resolution.py` | inflection handling the match depends on; the street-scoped resolution rules |

## MCP server (alpha test)

**[Alpha test]** An MCP server endpoint is available at:

```
https://tei.dh.unibe.ch/mpc/eos
```

Add it to any MCP-compatible client:

```json
{
  "mcpServers": {
    "eos": {
      "url": "https://tei.dh.unibe.ch/mpc/eos"
    }
  }
}
```

The server provides access to the full HGB corpus (75,447 documents, ~204k person spans) via the following tools:

| Tool | Description |
|------|-------------|
| `corpus_stats` | Document/span/person/event counts and year range |
| `search_persons(query, limit)` | FTS search for person names (FTS5 syntax) |
| `get_document(doc_id)` | Full document: text, all spans, events |
| `get_dossier(dossier_id)` | All documents for a property, ordered by year |
| `search_text(query, limit)` | Keyword search over raw transcriptions with snippets |
| `get_persons_in_year_range(year_from, year_to, limit)` | Person mentions filtered by year |
| `get_cooccurrences(person_name, limit)` | Other persons in the same documents |
| `list_dossiers(limit)` | All properties with coordinates and year ranges |

And resources:

| URI | Description |
|-----|-------------|
| `hgb://stats` | Corpus statistics (JSON) |
| `hgb://dossiers` | All dossiers (JSON) |
| `hgb://document/{doc_id}` | Single document (JSON) |

For local development and self-hosting, see [`mcp_server/`](mcp_server/) and [`mcp_server/README.md`](mcp_server/README.md).

## Deployment

The site is static HTML — no build step required. Served via GitHub Pages; a `.nojekyll` file disables Jekyll processing so all files (including large data JSON) are served verbatim.
