"""
Regression tests for the street-scoped identity resolution in
build_hgb_street_persons.py.

The rules mirror the corpus-wide HGB resolution (build_data.py approach 4,
dedupe_corpus.py) applied inside one street. These pin the four decisions
that matter for cross-linking: subset merge inside a dossier, the lifespan
cap, the deceased constraint (in both the canonical-key and the phonetic
pass) and the phonetic merge that the street anchors.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_hgb_street_persons import resolve_street, emit  # noqa: E402


def M(name, year, dossier, dead=False):
    return {"name": name, "year": year, "dossier": dossier, "dead": dead,
            "occ": [], "roles": {}, "source": "t", "location": "POINT(1 2)"}


def persons(mentions):
    return {r["name"]: r for r in emit("S", "Teststrasse", resolve_street(mentions))}


def test_subset_name_merges_inside_a_dossier():
    p = persons([M("Hans Gysler", 1540, "D1"), M("Hans Heinrich Gysler", 1545, "D1")])
    assert list(p) == ["Hans Heinrich Gysler"]
    assert sorted(p["Hans Heinrich Gysler"]["variants"]) == ["Hans Gysler", "Hans Heinrich Gysler"]
    assert "subset" in p["Hans Heinrich Gysler"]["merged_by"]


def test_same_name_across_dossiers_merges_within_one_lifespan():
    p = persons([M("Hans Gysler", 1540, "D1"), M("Hans Gysler", 1560, "D2")])
    assert len(p) == 1
    assert p["Hans Gysler"]["dossiers"] == ["D1", "D2"]
    assert p["Hans Gysler"]["years"] == [1540, 1560]


def test_lifespan_cap_keeps_generations_apart():
    recs = emit("S", "T", resolve_street([M("Hans Müller", 1450, "D1"), M("Hans Müller", 1600, "D2")]))
    assert len(recs) == 2


def test_phonetic_variants_merge_on_the_street():
    # Gysler/Gisler share the Kölner code and the given-name sequence;
    # the street is the context anchor, no shared dossier needed
    p = persons([M("Hans Gysler", 1540, "D1"), M("Hans Gisler", 1552, "D3")])
    assert len(p) == 1
    (rec,) = p.values()
    assert "phonetic" in rec["merged_by"]
    assert rec["n"] == 2


def test_different_given_sequence_never_merges():
    p = persons([M("Hans Gysler", 1540, "D1"), M("Hans Heinrich Gisler", 1552, "D3")])
    assert len(p) == 2


def test_deceased_constraint_in_both_passes():
    # recorded dead in 1510: a live 1540 mention is a later person, whether it
    # comes with the identical name (canonical-key pass) or a spelling
    # variant (phonetic pass)
    recs = emit("S", "T", resolve_street([
        M("Peter Vogt", 1500, "D4"), M("Peter Vogt", 1510, "D4", dead=True),
        M("Peter Vogt", 1540, "D5"), M("Petter Vogtt", 1545, "D6")]))
    by_year = sorted(recs, key=lambda r: r["years"][0])
    assert [r["years"] for r in by_year] == [[1500, 1510], [1540, 1545]]
    assert by_year[0]["dead_year"] == 1510 and by_year[1]["dead_year"] is None


def test_single_token_names_are_never_merged_across_dossiers():
    recs = emit("S", "T", resolve_street([M("Hans", 1500, "D1"), M("Hans", 1502, "D2")]))
    assert len(recs) == 2
