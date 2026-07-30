# HGB Basel — MCP Server

> ⚠️ **Alpha test** — This endpoint is available at `https://tei.dh.unibe.ch/mpc/eos` for testing purposes. Configuration and availability may change.

An [MCP](https://modelcontextprotocol.io) server that exposes the Historisches Grundbuch Basel (HGB) corpus for use with MCP-compatible clients.

## Quick start (alpha test endpoint)

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "eos": {
      "url": "https://tei.dh.unibe.ch/mpc/eos"
    }
  }
}
```

Available tools: `corpus_stats`, `search_persons`, `get_document`, `get_dossier`, `search_text`, `get_persons_in_year_range`, `get_cooccurrences`, `list_dossiers`, `identity_stats`, `search_identities`, `get_identity`, `get_identity_by_authority`, `get_identities_in_year_range`.

## Architecture

```
hgb_full_*.xml  ──► build_db.py ──► hgb.db (SQLite + FTS5)
                                         │
                                    server.py  (FastMCP / HTTP SSE)
                                         │
                              http://<host>:8000/sse
```

The 800 MB XML is parsed once into a ~100 MB SQLite database. The server then runs stateless queries against it.

## Local setup

### 1. Install dependencies

```bash
cd mcp_server
pip install -r requirements.txt
```

### 2. Build the database

```bash
python build_db.py --xml ../hgb_full_26_05_29_05.xml --db hgb.db
```

This takes ~10 minutes and produces `hgb.db`. Run it once; repeat only when the XML changes.

Then load the cross-corpus identities into the same database:

```bash
python build_identities.py --json ../merged_persons.json --db hgb.db
```

This takes under a second and only touches the `identities` / `fts_identities`
tables, so it can be re-run after every pipeline run without re-parsing the XML.

### 3. Start the server

```bash
python server.py --db hgb.db --host 0.0.0.0 --port 8000
```

### 4. Connect a client

Add to your `claude_desktop_config.json` (or equivalent):

```json
{
  "mcpServers": {
    "hgb": {
      "url": "http://<server-ip>:8000/sse"
    }
  }
}
```

Or for Claude Code:
```bash
claude mcp add hgb --transport sse --url http://<server-ip>:8000/sse
```

---

## Docker deployment (recommended for self-hosting)

### Build image

```bash
docker compose build
```

### First-time: build the database

```bash
# Copy XML to /data/hgb/ on the server, then:
docker run --rm \
  -v /data/hgb:/data \
  hgb-mcp \
  python build_db.py --xml /data/hgb_full_26_05_29_05.xml --db /data/hgb.db

# then load the cross-corpus identities into the same file
docker run --rm \
  -v /data/hgb:/data \
  hgb-mcp \
  python build_identities.py --json /data/merged_persons.json --db /data/hgb.db
```

### Run

```bash
docker compose up -d
```

Update `/data/hgb` in `docker-compose.yml` to match the actual path on the server.

### Reverse proxy (nginx, optional but recommended)

```nginx
server {
    listen 443 ssl;
    server_name hgb-mcp.example.unibe.ch;

    location / {
        proxy_pass         http://localhost:8000;
        proxy_http_version 1.1;
        # Required for SSE
        proxy_set_header   Connection '';
        proxy_buffering    off;
        proxy_cache        off;
        chunked_transfer_encoding on;
    }
}
```

---

## Available tools

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

### Cross-corpus identities

The tools above return raw HGB **mentions** — one row per time a name appears in
a document. These return resolved **people**: one record per real person, merged
across the HGB, the printed *Historisch-Biographisches Lexikon der Schweiz*
(HBLS, 1921–34) and its online successor (HLS), keyed to GND and Wikidata, each
carrying a `sources[]` array back to every contributing corpus. Built by
`build_identities.py` from Stage 4 of the linking pipeline
(see [`../hbls-extraction/DEDUP_PLAN.md`](../hbls-extraction/DEDUP_PLAN.md)).

| Tool | Description |
|------|-------------|
| `identity_stats` | Counts: resolved people, with GND/Wikidata, in all three corpora |
| `search_identities(query, limit, corpus, with_gnd)` | FTS over name, occupation, place and work title; optional corpus / has-GND filters |
| `get_identity(identity_id)` | Full record: life dates, occupations, places, publications, dossiers, sources |
| `get_identity_by_authority(scheme, value)` | Look up by `gnd`, `wikidata`, `hls` or `viaf` id |
| `get_identities_in_year_range(year_from, year_to, limit)` | People whose life span overlaps the window |

Current contents: **3,388** resolved people — 3,068 with a GND id, 1,609 with a
Wikidata QID, 2,426 with occupations, 602 with recorded works, 418 attested in
the HGB land register, 38 in all three corpora.

If the identity tables have not been built, these tools return an explanatory
error rather than failing; the HGB tools are unaffected.

## Available resources

| URI | Description |
|-----|-------------|
| `hgb://stats` | Corpus statistics (JSON) |
| `hgb://dossiers` | All dossiers (JSON) |
| `hgb://document/{doc_id}` | Single document (JSON) |
| `hgb://identity/{identity_id}` | Single resolved person (JSON) |
