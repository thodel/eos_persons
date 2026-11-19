"""
build_data.py turns the mention list into persons. These tests pin the time
rules and the bookkeeping that the cross-check with Basler Liegenschaften
Interaktiv showed to be wrong: fixed 80-year bins (a person torn apart at 1440,
1520, 1600, 1680; two namesakes 79 years apart kept together), bare given names
merged across generations, the mention count doubled at a death split, and the
dossier list cut at 30.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import build_data as B   # noqa: E402


def rows(*specs):
    """(name, year, dossier[, dead]) → DataFrame in the persons.csv layout."""
    out = []
    for sp in specs:
        name, year, dossier = sp[:3]
        out.append({"name": name, "year": year, "dossierid": dossier,
                    "is_deceased": 1 if len(sp) > 3 and sp[3] else 0,
                    "occupation_norm": None, "title": None, "family_relation": None,
                    "location": None, "org_affiliation": None})
    return pd.DataFrame(out)


def resolve(*specs):
    return B.build_persons_resolved(rows(*specs))


# ── time_runs / death_split ──────────────────────────────────────────────────

def R(*years):
    return [{"year": y, "dead": False} for y in years]


def test_runs_do_not_break_at_fixed_bin_borders():
    # 1595 // 80 != 1605 // 80: the old bins made two persons of this one
    assert [[r["year"] for r in run] for run in B.time_runs(R(1595, 1605))] == [[1595, 1605]]


def test_a_run_is_at_most_one_lifespan():
    # 1445 and 1519 shared a bin and were one person though 74 years apart is
    # fine; 1445 and 1530 (85 years) are two
    assert len(B.time_runs(R(1445, 1519))) == 1
    assert [[r["year"] for r in run] for run in B.time_runs(R(1445, 1500, 1530))] == [[1445, 1500], [1530]]


def test_gap_starts_a_new_run():
    runs = B.time_runs(R(1440, 1450, 1464, 1479, 1508), gap=B.BARE_GAP)
    assert [[r["year"] for r in run] for run in runs] == [[1440, 1450, 1464], [1479], [1508]]
    assert len(B.time_runs(R(1440, 1450, 1464, 1479, 1508))) == 1     # without a gap rule


def test_undated_rows_are_kept_apart():
    runs = B.time_runs(R(0, 1500, 1510))
    assert sorted(len(r) for r in runs) == [1, 2]


def test_death_split_assigns_every_row_once():
    rs = [{"year": 1480, "dead": False}, {"year": 1500, "dead": True},
          {"year": 1500, "dead": False},      # same year as the death: still him
          {"year": 1520, "dead": False}, {"year": 1540, "dead": True}]
    early, late = B.death_split(rs)
    assert [r["year"] for r in late] == [1520]
    assert [r["year"] for r in early] == [1480, 1500, 1500, 1540]
    assert len(early) + len(late) == len(rs)
    assert B.death_split(R(1480, 1500)) == [R(1480, 1500)]


# ── the resolution as a whole ────────────────────────────────────────────────

def test_every_mention_is_counted_exactly_once():
    specs = [("Hans Meyer", 1480, "D1"), ("Hans Meyer", 1500, "D1", True),
             ("Hans Meyer", 1520, "D1"), ("Hans Meyer", 1525, "D2"),
             ("Elsin", 1440, "D1"), ("Elsin", 1508, "D1"), ("Anna Roth", 1600, "D3")]
    P = resolve(*specs)
    assert sum(p["c"] for p in P) == len(specs)


def test_death_split_gives_each_half_its_own_mentions():
    P = resolve(("Hans Meyer", 1480, "D1"), ("Hans Meyer", 1490, "D1"),
                ("Hans Meyer", 1500, "D1", True), ("Hans Meyer", 1520, "D1"))
    by_start = {p["y"][0]: p for p in P}
    assert by_start[1480]["c"] == 3 and by_start[1480]["dead_year"] == 1500
    assert by_start[1520]["c"] == 1 and by_start[1520]["dead_year"] is None


def test_bare_names_are_not_merged_across_a_generation():
    P = resolve(("Elsin", 1440, "D1"), ("Elsin", 1452, "D1"), ("Elsin", 1508, "D1"))
    assert sorted((p["y"], p["c"]) for p in P) == [([1440, 1452], 2), ([1508, 1508], 1)]


def test_full_names_only_obey_the_lifespan():
    # 60 years of silence, same dossier: still one person by the rule of the index
    P = resolve(("Niclaus Krämer", 1605, "D1"), ("Niclaus Krämer", 1665, "D1"))
    assert len(P) == 1 and P[0]["y"] == [1605, 1665]


def test_a_bare_name_attached_to_a_full_name_follows_the_full_name():
    # 'Hans' is the one fuller 'Hans Meyer' of the dossier: no bare-name gap
    P = resolve(("Hans Meyer", 1500, "D1"), ("Hans", 1530, "D1"))
    assert len(P) == 1 and P[0]["c"] == 2


def test_person_at_a_former_bin_border_is_one():
    P = resolve(("Elsin", 1595, "D1"), ("Elsin", 1605, "D1"))
    assert len(P) == 1 and P[0]["y"] == [1595, 1605]


def test_dossier_list_is_complete_and_counted_by_dossier():
    specs = [("Sebastian Wursteisen", 1630 + i % 20, f"D{i:02d}") for i in range(40)]
    P = resolve(*specs)
    assert len(P) == 1
    assert len(P[0]["dos"]) == 40 and P[0]["d"] == 40


def test_d_counts_dossiers_not_name_pairs():
    # three spellings, each a subset of the two others, so none merges inside
    # the dossier; city-wide they share a canonical key: one dossier, three
    # (dossier, name) pairs
    P = resolve(("Hans Meyer", 1500, "D1"), ("Meyer Hans", 1501, "D1"), ("Hs Meyer", 1502, "D1"))
    assert len(P) == 1
    assert P[0]["d"] == 1 and len(P[0]["dos"]) == 3
