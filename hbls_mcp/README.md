# HBLS MCP Server

Exposes 137,038 merged historical person records from the Historisches Grundbuch
Basel (HGB), ca. 1400–1700, via the Model Context Protocol (MCP).

Each record is a deduplicated aggregation of mentions across HGB dossiers,
cross-linked to:

- **HLS** — Historical Dictionary of Switzerland (809 persons)
- **Wikidata** — QID, birth/death, occupations (768 persons)
- **GND** — via Wikidata (626 persons)

## Quick start

```bash
# 1. Build the SQLite database (one-time)
python build_db.py --json ../persons_resolved.json --db hbls.db

# 2. Start the server
python server.py --db hbls.db --port 8003

# 3. Connect MCP clients to http://localhost:8003/sse
```

Or with Docker:

```bash
# Build image
docker build -t hbls-mcp .

# Run (persons_resolved.json is at ../persons_resolved.json from this dir)
docker run --rm -v /path/to/data:/data -p 8003:8003 hbls-mcp \
  python build_db.py --json /data/persons_resolved.json --db /data/hbls.db

# Start server
docker run --rm -v /path/to/data:/data -p 8003:8003 hbls-mcp

# Or use docker-compose:
docker-compose up -d
```

## Endpoints (MCP tools)

| Tool | Description |
|---|---|
| `corpus_stats` | Corpus counts: persons, has_hls, has_wikidata, has_gnd, year_range |
| `search_persons` | FTS5 full-text name search, with fuzzy prefix fallback and year filters |
| `get_person` | Full record by integer id |
| `get_by_hls` | Full record by HLS ID (e.g. "025221") |
| `get_by_wikidata` | Full record by Wikidata QID (e.g. "Q4219116") |
| `get_persons_in_year_range` | Persons active in a given year window |

## Schema

Each person record:

```json
{
  "id": 2,
  "name": "Jacob Keller",
  "variants": ["Jacob Keller", "Keller Jac", "..."],
  "mention_count": 103,
  "dossier_count": 40,
  "year_from": 1510,
  "year_to": 1692,
  "dead_year": 1591,
  "occupations": ["metzger", "rebmann", "..."],
  "titles": ["Mr .", "J ."],
  "families": ["Frau"],
  "locations": ["von Nüwiler", "von Rewiler", "..."],
  "orgs": [],
  "hls": {
    "id": "025221",
    "url": "https://hls-dhs-dss.ch/de/articles/025221/...",
    "title": "Jakob Keller",
    "rel": "overlap"
  },
  "wd": {
    "qid": "Q4219116",
    "birth": 1568,
    "death": 1631,
    "occupations": ["Schriftsteller", "..."],
    "gnd": "122889576"
  },
  "kin": []
}
```

## Port

Default: `8003`. Configure with `--port`.

## Performance

- FTS5 search: ~0.2–2.5 ms for typical queries
- 137,038 records, ~50 MB SQLite database
- WAL mode enabled; concurrent reads safe
