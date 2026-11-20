"""
link_zunftmeister.py matches the guild masters with the merged eos persons.
The tests pin the name splitting (the published lists mix `forename surname`
and `surname forename`), the life-span window, and the tiers, then run the
whole join on a miniature of both datasets.
"""
import csv
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import link_zunftmeister as L   # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("Hans Jakob Göbelin", ("Hans Jakob", "Göbelin")),
    ("Peter von Hegenhein", ("Peter", "von Hegenhein")),
    ("Burkart Meyer zum Stampf", ("Burkart Meyer", "zum Stampf")),
    ("Dr. Emanuel Brandmüller", ("Emanuel", "Brandmüller")),
    ("Thomas von Tunsel genannt Silberberg", ("Thomas", "von Tunsel")),
    ("Hans Röl (Roly, Röly)", ("Hans", "Röl")),
    ("Zengerli", ("", "Zengerli")),
])
def test_split_name_forename_first(name, expected):
    assert L.split_name(name) == expected


def test_split_name_surname_first_keeps_particles_with_the_surname():
    assert L.split_name("Krug Caspar", surname_first=True) == ("Caspar", "Krug")
    assert L.split_name("von Oltingen Hans", surname_first=True) == ("Hans", "von Oltingen")


def test_both_name_orders_are_tried():
    assert ("Caspar", "Krug") in L.name_candidates("Krug Caspar")
    assert ("Krug", "Caspar") in L.name_candidates("Krug Caspar")


def test_life_window_prefers_life_dates_over_mentions():
    p = {"birth_year": 1500, "death_year": 1570, "mention_span": [1520, 1560]}
    assert L.life_window(p) == (1522, 1571, "life")
    q = {"mention_span": [1520, 1560]}
    assert L.life_window(q) == (1508, 1572, "mentions")
    assert L.life_window({})[0] is None


def test_master_must_be_alive_and_of_age():
    w = (1522, 1571, "life")
    assert L.fits(w, 1530, None)
    assert not L.fits(w, 1510, None)           # not yet 22
    assert not L.fits(w, 1580, None)           # dead
    assert L.fits(w, 1565, 1580)               # term overlaps the lifetime


def test_tiers():
    w = (1522, 1571, "life")
    assert L.tier_of(1.0, 1.0, w, 1540, None, True, False) == "stark"
    assert L.tier_of(1.0, 1.0, w, 1540, None, False, False) == "wahrscheinlich"
    assert L.tier_of(0.9, 0.9, w, 1540, None, False, True) == "wahrscheinlich"
    assert L.tier_of(0.91, 1.0, w, 1540, None, False, False) == "wahrscheinlich"   # Fäsch / Faesch
    assert L.tier_of(1.0, 0.85, w, 1540, None, False, False) == "möglich"          # given name differs
    assert L.tier_of(1.0, 1.0, (1508, 1572, "mentions"), 1540, None, True, True) == "möglich"
    assert L.tier_of(1.0, 1.0, w, 1600, None, True, True) is None


def test_a_conflicting_given_name_count_is_never_exact():
    p = {"surname": "Brandmüller", "given": "Johannes"}
    sr, gr = L.score_pair(L.name_candidates("Hans Heinrich Brandmüller"), p)
    assert sr == 1.0 and gr <= 0.85


def test_join_on_a_miniature(tmp_path):
    masters = tmp_path / "z.csv"
    masters.write_text(
        "zunft,year_from,year_to,name,note,source\n"
        "Hausgenossen,1534,1542,Jakob Rüdin,Stadtwechsler,x\n"
        "Schmieden,1557,,Krug Caspar,Oberzunftmeister,x\n"
        "Safran,1850,,Friedrich Hagenbach,Apotheker,x\n"            # after the corpus
        "Safran,1545,,Hans Meyer,Krämer,x\n",                        # no such person
        encoding="utf-8")
    persons = [
        {"id": "person:1", "name": "Jakob Rüdin", "surname": "Rüdin", "given": "Jakob",
         "birth_year": 1501, "death_year": 1573, "mention_span": [1530, 1560],
         "occupations": ["Wechsler"], "titles": ["Oberstzunftmeister"], "roles_gnd": [],
         "organisations": [], "status": "merged", "authority": {"wikidata": ["Q1"], "gnd": ["2"]}},
        {"id": "person:2", "name": "Caspar Krug", "surname": "Krug", "given": "Caspar",
         "birth_year": 1518, "death_year": 1579, "mention_span": [1540, 1570],
         "occupations": [], "titles": [], "roles_gnd": [], "organisations": [],
         "status": "merged", "authority": {}},
        {"id": "person:3", "name": "Hans Meyer", "surname": "Meyer", "given": "Hans",
         "birth_year": 1400, "death_year": 1460, "mention_span": [1420, 1455],
         "occupations": [], "titles": [], "roles_gnd": [], "organisations": [],
         "status": "merged", "authority": {}},
    ]
    rows = L.link(str(masters), persons)
    got = {(r["master"], r["person_id"]): r["tier"] for r in rows}
    assert got == {("Jakob Rüdin", "person:1"): "stark", ("Krug Caspar", "person:2"): "wahrscheinlich"}
    assert rows[0]["wikidata"] == "Q1"
