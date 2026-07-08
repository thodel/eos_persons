"""
db.py — HBLS MCP database layer

Provides read-only queries over hbls.db (SQLite + FTS5).
All functions return plain Python dicts/lists — JSON-serialisable.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

DB_PATH: Optional[str] = None


def set_db_path(path: str) -> None:
    global DB_PATH
    DB_PATH = path


def _con() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("db.py: call set_db_path(<path>) before querying")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── Stats ─────────────────────────────────────────────────────────────────────

def db_stats() -> dict:
    """
    Return corpus-level statistics for /health endpoint.
    Returns: {persons, has_hls, has_wikidata, has_gnd, year_range}
    """
    con = _con()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM persons WHERE hls_id IS NOT NULL")
    n_hls = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM persons WHERE wd_qid IS NOT NULL")
    n_wd = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM persons WHERE wd_gnd IS NOT NULL")
    n_gnd = cur.fetchone()[0]

    cur.execute("SELECT MIN(year_from), MAX(year_to) FROM persons "
                "WHERE year_from IS NOT NULL")
    row = cur.fetchone()
    ymin, ymax = row[0], row[1]

    cur.execute("SELECT COUNT(*) FROM persons")
    n_total = cur.fetchone()[0]

    con.close()
    return {
        "persons": n_total,
        "has_hls": n_hls,
        "has_wikidata": n_wd,
        "has_gnd": n_gnd,
        "year_range": [ymin, ymax] if ymin and ymax else [None, None],
    }


# ── Search ────────────────────────────────────────────────────────────────────

def search_persons(
    query: str,
    limit: int = 20,
    fuzzy: bool = False,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> list[dict]:
    """
    Full-text search for persons by name.

    Uses SQLite FTS5. query is interpreted as FTS5 syntax.
    For substring/prefix search, use query*" or query*.

    Args:
        query:       Name or name fragment (FTS5 syntax, e.g. "Keller*" for prefix).
        limit:       Max results (default 20, max 200).
        fuzzy:       If True and FTS returns < limit results, fall back to
                     prefix search (query*).
        year_from:   Filter: person active after this year.
        year_to:     Filter: person active before this year.

    Returns list of person dicts with {id, name, mention_count, year_from,
    year_to, hls_id, wd_qid, occupations, locations}.
    """
    limit = min(limit, 200)
    con = _con()
    con.create_function("match_rank", 1, _match_rank, deterministic=True)
    cur = con.cursor()

    # Build year filter clause
    year_clause = ""
    year_params: list = []
    if year_from is not None:
        year_clause += " AND p.year_to >= ?"
        year_params.append(year_from)
    if year_to is not None:
        year_clause += " AND p.year_from <= ?"
        year_params.append(year_to)

    base_sql = f"""
        SELECT p.id, p.name, p.mention_count, p.dossier_count,
               p.year_from, p.year_to, p.hls_id, p.wd_qid,
               p.occupations, p.locations, p.titles,
               p.hls_title, p.wd_birth, p.wd_death
        FROM persons p
        JOIN fts_persons f ON p.id = f.rowid
        WHERE fts_persons MATCH ?
        {year_clause}
        ORDER BY p.mention_count DESC
        LIMIT ?
    """
    params = [query] + year_params + [limit]
    cur.execute(base_sql, params)
    rows = cur.fetchall()

    # Fuzzy fallback: if fewer results than limit, try prefix search
    if fuzzy and len(rows) < limit and not query.endswith("*"):
        prefix_query = query + "*"
        cur.execute(base_sql, [prefix_query] + year_params + [limit])
        rows = cur.fetchall()

    results = [_row_to_dict(r) for r in rows]
    con.close()
    return results


def _match_rank(rowid: int) -> float:
    """BM25 proxy: just return rowid desc as rank (higher = more mentions)."""
    return 0.0


def _row_to_dict(r: sqlite3.Row) -> dict:
    def _parse_json(val):
        if val is None:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    return {
        "id":             r["id"],
        "name":           r["name"],
        "mention_count":  r["mention_count"],
        "dossier_count":  r["dossier_count"],
        "year_from":      r["year_from"],
        "year_to":        r["year_to"],
        "hls_id":         r["hls_id"],
        "wd_qid":         r["wd_qid"],
        "occupations":    _parse_json(r["occupations"]),
        "locations":      _parse_json(r["locations"]),
        "titles":         _parse_json(r["titles"]),
        "hls_title":      r["hls_title"],
        "wd_birth":       r["wd_birth"],
        "wd_death":       r["wd_death"],
    }


# ── Get single person ─────────────────────────────────────────────────────────

def get_person(person_id: int) -> Optional[dict]:
    """
    Fetch a single person by integer id.
    Returns None if not found.
    """
    con = _con()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, variants, mention_count, dossier_count,
               year_from, year_to, dead_year,
               occupations, titles, families, locations, orgs,
               hls_id, hls_url, hls_title, hls_rel,
               wd_qid, wd_birth, wd_death, wd_occupations, wd_gnd,
               kin
        FROM persons
        WHERE id = ?
        """,
        (person_id,),
    )
    row = cur.fetchone()
    con.close()
    if row is None:
        return None

    def _j(val):
        if val is None:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val

    r = dict(row)
    return {
        "id":             r["id"],
        "name":           r["name"],
        "variants":       _j(r["variants"]),
        "mention_count":  r["mention_count"],
        "dossier_count":  r["dossier_count"],
        "year_from":      r["year_from"],
        "year_to":        r["year_to"],
        "dead_year":      r["dead_year"],
        "occupations":    _j(r["occupations"]),
        "titles":         _j(r["titles"]),
        "families":       _j(r["families"]),
        "locations":      _j(r["locations"]),
        "orgs":           _j(r["orgs"]),
        "hls": {
            "id":    r["hls_id"],
            "url":   r["hls_url"],
            "title": r["hls_title"],
            "rel":   r["hls_rel"],
        } if r["hls_id"] else None,
        "wd": {
            "qid":        r["wd_qid"],
            "birth":      r["wd_birth"],
            "death":      r["wd_death"],
            "occupations": _j(r["wd_occupations"]),
            "gnd":        r["wd_gnd"],
        } if r["wd_qid"] else None,
        "kin": _j(r["kin"]),
    }


# ── Get by HLS ID ─────────────────────────────────────────────────────────────

def get_by_hls(hls_id: str) -> Optional[dict]:
    """Fetch person by HLS ID (e.g. '025221')."""
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT id FROM persons WHERE hls_id = ?", (hls_id,))
    row = cur.fetchone()
    con.close()
    if row is None:
        return None
    return get_person(row[0])


# ── Get by Wikidata QID ───────────────────────────────────────────────────────

def get_by_wikidata(qid: str) -> Optional[dict]:
    """Fetch person by Wikidata QID (e.g. 'Q4219116')."""
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT id FROM persons WHERE wd_qid = ?", (qid,))
    row = cur.fetchone()
    con.close()
    if row is None:
        return None
    return get_person(row[0])
