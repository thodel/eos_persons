"""
server.py — HBLS MCP server (HTTP/SSE transport)

Exposes 137,038 merged historical person records from HGB Basel (ca. 1400–1700),
cross-linked to HLS (Historical Dictionary of Switzerland), Wikidata, and GND.

Start:
    python server.py --db hbls.db --host 0.0.0.0 --port 8003

MCP clients connect to:
    http://<host>:<port>/sse
    or
    http://<host>:<port>/mcp  (streamable-http)
"""

import argparse
import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

import db as db_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="HBLS (HGB Basel Persons)",
    instructions=(
        "HBLS provides access to 137,038 merged person records from the "
        "Historisches Grundbuch Basel (HGB), ca. 1400–1700. Each record "
        "aggregates mentions across multiple HGB dossiers and carries "
        "authority links to HLS (Historical Dictionary of Switzerland), "
        "Wikidata, and GND where available. "
        "Use search_persons to find persons by name; get_person to fetch "
        "a full record by id; get_by_hls or get_by_wikidata to look up "
        "by authority identifiers."
    ),
)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def corpus_stats() -> dict:
    """
    High-level statistics about the HBLS corpus.

    Returns: {persons, has_hls, has_wikidata, has_gnd, year_range}
    """
    return db_module.db_stats()


@mcp.tool()
def search_persons(
    query: str,
    limit: int = 20,
    fuzzy: bool = False,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> list[dict]:
    """
    Full-text search for persons by name using SQLite FTS5.

    Args:
        query:     Name string (FTS5 syntax: "Keller" or "Keller*" for prefix).
        limit:     Max results to return (default 20, max 200).
        fuzzy:     If True and exact search finds fewer than limit results,
                   automatically retry with prefix search (appends *).
        year_from: Only return persons active after this year.
        year_to:   Only return persons active before this year.

    Returns list of person summary dicts, ordered by mention count descending.
    Each dict contains: id, name, mention_count, dossier_count, year_from,
    year_to, hls_id, wd_qid, occupations, locations.
    """
    limit = min(limit, 200)
    if not query or len(query.strip()) < 1:
        return []
    return db_module.search_persons(
        query.strip(), limit=limit, fuzzy=fuzzy,
        year_from=year_from, year_to=year_to,
    )


@mcp.tool()
def get_person(person_id: int) -> Optional[dict]:
    """
    Fetch a single person record by integer id.

    Args:
        person_id: Internal HBLS id (integer). Use search_persons first
                   to find the id for a given name.

    Returns full person dict (with variants, occupations, locations, HLS link,
    Wikidata link, family relations) or None if not found.
    """
    return db_module.get_person(person_id)


@mcp.tool()
def get_by_hls(hls_id: str) -> Optional[dict]:
    """
    Look up a person by their HLS (Historical Dictionary of Switzerland) ID.

    Args:
        hls_id: HLS article number as string, e.g. "025221" for Jakob Keller.
                Returns None if no person has this HLS ID (only ~809 of 137k
                persons are linked to HLS).

    Returns full person dict or None.
    """
    if not hls_id:
        return None
    return db_module.get_by_hls(hls_id.strip())


@mcp.tool()
def get_by_wikidata(qid: str) -> Optional[dict]:
    """
    Look up a person by their Wikidata QID.

    Args:
        qid: Wikidata item ID, e.g. "Q4219116" for Jakob Keller.
             Returns None if the person has no Wikidata link
             (only ~768 of 137k persons are linked).

    Returns full person dict or None.
    """
    if not qid:
        return None
    return db_module.get_by_wikidata(qid.strip())


@mcp.tool()
def get_persons_in_year_range(
    year_from: int,
    year_to: int,
    limit: int = 100,
) -> list[dict]:
    """
    List persons whose activity window overlaps with [year_from, year_to].

    Args:
        year_from: Start of range (inclusive).
        year_to:   End of range (inclusive).
        limit:     Max results (default 100, max 500).

    Returns person summary dicts ordered by mention count descending.
    """
    if year_to < year_from:
        return []
    if year_to - year_from > 300:
        return []
    limit = min(limit, 500)
    con = db_module._con()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, mention_count, dossier_count,
               year_from, year_to, hls_id, wd_qid
        FROM persons
        WHERE year_from <= ? AND year_to >= ?
        ORDER BY mention_count DESC
        LIMIT ?
        """,
        (year_to, year_from, limit),
    )
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("hbls://stats")
def resource_stats() -> str:
    """Corpus statistics as JSON."""
    return json.dumps(db_module.db_stats(), indent=2)


@mcp.resource("hbls://person/{person_id}")
def resource_person(person_id: int) -> str:
    """Full person record by id as JSON."""
    record = db_module.get_person(person_id)
    if record is None:
        return json.dumps({"error": f"Person {person_id} not found"})
    return json.dumps(record, indent=2, ensure_ascii=False)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="HBLS MCP server")
    ap.add_argument("--db",   default="hbls.db",  help="Path to hbls.db")
    ap.add_argument("--host", default="0.0.0.0", help="Bind host")
    ap.add_argument("--port", type=int, default=8003, help="Bind port")
    args = ap.parse_args()

    db_module.set_db_path(args.db)
    logger.info(f"Database: {args.db}")

    try:
        stats = db_module.db_stats()
        logger.info(
            f"HBLS corpus: {stats['persons']:,} persons, "
            f"has_hls={stats['has_hls']:,}, has_wikidata={stats['has_wikidata']:,}"
        )
    except Exception as e:
        logger.warning(f"Could not read DB stats: {e}")

    logger.info(f"Starting HBLS MCP server on {args.host}:{args.port}")
    mcp.run(transport="sse", host=args.host, port=args.port)
