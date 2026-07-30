"""
server.py — HGB Basel MCP server (HTTP/SSE transport)

Start:
    python server.py --db hgb.db --host 0.0.0.0 --port 8000

MCP clients connect to:
    http://<host>:8000/sse
"""

import argparse
import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

import db as db_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="HGB Basel",
    instructions=(
        "This server provides access to the Historisches Grundbuch Basel (HGB), "
        "a corpus of historical land-register documents from Basel, ca. 1400–1700. "
        "Documents contain tokenised medieval German text annotated with persons, "
        "dates, money amounts, and legal events (payments, transfers, etc.). "
        "Use search_persons to find person mentions; get_document for full detail; "
        "search_text for keyword search across the raw transcriptions. "
        "Separately, the identity tools (search_identities, get_identity, "
        "get_identity_by_authority) expose resolved *people* rather than raw "
        "mentions: one record per person merged across the HGB, the printed "
        "Historisch-Biographisches Lexikon der Schweiz (HBLS) and its online "
        "successor (HLS), keyed to GND and Wikidata, with provenance back to "
        "each source. Use those when the question is about a person; use "
        "search_persons when it is about where a name occurs in the documents."
    ),
)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def corpus_stats() -> dict:
    """Return high-level statistics about the HGB corpus."""
    return db_module.db_stats()


@mcp.tool()
def search_persons(query: str, limit: int = 20) -> list[dict]:
    """
    Full-text search for person mentions by name.

    Args:
        query: Name or name fragment (SQLite FTS5 syntax, e.g. "Bulacher*").
        limit: Maximum number of results (default 20, max 200).

    Returns a list of person mentions with document metadata
    (doc_id, year, dossier_id, source, location, confidence).
    """
    limit = min(limit, 200)
    results = db_module.search_persons(query, limit)
    return results


@mcp.tool()
def get_document(doc_id: str) -> dict:
    """
    Fetch a single document by its ID, including the full transcription text,
    all NLP spans (persons, dates, money, events), and event groups.

    Args:
        doc_id: Document UUID (e.g. "00014bb1-0d38-4683-925d-6c5b88d5c1ab_20260528").
    """
    result = db_module.get_document(doc_id)
    if not result:
        return {"error": f"Document '{doc_id}' not found."}
    return result


@mcp.tool()
def get_dossier(dossier_id: str) -> list[dict]:
    """
    Return all documents belonging to a dossier (= a specific property/location
    in the land register), ordered by year.

    Args:
        dossier_id: Dossier identifier (e.g. "HGB_1_113_064").
    """
    results = db_module.get_dossier(dossier_id)
    if not results:
        return [{"error": f"Dossier '{dossier_id}' not found."}]
    return results


@mcp.tool()
def search_text(query: str, limit: int = 20) -> list[dict]:
    """
    Full-text search over raw document transcriptions.

    Args:
        query: Search query (SQLite FTS5 syntax, supports AND/OR/NOT/phrase).
        limit: Maximum results (default 20, max 100).

    Returns matching documents with a text snippet showing the match in context.
    """
    limit = min(limit, 100)
    return db_module.search_text(query, limit)


@mcp.tool()
def get_persons_in_year_range(
    year_from: int, year_to: int, limit: int = 100
) -> list[dict]:
    """
    List all person mentions (head spans) in documents within a year range.

    Args:
        year_from: Start year (inclusive).
        year_to:   End year (inclusive).
        limit:     Maximum results (default 100, max 500).
    """
    if year_to < year_from:
        return [{"error": "year_to must be >= year_from"}]
    if year_to - year_from > 300:
        return [{"error": "Year range too large; max 300 years."}]
    limit = min(limit, 500)
    return db_module.get_persons_in_year_range(year_from, year_to, limit)


@mcp.tool()
def get_cooccurrences(person_name: str, limit: int = 20) -> list[dict]:
    """
    Find other persons who appear in the same documents as the given person.
    Useful for discovering social networks and property relationships.

    Args:
        person_name: Full or partial name (case-insensitive substring match).
        limit:       Max co-occurring persons to return (default 20).
    """
    return db_module.get_cooccurrences(person_name, min(limit, 100))


@mcp.tool()
def list_dossiers(limit: int = 200) -> list[dict]:
    """
    List all dossiers (properties) in the corpus with their year range,
    document count, and geographic coordinates.

    Args:
        limit: Max dossiers to return (default 200, max 2000).
    """
    return db_module.list_dossiers(min(limit, 2000))


# ── Cross-corpus identities ───────────────────────────────────────────────────
#
# The tools above work on raw HGB *mentions*: one row per time a name appears in
# a document. These work on resolved *people*: one record per real person,
# merged across HBLS, HLS and the HGB and keyed to GND/Wikidata, each carrying
# a sources[] array back to every contributing corpus.

_NO_IDENTITIES = {
    "error": "Identity tables not present in this database. "
             "Run: python build_identities.py --json ../merged_persons.json --db <db>"
}


