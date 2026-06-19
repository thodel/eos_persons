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
        "search_text for keyword search across the raw transcriptions."
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
