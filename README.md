# Historisches Grundbuch Basel (HGB)

A web-based exploration tool for person mentions and property records in the historical land register of Basel, ca. 1400–1700. Developed at the Universities of Bern and Basel.

## Pages

| Page | Description |
|------|-------------|
| [`index.html`](index.html) | Searchable index of all persons, filterable by name, year, and occupation |
| [`persons_sparql.html`](persons_sparql.html) | Live person lookup against the Economies of Space SPARQL endpoint — mention counts, year ranges, roles, and co-appearing names |
| [`map.html`](map.html) | Property map — dossiers plotted on a modern basemap, coloured by person count, date range, or archival source |
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
- `build_sparql_index.py` — **run on demand** to pre-build `persons_sparql_index.json`, a cached index for `persons_sparql.html`. The page works without it by querying the SPARQL endpoint live, but the cache makes searching instant. Depends on endpoint availability; re-run when the graph is updated.

## SPARQL endpoint

`persons_sparql.html` and `build_sparql_index.py` query the Economies of Space LOD endpoint at `https://sparql-gdb.lod4hss.org/eos` ([graph docs](https://github.com/history-unibas/economies-of-space-lod)). When no cached index is present the page falls back to live queries, with a 20 s client-side timeout so an unreachable endpoint surfaces a clear error rather than hanging.

## MCP server

[`mcp_server/`](mcp_server/) exposes the HGB corpus to MCP-compatible clients (Claude and others) over HTTP/SSE, backed by a SQLite/FTS5 database built from the source XML. See [`mcp_server/README.md`](mcp_server/README.md) for setup.

## Deployment

The site is static HTML — no build step required. Served via GitHub Pages; a `.nojekyll` file disables Jekyll processing so all files (including large data JSON) are served verbatim.
