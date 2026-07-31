"""
Shared fixtures.

The person tables are built from small synthetic fixtures that mirror the real
JSON schemas exactly, so the suite runs anywhere without the 800 MB XML, the
26 MB persons_resolved.json, or a prebuilt database. Tests that want the real
corpus opt in via the `real_db` fixture and skip when it is not there — that
way an absent data file skips one or two tests instead of silently skipping
everything.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MCP = HERE.parent
REPO = MCP.parent
sys.path.insert(0, str(MCP))


# ── Synthetic corpora ─────────────────────────────────────────────────────────
# Shapes copied from the real files; see build_merged_persons.py and
# hbls-extraction/DEDUP_PLAN.md for the schemas these mimic.

MERGED = [
    {   # the interesting case: all three corpora, GND + Wikidata, works
        "id": "person:00001", "cluster_id": "gnd:104334274", "status": "merged",
        "conflicts": [], "corpora": ["hbls", "hgb", "hls"],
        "name": "Johann Jakob Grasser", "surname": "Grasser", "given": "Johann Jakob",
        "birth_year": 1579, "death_year": 1627, "floruit_years": None, "gender": "m",
        "mention_span": [1626, 1626],
        "occupations": ["Theologe", "Historiker"],
        "occupations_hgb": [], "roles_gnd": ["Theologe", "Historiker"],
        "titles": [], "organisations": [], "locations": [],
        "places": {"birth": ["Basel"], "death": ["Basel"], "activity": []},
        "family": [], "kin": [], "dossiers": ["HGB_1_066_023"],
        "name_variants": ["Hans Ulrich Grassern"],
        "publications": [{"title": "Q. Horatii Flacci Opera Omnia", "year": "1615"}],
        "authority": {"gnd": ["104334274"], "wikidata": ["Q6215993"],
                      "viaf": "http://viaf.org/viaf/69366931"},
        "bio": "Jakob, Sohn von Nr. 1, 1579-1627, königl. Professor in Nîmes.",
        "name_agreement": 1.0,
        "provenance": {"name": "hls", "birth": "hls", "death": "hls"},
        "sources": [
            {"corpus": "hbls", "id": "hbls:3:3077", "volume": 3, "page": 660,
             "url": "https://biblio.unibe.ch/digibern/x/HBLS_band_03.pdf#page=660"},
            {"corpus": "hls", "id": "025956", "title": "Johann Jakob Grasser",
             "url": "https://hls-dhs-dss.ch/de/articles/025956/2005-12-05/"},
            {"corpus": "hgb", "id": "Johann Jacob Graser#1663", "n_records": 1,
             "n_mentions": 1, "n_dossiers": 1},
            {"corpus": "gnd", "id": "104334274", "url": "https://d-nb.info/gnd/104334274"},
            {"corpus": "wikidata", "id": "Q6215993",
             "url": "https://www.wikidata.org/wiki/Q6215993"},
        ],
    },
    {   # HBLS-only, no authority ids, no dates -> exercises the NULL paths
        "id": "person:00002", "cluster_id": "hbls:1:101", "status": "merged",
        "conflicts": [], "corpora": ["hbls"], "name": "Johann Abyberg",
        "surname": "Abyberg", "given": "Johann", "birth_year": None,
        "death_year": None, "floruit_years": [1428], "gender": None,
        "mention_span": None, "occupations": [], "occupations_hgb": [],
        "roles_gnd": [], "titles": [], "organisations": [], "locations": [],
        "places": {"birth": [], "death": [], "activity": []},
        "family": [], "kin": [], "dossiers": [], "name_variants": [],
        "publications": [], "authority": {"gnd": [], "wikidata": []},
        "bio": "Landammann 1428-32.", "name_agreement": None,
        "provenance": {"name": "hbls", "birth": None, "death": None},
        "sources": [{"corpus": "hbls", "id": "hbls:1:101", "volume": 1,
                     "page": 70, "url": "https://example.invalid/x.pdf#page=70"}],
    },
    {   # flagged -> must be excluded unless --include-review
        "id": "person:00003", "cluster_id": "hbls:9:9", "status": "review",
        "conflicts": ["name_disagreement"], "corpora": ["hbls", "hgb"],
        "name": "Konrad Fässler", "surname": "Fässler", "given": "Konrad",
        "birth_year": 1620, "death_year": 1695, "floruit_years": None,
        "gender": None, "mention_span": [1663, 1663], "occupations": [],
        "occupations_hgb": [], "roles_gnd": [], "titles": [],
        "organisations": [], "locations": [],
        "places": {"birth": [], "death": [], "activity": []},
        "family": [], "kin": [], "dossiers": [], "name_variants": [],
        "publications": [], "authority": {"gnd": ["107407100X"], "wikidata": []},
        "bio": None, "name_agreement": 0.0,
        "provenance": {"name": "hls", "birth": "hls", "death": "hls"},
        "sources": [{"corpus": "gnd", "id": "107407100X",
                     "url": "https://d-nb.info/gnd/107407100X"}],
    },
]

RESOLVED = [
    {"n": "Sebastian Wursteisen", "v": ["Sebastian Wursteisen", "Sebastian Wurstisen"],
     "c": 128, "d": 32, "y": [1604, 1651], "dead_year": None,
     "occ": ["gerichtsknecht", "ratsbote"], "tit": [], "fam": [], "loc": [], "org": [],
     "dos": [["HGB_1_002_040", "Sebastian Wursteisen"]],
     "hls": {"id": "025956", "url": "https://hls-dhs-dss.ch/de/articles/025956/"},
     "wd": {"qid": "Q6215993", "gnd": "104334274"}},
    {"n": "Heinrichen Keller", "v": ["Heinrichen Keller"], "c": 3, "d": 2,
     "y": [1431, 1510], "dead_year": None, "occ": ["schmid"], "tit": [], "fam": [],
     "loc": [], "org": [], "dos": [["HGB_1_010_125", "Heinrichen Keller"]]},
    {"n": "Panthaleon Wursteisen", "v": ["Panthaleon Wursteisen"], "c": 1, "d": 1,
     "y": [1561, 1561], "dead_year": None, "occ": [], "tit": [], "fam": [],
     "loc": [], "org": [], "dos": [["HGB_1_014_007", "Panthaleon Wursteisen"]]},
]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """A database with both person tables, built by the real build script."""
    d = tmp_path_factory.mktemp("mcpdb")
    merged, resolved, db = d / "merged.json", d / "resolved.json", d / "test.db"
    merged.write_text(json.dumps(MERGED), encoding="utf-8")
    resolved.write_text(json.dumps(RESOLVED), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(MCP / "build_identities.py"),
         "--json", str(merged), "--persons", str(resolved), "--db", str(db)],
        check=True, capture_output=True, cwd=MCP)
    return db


@pytest.fixture
def db(db_path):
    """The db module, pointed at the fixture database."""
    import db as db_module
    db_module.set_db_path(str(db_path))
    return db_module


@pytest.fixture
def tools(db_path):
    """server.py's tool functions, with FastMCP stubbed out."""
    import types
    if "mcp" not in sys.modules:
        fake = types.ModuleType("mcp")
        srv = types.ModuleType("mcp.server")
        fm = types.ModuleType("mcp.server.fastmcp")

        class FastMCP:
            def __init__(self, **kw):
                self.registered = []

            def tool(self, *a, **k):
                def deco(f):
                    self.registered.append(f.__name__)
                    return f
                return deco

            def resource(self, *a, **k):
                return lambda f: f

            def run(self, **kw):
                pass

        fm.FastMCP = FastMCP
        sys.modules.update({"mcp": fake, "mcp.server": srv,
                            "mcp.server.fastmcp": fm})
    import server
    server.db_module.set_db_path(str(db_path))
    return server


@pytest.fixture
def empty_db(tmp_path):
    """A database with no person tables, for the degradation paths."""
    p = tmp_path / "bare.db"
    sqlite3.connect(str(p)).close()
    import db as db_module
    db_module.set_db_path(str(p))
    return db_module


@pytest.fixture
def real_db(tmp_path_factory):
    """The real corpus, if merged_persons.json is present; else skip."""
    src = REPO / "merged_persons.json"
    if not src.exists():
        pytest.skip("merged_persons.json not present")
    db = tmp_path_factory.mktemp("realdb") / "real.db"
    subprocess.run(
        [sys.executable, str(MCP / "build_identities.py"),
         "--json", str(src), "--persons", "", "--db", str(db)],
        check=True, capture_output=True, cwd=MCP)
    return db
