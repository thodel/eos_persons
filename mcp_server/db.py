"""
db.py — SQLite query helpers for the HGB MCP server.
"""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, List, Optional

_DB_PATH: str = "hgb.db"


def set_db_path(path: str):
    global _DB_PATH
    _DB_PATH = path


@contextmanager
def conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    try:
        yield con
    finally:
        con.close()


def row_to_dict(row) -> dict:
    return dict(row) if row else {}


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Document queries ──────────────────────────────────────────────────────────

def get_document(doc_id: str) -> dict:
    with conn() as c:
        doc = c.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not doc:
            return {}
        result = row_to_dict(doc)
        result["spans"] = rows_to_list(
            c.execute(
                "SELECT span_id, parent_id, class, element, text, confidence, "
                "token_start, token_end, numerus, specificity, subclass, norm "
                "FROM spans WHERE doc_id = ? ORDER BY token_start",
                (doc_id,),
            )
        )
        result["events"] = rows_to_list(
            c.execute(
                "SELECT event_id, class, token_start, token_end, tense, polarity, modality "
                "FROM events WHERE doc_id = ?",
                (doc_id,),
            )
        )
        return result


def get_dossier(dossier_id: str) -> list[dict]:
    with conn() as c:
        docs = rows_to_list(
            c.execute(
                "SELECT id, year, source, location, text_raw "
                "FROM documents WHERE dossier_id = ? ORDER BY year",
                (dossier_id,),
            )
        )
    return docs


# ── Person queries ────────────────────────────────────────────────────────────

