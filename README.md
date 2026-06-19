# Historisches Grundbuch Basel (HGB)

A web-based exploration tool for person mentions and property records in the historical land register of Basel, ca. 1400–1700. Developed at the Universities of Bern and Basel.

## Pages

| Page | Description |
|------|-------------|
| [`index.html`](index.html) | Searchable index of all persons, filterable by name, year, and occupation |
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
- `persons_index.json` / `persons_resolved.json` — pre-built indexes for the UI
- `build_data.py` — rebuilds the JSON indexes from the CSV/XML sources

## Deployment

The site is static HTML — no build step required. Served via GitHub Pages (`_config.yml`).
