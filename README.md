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

- `persons.csv` — raw person mentions extracted from the XML source
- `hgb_full_26_05_29_05.xml` — full HGB source XML
- `dossiers_geo.json` — dossier-level geo-coordinates and person lists
- `persons_resolved.json` — pre-built person index for `index.html`
- `build_data.py` — rebuilds the JSON indexes from the CSV/XML sources

### Correlation analysis pipeline

Statistical pattern analysis of the full corpus (75,447 documents). The pipeline is
script-based and reproducible from the source XML:

1. `extract_features.py` — streams `hgb_full_26_05_29_05.xml` and emits
   `features_doc.parquet`, a document-level feature matrix (75,447 × 153). Every
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

## MCP server

[`mcp_server/`](mcp_server/) exposes the HGB corpus to MCP-compatible clients (Claude and others) over HTTP/SSE, backed by a SQLite/FTS5 database built from the source XML. See [`mcp_server/README.md`](mcp_server/README.md) for setup.

## Deployment

The site is static HTML — no build step required. Served via GitHub Pages; a `.nojekyll` file disables Jekyll processing so all files (including large data JSON) are served verbatim.
