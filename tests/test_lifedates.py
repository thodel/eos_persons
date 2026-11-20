"""
The life of an HLS-linked person, checked mention by mention (lifedates.py).

These tests pin how the dates of an HLS header are read with their qualifiers,
how Wikidata's dates enter as a second opinion, what a life excludes for a
single mention, and how a person whose mentions reach outside the life is
split — the same-named father before, the same-named son after.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_data                  # noqa: E402
import lifedates as LD             # noqa: E402
from lifedates import Life         # noqa: E402

AUTHOR = "Autorin/Autor: Erika Muster "


@pytest.mark.parametrize("head,b,d,kinds", [
    ("25.3.1621 Basel, 15.2.1687 Frankfurt am Main, ref., von Basel. Sohn des Hans.",
     1621, 1687, ("exact", "exact")),
    ("um 1485 Thann (Elsass), nach 1535, von Thann. 1511 Margareth Öder.",
     1485, 1535, ("circa", "after")),
    ("Erstmals erw. 1505, vor dem 3.4.1551 Basel, von Basel. Sohn des Hans.",
     1505, 1551, ("first_mention", "before")),
    ("1444 erstmals erwähnt, zwischen 1496 und 1499 Basel, aus Rottenburg am Neckar.",
     1444, 1499, ("first_mention", "range")),
    ("Erstmals 1462, letztmals 1499 erwähnt, aus Strassburg, ab 1473 von Basel.",
     1462, 1499, ("first_mention", "last_mention")),
    ("vor 1460 Solothurn, 1517 Lyon, katholisch, von Solothurn.",
     1460, 1517, ("before", "exact")),
    ("um 1465 Freiburg. Erwähnt zwischen 1480 und 1523 .",
     1465, 1523, ("circa", "last_mention")),
    ("1494/1496 Basel, 9.3.1575 Basel, von Basel.", 1494, 1575, ("range", "exact")),
    # a caption before the author line does not count
    ("Porträt von 1650 in der Bibliothek. " + AUTHOR + "um 1590 Basel, 1664 Basel.",
     1590, 1664, ("circa", "exact")),
])
def test_the_qualifiers_of_an_hls_header(head, b, d, kinds):
    text = head if "Autorin" in head else AUTHOR + head
    assert LD.date_kinds(text, b, d) == kinds


def test_a_year_that_is_not_in_the_header_has_no_kind():
    assert LD.date_kinds(AUTHOR + "1557/60 Biel, 1597/98 Bern, ab 1581 von Basel.",
                         1557, 1595) == ("range", None)


def test_bounds_follow_the_qualifier():
    assert LD.bounds(1620, "exact", 1683, "exact") == Life(1620, 1620, 1683, 1683)
    assert LD.bounds(1485, "circa", 1535, "after") == Life(1480, 1490, 1535, 1575)
    # first mentioned 1505: an adult then, born 1435–1491
    assert LD.bounds(1505, "first_mention", 1551, "before") == Life(1435, 1491, 1541, 1551)
    assert LD.bounds(None, None, None, None) is None
    # one date only: the other end is fenced by a long life
    assert LD.bounds(None, None, 1530, "exact") == Life(1430, 1516, 1530, 1530)
    assert LD.bounds(1492, "exact", None, None) == Life(1492, 1492, 1506, 1587)


def test_wikidata_is_a_second_opinion():
    # a birth year for somebody the HLS only knows from a first mention
    assert LD.bounds(1505, "first_mention", 1551, "exact", wd_b=[1482, 1490]) \
        == Life(1477, 1495, 1551, 1551)
    # … unless it does not respect the fence (Wikidata repeats the first mention)
    assert LD.bounds(1444, "first_mention", 1499, "exact", wd_b=[1444]).bhi == 1430
    # "vor 1594" and Wikidata's 1578
    assert LD.bounds(1513, "circa", 1594, "before", wd_d=[1578])[2:] == (1577, 1579)
    # "letztmals 1528" against a death in 1511: the last mention stands
    assert LD.bounds(1505, "first_mention", 1528, "last_mention", wd_d=[1511]).dlo == 1528
    # two firm dates that disagree: the life holds both (Henman Offenburg)
    assert LD.bounds(1379, "exact", 1459, "exact", wd_d=[1454])[2:] == (1454, 1459)
    assert LD.bounds(1620, "exact", 1683, "exact", wd_b=[1620], wd_d=[1683]) \
        == Life(1620, 1620, 1683, 1683)


LIFE = Life(1620, 1620, 1683, 1683)


@pytest.mark.parametrize("year,late,strong,kind", [
    (1650, False, True, None),
    (1619, False, False, "before_birth"),
    (1630, False, True, "child"),            # a buyer at ten
    (1630, False, False, None),              # named at ten: the heir of a house
    (1684, False, True, None),               # within a year of the death
    (1686, False, True, "after_death"),
    (1690, False, False, None),              # the neighbour's house keeps the name
    (1700, False, False, "late_naming"),
    (1700, True, False, None),               # "selig"
    (1680, True, False, "dead_early"),       # called deceased three years early
    (1750, True, False, "beyond"),
])
def test_what_the_life_excludes_for_one_mention(year, late, strong, kind):
    assert LD.mention_conflict(LIFE, year, late, strong) == kind


def test_a_role_of_the_past_names_nobody_as_living():
    assert LD.mention_conflict(LIFE, 1700, False, False, past=True) is None
    assert LD.mention_conflict(LIFE, 1700, False, False, past=False) == "late_naming"
    # … and so stays with the dead man when a later bearer appears
    ms = [(1650, False, True, False), (1688, False, False, True), (1692, False, True, False)]
    assert LD.partition(LIFE, ms)[0] == ["F", "F", "L"]


def test_partition_father_person_son():
    ms = [(1616, False, False), (1625, False, True),          # the father
          (1632, False, False),                               # … and what follows him
          (1640, False, True), (1670, False, True), (1683, False, False),
          (1690, True, False),                                # the late X
          (1692, False, True), (1695, False, False),          # the son acts, and is named
          (1699, True, False)]                                # the son's own death
    labels, kinds = LD.partition(LIFE, ms)
    assert labels == ["E", "E", "E", "F", "F", "F", "F", "L", "L", "L"]
    assert kinds == {"before_birth": 1, "child": 1, "after_death": 1}


def test_partition_without_conflict_keeps_everything():
    ms = [(1640, False, True), (1690, False, False), (1700, True, False)]
    assert LD.partition(LIFE, ms)[0] == ["F", "F", "F"]


def test_nothing_of_the_lifetime_nothing_at_all():
    # Johannes Buxtorf died in 1629; a Johann Buxtorf pays, sues and sells from
    # 1630 to 1684 — the son and the grandson
    life = Life(1564, 1564, 1629, 1629)
    ms = [(1630, False, False), (1635, False, False), (1650, False, True), (1684, True, False)]
    assert LD.partition(life, ms)[0] == ["L", "L", "L", "L"]


def test_a_deceased_mention_before_the_death_is_an_earlier_bearer():
    ms = [(1650, False, True), (1659, True, False), (1670, False, True)]
    labels, kinds = LD.partition(LIFE, ms)
    assert labels == ["F", "E", "F"] and kinds == {"dead_early": 1}


# ── a person taken apart by its mentions (build_data.split_person) ───────────

def mention(year, name="Hans Rudolf Burckhardt", dossier="HGB_1_001_001", dead=0, roles="",
            occ="unk"):
    return {"name": name, "year": year, "dossierid": dossier, "is_deceased": dead,
            "roles": roles, "occupation_norm": occ, "title": None, "family_relation": None,
            "location": None, "org_affiliation": None}


def test_split_person_keeps_every_mention_once():
    df = pd.DataFrame([
        mention(1616, roles="location-b"), mention(1625, roles="seller", occ="krämer"),
        mention(1640, roles="buyer", dossier="HGB_1_001_002"),
        mention(1670, roles="seller|owner", occ="bürgermeister"),
        mention(1690, dead=1), mention(1695, roles="buyer", dossier="HGB_1_001_002"),
    ])
    rows = build_data.prepare_rows(df)
    assert [r["_strong"] for r in rows] == [False, True, True, True, False, True]
    entries = [build_data.summarise(("HGB_1_001_001", "Hans Rudolf Burckhardt"),
                                    [rows[i] for i in (0, 1, 3, 4)]),
               build_data.summarise(("HGB_1_001_002", "Hans Rudolf Burckhardt"),
                                    [rows[i] for i in (2, 5)])]
    whole = build_data.assemble(entries)
    assert (whole["c"], whole["y"], whole["d"], whole["a"]) == (6, [1616, 1695], 2, [1625, 1695])

    idx = [i for _, js in whole["_rows"] for i in js]
    labels, _ = LD.partition(LIFE, [(rows[i]["_year"], rows[i]["_dead"], rows[i]["_strong"])
                                    for i in idx])
    lab = dict(zip(idx, labels))
    parts = build_data.split_person(whole["_rows"], rows, lambda r: lab[r["_i"]])
    assert {k: (p["c"], p["y"]) for k, p in parts.items()} == {
        "E": (2, [1616, 1625]), "F": (3, [1640, 1690]), "L": (1, [1695, 1695])}
    assert sum(p["c"] for p in parts.values()) == whole["c"]
    assert parts["F"]["dead_year"] == 1690 and parts["F"]["a"] == [1640, 1670]
    assert parts["F"]["occ"] == ["bürgermeister"] and parts["E"]["occ"] == ["krämer"]
    assert parts["F"]["d"] == 2 and parts["L"]["dos"] == [("HGB_1_001_002", "Hans Rudolf Burckhardt")]
    assert parts["F"]["ly"] == 1670 and "ly" not in parts["L"]      # last year named as living
    assert LD.fits(LIFE, *parts["F"]["y"], parts["F"]["dead_year"], *LD.extra(parts["F"]))
    assert not LD.fits(LIFE, *whole["y"], whole["dead_year"], *LD.extra(whole))


def test_named_as_living_long_after_the_death_does_not_fit():
    # called deceased in 1690 — and named as living in 1705: a later bearer
    late = {"y": [1650, 1705], "dead_year": 1690, "ly": 1705}
    assert not LD.fits(LIFE, 1650, 1705, 1690, *LD.extra(late))
    ok = {"y": [1650, 1705], "dead_year": 1690, "ly": 1689}
    assert LD.fits(LIFE, 1650, 1705, 1690, *LD.extra(ok))
    # the last mention of somebody never called deceased is one as living …
    assert LD.extra({"y": [1650, 1705]}) == (None, 1705)
    assert not LD.fits(LIFE, 1650, 1705, None, *LD.extra({"y": [1650, 1705]}))
    # … unless it names a role of the past (ly: the last year as living)
    assert LD.fits(LIFE, 1650, 1705, None, *LD.extra({"y": [1650, 1705], "ly": 1680}))
    assert LD.extra({"y": [1700, 1705], "dead_year": 1700, "ly": 0}) == (None, None)
    # taken together the later of the two counts
    assert LD.extra_merge(LD.extra(ok), LD.extra({"y": [1660, 1701], "a": [1660, 1670]})) \
        == ([1660, 1670], 1701)