@mcp.tool()
def identity_stats() -> dict:
    """
    Statistics about the cross-corpus person identities: how many resolved
    people, how many carry a GND/Wikidata id, how many are attested in all
    three source corpora.
    """
    if not db_module.has_identities():
        return _NO_IDENTITIES
    return db_module.identity_stats()


@mcp.tool()
def search_identities(query: str, limit: int = 20, corpus: Optional[str] = None,
                      with_gnd: bool = False) -> list[dict]:
    """
    Search resolved cross-corpus persons by name, occupation, place or the
    title of a work they authored.

    Prefer this over search_persons when you want *people* rather than raw
    document mentions: each hit is one person with life dates, occupations,
    authority ids (GND/Wikidata/VIAF) and provenance back to each source.

    Args:
        query:    FTS5 query, e.g. "Buchdrucker", "Zwinger", "Basel".
        limit:    Maximum results (default 20, max 200).
        corpus:   Restrict to persons attested in a corpus: "hbls", "hls" or "hgb".
        with_gnd: Only return persons carrying a GND identifier.
    """
    if not db_module.has_identities():
        return [_NO_IDENTITIES]
    if corpus and corpus.lower() not in ("hbls", "hls", "hgb"):
        return [{"error": "corpus must be one of: hbls, hls, hgb"}]
    return db_module.search_identities(
        query, min(limit, 200), corpus.lower() if corpus else None, with_gnd)


@mcp.tool()
def get_identity(identity_id: str) -> dict:
    """
    Fetch one resolved person by id, with full detail: life dates, occupations,
    places, publications, authority ids, HGB dossiers and the sources[] array
    linking back to the HBLS scan page, HLS article, GND and Wikidata.

    Args:
        identity_id: Identity id, e.g. "person:00050".
    """
    if not db_module.has_identities():
        return _NO_IDENTITIES
    rec = db_module.get_identity(identity_id)
    return rec or {"error": f"Identity '{identity_id}' not found."}


@mcp.tool()
def get_identity_by_authority(scheme: str, value: str) -> dict:
    """
    Look up a resolved person by an external authority identifier — the
    reliable way in, when you already have an id from another system.

    Args:
        scheme: One of "gnd", "wikidata", "hls", "viaf".
        value:  The identifier, e.g. "104334274", "Q6215993", "025956".
    """
    if not db_module.has_identities():
        return _NO_IDENTITIES
    if scheme.lower() not in ("gnd", "wikidata", "hls", "viaf"):
        return {"error": "scheme must be one of: gnd, wikidata, hls, viaf"}
    rec = db_module.get_identity_by_authority(scheme, value)
    return rec or {"error": f"No identity with {scheme}={value}."}


@mcp.tool()
def get_identities_in_year_range(
    year_from: int, year_to: int, limit: int = 100
) -> list[dict]:
    """
    Resolved persons whose life span overlaps the given years. Unlike
    get_persons_in_year_range (which returns document mentions), this returns
    one record per person.

    Args:
        year_from: Start year (inclusive).
        year_to:   End year (inclusive).
        limit:     Maximum results (default 100, max 500).
    """
    if not db_module.has_identities():
        return [_NO_IDENTITIES]
    if year_to < year_from:
        return [{"error": "year_to must be >= year_from"}]
    return db_module.identities_in_year_range(year_from, year_to, min(limit, 500))


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("hgb://stats")
def resource_stats() -> str:
    """Corpus statistics as JSON."""
    return json.dumps(db_module.db_stats(), indent=2)


@mcp.resource("hgb://dossiers")
def resource_dossiers() -> str:
    """All dossiers (properties) as JSON."""
    return json.dumps(db_module.list_dossiers(9999), indent=2)


@mcp.resource("hgb://document/{doc_id}")
def resource_document(doc_id: str) -> str:
    """Full document by ID as JSON."""
    return json.dumps(db_module.get_document(doc_id), indent=2, ensure_ascii=False)


@mcp.resource("hgb://identity/{identity_id}")
def resource_identity(identity_id: str) -> str:
    """Resolved cross-corpus person by identity id as JSON."""
    if not db_module.has_identities():
        return json.dumps(_NO_IDENTITIES, indent=2)
    return json.dumps(db_module.get_identity(identity_id), indent=2,
                      ensure_ascii=False)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",   default="hgb.db",  help="Path to hgb.db")
    ap.add_argument("--host", default="0.0.0.0", help="Bind host")
    ap.add_argument("--port", type=int, default=8000, help="Bind port")
    args = ap.parse_args()

    db_module.set_db_path(args.db)
    logger.info(f"Database: {args.db}")
    try:
        stats = db_module.db_stats()
        logger.info(f"Corpus: {stats['n_documents']:,} docs, {stats['n_persons']:,} person spans")
    except Exception as e:
        logger.warning(f"Could not read DB stats: {e}")

    logger.info(f"Starting HGB MCP server on {args.host}:{args.port}")
    mcp.run(transport="sse", host=args.host, port=args.port)
