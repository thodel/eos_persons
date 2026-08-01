"""
Tests for the person tables and the MCP tools over them.

Ported from PR #1 (epic/ah-13-hbls-mcp), restructured in two ways:

  * PR #1 skipped its whole suite unless a prebuilt 137k-row database happened
    to exist, so in CI all 14 tests passed by being skipped. Here the database
    is built by the real build script from small synthetic fixtures, so the
    tests actually run everywhere.
  * PR #1 hand-wrote SQL against the schema and never imported db.py or
    server.py, so it tested SQLite rather than our code. These go through the
    query layer and the tool functions.

Assertions that only restated SQLite's own behaviour (bm25 scores are
negative, snippets are non-empty) are deliberately not carried over.

    python -m pytest mcp_server/tests -v
"""
import sqlite3

import pytest


# ── Database structure (from PR #1) ───────────────────────────────────────────

def test_db_integrity(db_path):
    con = sqlite3.connect(db_path)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_is_wal_mode(db_path):
    con = sqlite3.connect(db_path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.close()


@pytest.mark.parametrize("table", ["identities", "fts_identities",
                                   "hgb_persons", "fts_hgb_persons"])
def test_table_exists(db_path, table):
    con = sqlite3.connect(db_path)
    got = con.execute("SELECT name FROM sqlite_master WHERE name=?",
                      (table,)).fetchone()
    con.close()
    assert got is not None, f"{table} missing"


def test_required_columns_present(db_path):
    con = sqlite3.connect(db_path)
    for table, required in [
        ("identities", ("name", "birth_year", "death_year", "gnd", "wikidata",
                        "corpora", "status", "sources", "occupations")),
        ("hgb_persons", ("name", "variants", "year_from", "year_to",
                         "occupations", "hls_id", "wikidata")),
    ]:
        cols = {d[0] for d in con.execute(f"SELECT * FROM {table} LIMIT 1").description}
        missing = set(required) - cols
        assert not missing, f"{table} missing columns: {missing}"
    con.close()


def test_review_clusters_excluded_by_default(db):
    """person:00003 is status=review and must not be loaded."""
    assert db.get_identity("person:00003") == {}
    assert db.identity_stats()["n_identities"] == 2


# ── Identity queries ──────────────────────────────────────────────────────────

def test_identity_stats_shape(db):
    s = db.identity_stats()
    for k in ("n_identities", "with_gnd", "with_wikidata", "with_life_dates",
              "in_all_three_corpora", "attested_in_hgb"):
        assert k in s, f"missing stat: {k}"
    assert s["with_gnd"] == 1
    assert s["in_all_three_corpora"] == 1


def test_get_identity_expands_json_columns(db):
    """Stored as JSON text; callers must get real structures back."""
    r = db.get_identity("person:00001")
    assert r["name"] == "Johann Jakob Grasser"
    assert r["corpora"] == ["hbls", "hgb", "hls"]          # split, not "hbls+hgb+hls"
    assert r["occupations"] == ["Theologe", "Historiker"]  # list, not '["Theologe"…]'
    assert isinstance(r["sources"], list) and len(r["sources"]) == 5
    assert r["places"]["birth"] == ["Basel"]
    assert r["publications"][0]["year"] == "1615"


@pytest.mark.parametrize("scheme,value", [
    ("gnd", "104334274"),
    ("wikidata", "Q6215993"),
    ("hls", "025956"),
])
def test_lookup_by_authority(db, scheme, value):
    assert db.get_identity_by_authority(scheme, value)["name"] == "Johann Jakob Grasser"


def test_lookup_by_authority_rejects_unknown_scheme(db):
    assert db.get_identity_by_authority("orcid", "x") == {}


@pytest.mark.parametrize("query,expected", [
    ("Grasser", "Johann Jakob Grasser"),   # name
    ("Theologe", "Johann Jakob Grasser"),  # occupation
    ("Basel", "Johann Jakob Grasser"),     # place
    ("Horatii", "Johann Jakob Grasser"),   # work title
])
def test_identity_search_covers_every_indexed_field(db, query, expected):
    hits = db.search_identities(query, 5)
    assert [h["name"] for h in hits] == [expected]


def test_identity_search_filters(db):
    assert len(db.search_identities("Grasser", 5, corpus="hgb")) == 1
    assert len(db.search_identities("Abyberg", 5, corpus="hgb")) == 0
    assert len(db.search_identities("Abyberg", 5, with_gnd=True)) == 0
    assert len(db.search_identities("Abyberg", 5)) == 1


def test_identities_in_year_range_uses_overlap_not_containment(db):
    """Grasser lived 1579–1627, so a window inside that span must match."""
    assert len(db.identities_in_year_range(1600, 1610)) == 1
    assert len(db.identities_in_year_range(1700, 1800)) == 0


def test_identity_without_life_dates_is_excluded_from_year_range(db):
    assert all(r["id"] != "person:00002"
               for r in db.identities_in_year_range(1400, 1500))


# ── HGB register persons ──────────────────────────────────────────────────────

def test_hgb_person_search_and_expansion(db):
    hits = db.search_hgb_persons("Wursteisen", 10)
    assert {h["name"] for h in hits} == {"Sebastian Wursteisen",
                                         "Panthaleon Wursteisen"}
    seb = next(h for h in hits if h["name"] == "Sebastian Wursteisen")
    assert seb["variants"] == ["Sebastian Wursteisen", "Sebastian Wurstisen"]
    assert seb["occupations"] == ["gerichtsknecht", "ratsbote"]
    assert seb["dossiers"] == ["HGB_1_002_040"]
    assert seb["n_mentions"] == 128


def test_hgb_person_search_matches_variant_spelling(db):
    """Wurstisen appears only as a variant, never as the display name."""
    assert [h["name"] for h in db.search_hgb_persons("Wurstisen", 5)] == \
        ["Sebastian Wursteisen"]


def test_hgb_person_prefix_fallback(db):
    """A bare fragment matches no whole token; the fallback retries as pref*."""
    assert db.search_hgb_persons("Wurstei", 5), "prefix fallback did not fire"


def test_hgb_person_year_filter_is_overlap(db):
    """Heinrichen Keller spans 1431–1510 and overlaps a 1450–1500 window."""
    names = {h["name"] for h in db.search_hgb_persons("Keller", 10,
                                                      year_from=1450, year_to=1500)}
    assert "Heinrichen Keller" in names
    assert not db.search_hgb_persons("Keller", 10, year_from=1600, year_to=1700)


def test_get_hgb_person(db):
    r = db.get_hgb_person(1)
    assert r["name"] == "Sebastian Wursteisen"
    assert db.get_hgb_person(999_999) == {}


def test_hgb_authority_links_are_carried(db):
    seb = db.get_hgb_person(1)
    assert seb["hls_id"] == "025956"
    assert seb["wikidata"] == "Q6215993"
    assert seb["gnd"] == "104334274"


# ── Tool layer ────────────────────────────────────────────────────────────────

def test_all_expected_tools_registered(tools):
    for name in ("corpus_stats", "search_persons", "identity_stats",
                 "search_identities", "get_identity",
                 "get_identity_by_authority", "get_identities_in_year_range",
                 "search_hgb_persons", "get_hgb_person"):
        assert name in tools.mcp.registered, f"tool not registered: {name}"


def test_tools_clamp_limits(tools):
    """limit is clamped, so a client cannot ask for the whole table."""
    assert len(tools.search_identities("Grasser", limit=10_000)) <= 200
    assert len(tools.search_hgb_persons("Wursteisen", limit=10_000)) <= 200


@pytest.mark.parametrize("call,expected", [
    (lambda t: t.search_identities("x", corpus="nope")[0], "corpus must be one of"),
    (lambda t: t.get_identity_by_authority("nope", "x"), "scheme must be one of"),
    (lambda t: t.get_identities_in_year_range(1700, 1600)[0], "year_to must be >="),
    (lambda t: t.get_identity("person:99999"), "not found"),
    (lambda t: t.get_hgb_person(999_999), "not found"),
])
def test_tools_return_errors_not_exceptions(tools, call, expected):
    assert expected in call(tools)["error"]


def test_tools_degrade_when_tables_absent(tools, tmp_path):
    """A database without the person tables must explain itself, not crash."""
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()
    tools.db_module.set_db_path(str(bare))
    assert "not present" in tools.identity_stats()["error"]
    assert "not present" in tools.search_identities("x")[0]["error"]
    assert "not present" in tools.search_hgb_persons("x")[0]["error"]


# ── Real corpus (opt-in) ──────────────────────────────────────────────────────

def test_real_corpus_invariants(real_db):
    """Guards the published figures in DEDUP_PLAN.md against silent drift."""
    import db as db_module
    db_module.set_db_path(str(real_db))
    s = db_module.identity_stats()
    assert s["n_identities"] > 3_000, s
    # GND coverage is the headline claim of the linking work
    assert s["with_gnd"] / s["n_identities"] > 0.85, s
    assert s["in_all_three_corpora"] > 0


def test_real_corpus_year_min_is_plausible(real_db):
    """Regression guard for truncated GND years.

    GND writes decade-level uncertainty as '149X'. A bare \\d{3,4} search read
    that as the year 149, so three records reached the corpus with 3-digit
    life dates (Benedict May birth=149, Valentin Rebmann birth=152, Hans
    Conrad Griesser death=169) — indistinguishable from real years once in the
    published statistics. `link_hls.year_of` now rejects an imprecise date
    rather than guessing at it; this fails again if that regresses.
    """
    import db as db_module
    db_module.set_db_path(str(real_db))
    s = db_module.identity_stats()
    assert 1000 < s["year_min"] < 1700, f"implausible year_min: {s['year_min']}"