def search_persons(query: str, limit: int = 20) -> list[dict]:
    """FTS search over person span texts."""
    with conn() as c:
        rows = c.execute(
            """
            SELECT s.doc_id, s.span_id, s.class, s.text, s.confidence,
                   s.numerus, s.specificity,
                   d.dossier_id, d.year, d.source, d.location
            FROM fts_spans f
            JOIN spans s  ON s.rowid = f.rowid
            JOIN documents d ON d.id = s.doc_id
            WHERE fts_spans MATCH ? AND s.class = 'per'
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return rows_to_list(rows)


def get_persons_in_year_range(
    year_from: int, year_to: int, limit: int = 100
) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """
            SELECT s.text, s.confidence, s.numerus, s.specificity,
                   d.id AS doc_id, d.dossier_id, d.year, d.source, d.location
            FROM spans s
            JOIN documents d ON d.id = s.doc_id
            WHERE s.class = 'per' AND s.element = 'head'
              AND d.year BETWEEN ? AND ?
            ORDER BY d.year, s.text
            LIMIT ?
            """,
            (year_from, year_to, limit),
        ).fetchall()
    return rows_to_list(rows)


def get_cooccurrences(person_name: str, limit: int = 20) -> list[dict]:
    """Other persons mentioned in the same documents as person_name."""
    with conn() as c:
        # Find doc_ids containing the person
        doc_ids = [
            r[0]
            for r in c.execute(
                """
                SELECT DISTINCT doc_id FROM spans
                WHERE class = 'per' AND text LIKE ?
                """,
                (f"%{person_name}%",),
            )
        ]
        if not doc_ids:
            return []
        placeholders = ",".join("?" * len(doc_ids))
        rows = c.execute(
            f"""
            SELECT s.text, COUNT(*) AS freq,
                   GROUP_CONCAT(DISTINCT d.dossier_id) AS dossiers
            FROM spans s
            JOIN documents d ON d.id = s.doc_id
            WHERE s.doc_id IN ({placeholders})
              AND s.class = 'per'
              AND s.text NOT LIKE ?
            GROUP BY s.text
            ORDER BY freq DESC
            LIMIT ?
            """,
            (*doc_ids, f"%{person_name}%", limit),
        ).fetchall()
    return rows_to_list(rows)


# ── Full-text search ──────────────────────────────────────────────────────────

def search_text(query: str, limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """
            SELECT d.id, d.dossier_id, d.year, d.source, d.location,
                   snippet(fts_documents, 1, '<b>', '</b>', '…', 20) AS snippet
            FROM fts_documents f
            JOIN documents d ON d.id = f.id
            WHERE fts_documents MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return rows_to_list(rows)


# ── Dossier listing ───────────────────────────────────────────────────────────

def list_dossiers(limit: int = 1000) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """
            SELECT dossier_id,
                   MIN(year) AS year_min, MAX(year) AS year_max,
                   COUNT(*) AS n_docs,
                   location
            FROM documents
            WHERE dossier_id IS NOT NULL
            GROUP BY dossier_id
            ORDER BY dossier_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows_to_list(rows)


def db_stats() -> dict[str, Any]:
    with conn() as c:
        return {
            "n_documents": c.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "n_spans":     c.execute("SELECT COUNT(*) FROM spans").fetchone()[0],
            "n_persons":   c.execute("SELECT COUNT(*) FROM spans WHERE class='per'").fetchone()[0],
            "n_events":    c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "n_dossiers":  c.execute("SELECT COUNT(DISTINCT dossier_id) FROM documents").fetchone()[0],
            "year_min":    c.execute("SELECT MIN(year) FROM documents").fetchone()[0],
            "year_max":    c.execute("SELECT MAX(year) FROM documents").fetchone()[0],
        }


# ── Cross-corpus identities ───────────────────────────────────────────────────
#
# One row per real person, resolved across HBLS / HLS / HGB with GND and
# Wikidata authority ids (see ../hbls-extraction/DEDUP_PLAN.md). Loaded by
# build_identities.py; absent until that has been run, so every accessor here
# degrades to an explanatory error rather than an sqlite3 exception.

_JSON_FIELDS = ("conflicts", "occupations", "places", "publications",
                "dossiers", "sources")


def has_identities() -> bool:
    with conn() as c:
        return bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='identities'"
        ).fetchone())


def _identity_row(row) -> dict:
    """Expand the JSON-encoded columns back into real structures."""
    d = dict(row)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                pass
    d["corpora"] = d["corpora"].split("+") if d.get("corpora") else []
    return d


def search_identities(query: str, limit: int = 20, corpus: Optional[str] = None,
                      with_gnd: bool = False) -> list[dict]:
    sql = ["""SELECT i.* FROM fts_identities f
              JOIN identities i ON i.id = f.id
              WHERE fts_identities MATCH ?"""]
    params: List[Any] = [query]
    if corpus:
        sql.append("AND i.corpora LIKE ?")
        params.append(f"%{corpus}%")
    if with_gnd:
        sql.append("AND i.gnd IS NOT NULL")
    sql.append("ORDER BY rank LIMIT ?")
    params.append(limit)
    with conn() as c:
        rows = c.execute(" ".join(sql), params).fetchall()
    return [_identity_row(r) for r in rows]


def get_identity(identity_id: str) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM identities WHERE id = ?",
                        (identity_id,)).fetchone()
    return _identity_row(row) if row else {}


def get_identity_by_authority(scheme: str, value: str) -> dict:
    col = {"gnd": "gnd", "wikidata": "wikidata", "hls": "hls_id",
           "viaf": "viaf"}.get(scheme.lower())
    if not col:
        return {}
    with conn() as c:
        row = c.execute(f"SELECT * FROM identities WHERE {col} = ?",
                        (value,)).fetchone()
    return _identity_row(row) if row else {}


def identities_in_year_range(year_from: int, year_to: int,
                             limit: int = 100) -> list[dict]:
    """Identities whose life span overlaps [year_from, year_to]."""
    with conn() as c:
        rows = c.execute(
            """SELECT * FROM identities
               WHERE (birth_year IS NOT NULL OR death_year IS NOT NULL)
                 AND COALESCE(birth_year, death_year) <= ?
                 AND COALESCE(death_year, birth_year) >= ?
               ORDER BY COALESCE(birth_year, death_year) LIMIT ?""",
            (year_to, year_from, limit)).fetchall()
    return [_identity_row(r) for r in rows]


# ── Resolved HGB person clusters ──────────────────────────────────────────────
#
# One row per deduplicated name in the land register, with variants and
# aggregated mention/dossier counts. Breadth over the register (~137k), where
# `identities` above is depth on the ~3.4k people resolvable across corpora.

_PERSON_JSON = ("variants", "occupations", "titles", "families", "locations",
                "orgs", "dossiers")


def has_hgb_persons() -> bool:
    with conn() as c:
        return bool(c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hgb_persons'"
        ).fetchone())


def _person_row(row) -> dict:
    d = dict(row)
    for f in _PERSON_JSON:
        if isinstance(d.get(f), str):
            try:
                d[f] = json.loads(d[f])
            except (TypeError, ValueError):
                pass
    return d


def search_hgb_persons(query: str, limit: int = 20,
                       year_from: Optional[int] = None,
                       year_to: Optional[int] = None) -> list[dict]:
    sql = ["""SELECT p.* FROM fts_hgb_persons f
              JOIN hgb_persons p ON p.id = f.id
              WHERE fts_hgb_persons MATCH ?"""]
    params: List[Any] = [query]
    if year_from is not None:
        sql.append("AND p.year_to >= ?")
        params.append(year_from)
    if year_to is not None:
        sql.append("AND p.year_from <= ?")
        params.append(year_to)
    sql.append("ORDER BY rank LIMIT ?")
    params.append(limit)
    with conn() as c:
        rows = c.execute(" ".join(sql), params).fetchall()
        # FTS5 matches whole tokens; fall back to a prefix search when a bare
        # name fragment finds nothing (the common case for partial surnames).
        if not rows and not query.endswith("*") and " " not in query:
            params[0] = query + "*"
            rows = c.execute(" ".join(sql), params).fetchall()
    return [_person_row(r) for r in rows]


def get_hgb_person(person_id: int) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM hgb_persons WHERE id = ?",
                        (person_id,)).fetchone()
    return _person_row(row) if row else {}


def identity_stats() -> dict[str, Any]:
    with conn() as c:
        one = lambda q: c.execute(q).fetchone()[0]  # noqa: E731
        return {
            "n_identities":      one("SELECT COUNT(*) FROM identities"),
            "with_life_dates":   one("SELECT COUNT(*) FROM identities WHERE birth_year IS NOT NULL OR death_year IS NOT NULL"),
            "with_gnd":          one("SELECT COUNT(*) FROM identities WHERE gnd IS NOT NULL"),
            "with_wikidata":     one("SELECT COUNT(*) FROM identities WHERE wikidata IS NOT NULL"),
            "with_occupations":  one("SELECT COUNT(*) FROM identities WHERE occupations != '[]'"),
            "with_publications": one("SELECT COUNT(*) FROM identities WHERE n_publications > 0"),
            "in_all_three_corpora": one("SELECT COUNT(*) FROM identities WHERE n_corpora = 3"),
            "attested_in_hgb":   one("SELECT COUNT(*) FROM identities WHERE corpora LIKE '%hgb%'"),
            "year_min":          one("SELECT MIN(birth_year) FROM identities"),
            "year_max":          one("SELECT MAX(death_year) FROM identities"),
        }
