"""Tests for hbls_mcp — run with:  HBLS_PERSONS_DB=hbls.db python -m pytest tests/  -v"""
import os, pytest
from pathlib import Path

DB = Path(os.environ.get("HBLS_PERSONS_DB", "hbls.db"))

pytestmark = pytest.mark.skipif(
    not DB.exists(), reason=f"HBLS_PERSONS_DB not found at {DB}"
)

# ── DB structure ──────────────────────────────────────────────────────────────

def test_db_opens_and_is_ok():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    con.close()

def test_fts_persons_table_exists():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fts_persons'"
    )
    assert cur.fetchone() is not None, "fts_persons table missing"
    con.close()

def test_persons_count():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT COUNT(*) FROM persons")
    n = cur.fetchone()[0]
    assert n >= 137_000, f"Expected >=137k persons, got {n}"
    con.close()

def test_fts_count():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT COUNT(*) FROM fts_persons")
    assert cur.fetchone()[0] >= 137_000
    con.close()

# ── FTS search correctness ────────────────────────────────────────────────────

def test_fts_exact_match():
    import sqlite3
    con = sqlite3.connect(DB)
    # exact phrase match on "Hans Müller"
    cur = con.execute(
        "SELECT p.name FROM fts_persons f JOIN persons p ON f.rowid = p.id "
        "WHERE fts_persons MATCH ? LIMIT 5",
        ('"Hans Müller"',)
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "No FTS results for exact phrase 'Hans Müller'"
    con.close()

def test_fts_fuzzy_prefix():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT p.name FROM fts_persons f JOIN persons p ON f.rowid = p.id "
        "WHERE fts_persons MATCH ? LIMIT 5",
        ('Müller*',)
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "No FTS results for prefix 'Müller*'"
    con.close()

def test_bm25_scores_are_negative():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT bm25(fts_persons) FROM fts_persons WHERE fts_persons MATCH ? LIMIT 10",
        ('Hans',)
    )
    scores = [r[0] for r in cur.fetchall()]
    assert len(scores) == 10
    for s in scores:
        assert s < 0, f"BM25 should be negative (lower=more relevant), got {s}"
    con.close()

def test_fts_snippet_not_empty():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT snippet(fts_persons, 0, '<b>', '</b>', '…', 10) "
        "FROM fts_persons WHERE fts_persons MATCH ? LIMIT 3",
        ('Müller',)
    )
    snippets = [r[0] for r in cur.fetchall()]
    assert all(snippets), f"Empty FTS snippets: {snippets}"
    con.close()

# ── Schema ────────────────────────────────────────────────────────────────────

def test_sample_record_has_required_columns():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT * FROM persons LIMIT 1")
    cols = [d[0] for d in cur.description]
    for field in ("name", "variants", "year_from", "year_to",
                  "occupations", "hls_id", "wd_qid"):
        assert field in cols, f"Missing required column: {field}"
    con.close()

# ── Filters ───────────────────────────────────────────────────────────────────

def test_year_range_filter():
    """Corpus spans 1400-1700; use 1450-1500 window with 23k+ persons."""
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT COUNT(*) FROM persons WHERE year_from >= ? AND year_to <= ?",
        (1450, 1500)
    )
    n = cur.fetchone()[0]
    assert n > 0, f"Expected some persons 1450-1500, got {n}"
    con.close()

def test_hls_ids_exist():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT COUNT(*) FROM persons WHERE hls_id IS NOT NULL")
    assert cur.fetchone()[0] > 0, "No HLS IDs found"
    con.close()

def test_wikidata_qids_exist():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("SELECT COUNT(*) FROM persons WHERE wd_qid IS NOT NULL")
    assert cur.fetchone()[0] > 0, "No Wikidata QIDs found"
    con.close()

# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_keys():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(hls_id IS NOT NULL) AS with_hls, "
        "SUM(wd_qid IS NOT NULL) AS with_wikidata "
        "FROM persons"
    )
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    d = dict(zip(cols, row))
    assert all(k in d for k in ("total", "with_hls", "with_wikidata"))
    assert d["total"] >= 137_000
    con.close()

# ── WAL mode ──────────────────────────────────────────────────────────────────

def test_db_is_wal_mode():
    import sqlite3
    con = sqlite3.connect(DB)
    cur = con.execute("PRAGMA journal_mode")
    assert cur.fetchone()[0] == "wal", "Expected WAL journal mode"
    con.close()
