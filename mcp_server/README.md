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

Available tools: `corpus_stats`, `search_persons`, `get_document`, `get_dossier`, `search_text`, `get_persons_in_year_range`, `get_cooccurrences`, `list_dossiers`, `identity_stats`, `search_identities`, `get_identity`, `get_identity_by_authority`, `get_identities_in_year_range`, `search_hgb_persons`, `get_hgb_person`.

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
python build_identities.py --json ../merged_persons.json \
                           --persons ../persons_resolved.json --db hgb.db
```

This takes about five seconds and only touches the person tables
(`identities`, `hgb_persons` and their FTS indexes), so it can be re-run after
every pipeline run without re-parsing the XML. Either source can be omitted
with `--json ''` or `--persons ''` to load just one.

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

## Design note — one server, not two

PR [#1](https://github.com/thodel/eos_persons/pull/1) ("Epic 13 — HBLS Knowledge
Graph MCP Server") proposed a second, standalone server in `hbls_mcp/` on port
8003, built from `persons_resolved.json`. It was declined in favour of extending
this server. The reasoning, recorded so it is not relitigated:

- **It contained no HBLS data.** Despite the name, its only source is
  `persons_resolved.json`, whose fields are `n, v, c, d, y, dead_year, occ, dos,
  tit, fam, loc, org, hls, wd, kin` — HGB land-register clusters. The actual
  *Historisch-Biographisches Lexikon der Schweiz* (27,838 extracted persons)
  appears nowhere in it. A client trusting the name would ask the "HBLS server"
  about a lexicon entry and get land-register clusters back.
- **Authority coverage was 0.58%** — 796 of 137,038 records carry any external
  link. The cross-corpus linking is what makes this data usable for research,
  and it was almost entirely absent from what the PR exposed.
- **It duplicated tool names.** `corpus_stats`, `search_persons` and
  `get_person` collide with this server's, so a client connected to both sees
  two different answers under one name.
- **It doubled the deployment.** A second container, port, healthcheck and nginx
  route, for data already reachable from the single alpha endpoint.

What the PR *did* have that this server lacked was search over the register's
deduplicated person clusters — `search_persons` here returns mentions, not
persons. That capability was kept: it is now `search_hgb_persons` /
`get_hgb_person` above, reading the same `persons_resolved.json`, in the same
database and process. So closing the PR cost no coverage.

Its 14 tests were not carried over verbatim; they assert structural facts about
a database this server builds differently (`>= 137_000` rows, negative BM25
scores). The ideas behind them were ported instead — see below.

## Tests

```bash
pip install -r mcp_server/requirements-dev.txt
python -m pytest mcp_server/tests -q      # from the repo root, or
python -m pytest tests -q                 # from mcp_server/
```

Test tooling lives in `requirements-dev.txt`, not `requirements.txt`, so the
Docker image does not carry pytest.

37 tests covering database structure, the identity and register-person queries,
and the tool layer. They build both person tables with the real
`build_identities.py` from small synthetic fixtures that mirror the production
JSON schemas, so the suite needs neither the 800 MB XML nor a prebuilt
database and runs in about a second.

One test opts into the real corpus via the `real_db` fixture and skips when
`merged_persons.json` is absent, so missing data costs one test rather than
silently skipping the suite.

`test_real_corpus_year_min_is_plausible` is a regression guard for a defect
this porting exposed and which is now fixed. GND writes decade-level
uncertainty as `149X`; a bare `\d{3,4}` search read that as the year 149, so
three identities reached the published corpus with 3-digit life dates
(Benedict May birth=149, Valentin Rebmann birth=152, Hans Conrad Griesser
death=169) — indistinguishable from real years once in the statistics.
`link_hls.year_of` now returns `None` for an imprecise date rather than
guessing at it, and Stage 4 has been rebuilt: `year_min` is 1100, no record
carries a 3-digit year, and every other figure is unchanged. The test fails
again if that parsing regresses.

## Updating the deployed server

The alpha endpoint at `https://tei.dh.unibe.ch/mpc/eos` runs from this
directory via Docker. The HGB tables come from the 800 MB XML and change
almost never; the identity tables change on every pipeline run and rebuild in
under a second, so a refresh does **not** need the XML.

`merged_persons.json` is tracked in git precisely so this works from a pull —
if it is missing on the host, `build_identities.py` has nothing to read and the
identity tools will keep returning "Identity tables not present".

```bash
# on the deployment host, in the repo checkout
git pull

# load the current identities into the live database
#   --db must point at the SAME hgb.db the container serves
#   (the compose file mounts /data/hgb -> /data, so it is /data/hgb/hgb.db)
docker run --rm -v /data/hgb:/data hgb-mcp \
  python build_identities.py --json /data/merged_persons.json \
                             --persons /data/persons_resolved.json --db /data/hgb.db

# if merged_persons.json is not already beside hgb.db, copy it there first:
#   cp merged_persons.json /data/hgb/merged_persons.json

# rebuild the image only if server code changed, then restart
docker compose build
docker compose up -d
```

Verify from any MCP client, or against the container directly:

```bash
docker run --rm -v /data/hgb:/data hgb-mcp python -c \
  "import db; db.set_db_path('/data/hgb.db'); print(db.identity_stats())"
```

Expected right now: 3,388 identities, 3,068 with a GND id, 38 in all three
corpora. `build_identities.py` drops and rebuilds only `identities` and
`fts_identities`, so re-running it is safe and never touches the HGB tables.

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

### Land-register persons

One row per **deduplicated name in the register** (~137,000), with spelling
variants and aggregated mention/dossier counts. Breadth over the HGB, where the
identity tools above are depth on the people resolvable across corpora. Loaded
by `build_identities.py --persons ../persons_resolved.json`.

| Tool | Description |
|------|-------------|
| `search_hgb_persons(query, limit, year_from, year_to)` | Name/variant/occupation search; bare fragments retry as a prefix search |
| `get_hgb_person(person_id)` | Variants, occupations, titles, families, locations, dossier ids |

Three levels of granularity, easily confused — pick by the question asked:

| Question | Tool |
|---|---|
| Where does this name occur in the documents? | `search_persons` (mentions) |
| Who appears in the land register? | `search_hgb_persons` (register persons) |
| Who was this person, across all our sources? | `search_identities` (resolved people) |

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
