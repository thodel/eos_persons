"""
extract_genealogy.extract reads parents and spouses from the lead of an HLS
biography. The sentences below are made in the pattern of the articles; they pin
that a name keeps the particles inside it and that one stray word is no spouse.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_genealogy as G     # noqa: E402


def names(spouses):
    return {s["n"]: s["y"] for s in spouses}


def test_parents_and_numbered_marriages():
    f, m, sp = G.extract(
        "1450, 1510 Basel, von Basel. Sohn des Heinrich, Schaffners, und der Greda Kern. "
        "1) 1479 Elisabeth Schilling, 2) 1483 Dorothea Wasserhun. Wechsler und Kaufmann.",
        "Muster")
    assert (f, m) == ("Heinrich Muster", "Greda Kern")     # the father shares the surname
    assert names(sp) == {"Elisabeth Schilling": 1479, "Dorothea Wasserhun": 1483}


def test_a_name_keeps_its_particles():
    _, m, sp = G.extract(
        "Sohn des Hans Bernhard, Vogts, und der Susanna Bock von Staufenberg. "
        "1) 1499 Barbara von Andlau, Tochter des Hans, Ritters, "
        "2) 1503 Helena Meyer zum Pfeil, Tochter des Claus, Ratschreibers.", "Muster")
    assert m == "Susanna Bock von Staufenberg"
    assert names(sp) == {"Barbara von Andlau": 1499, "Helena Meyer zum Pfeil": 1503}


def test_one_word_is_no_spouse():
    # the trade of the bride's father, and given names without a surname
    _, _, sp = G.extract(
        "Sohn des Andreas, Schaffners. 1547 Margaretha Uelin, Tochter des Matthias, Wirts, "
        "Witwe des Wolfgang Schnitzer.", "Muster")
    assert names(sp) == {"Margaretha Uelin": 1547}
    _, _, sp = G.extract("aus Rottenburg. 1) Margaretha, 2) Katharina (Nachnamen unbekannt).",
                         "Muster")
    assert sp == []
