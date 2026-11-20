"""
The HLS covers all of Switzerland, the register one town: link_hls only takes an
article as a candidate when its text ties the person to Basel. These tests pin
the three classes on the patterns HLS biographies are written in.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from link_hls import basel_relation     # noqa: E402


@pytest.mark.parametrize("text", [
    "25.3.1621 Basel, 15.2.1687 Frankfurt am Main, ref., von Basel, ab 1626 von Frankfurt.",
    "Erstmals erwähnt 1470 Basel, vor dem 3.6.1500. Sohn des Hans.",
    "Erstmals erw. 1396, nach 1400, Bürger von Basel und Luzern. Kaufmann.",
    "um 1485 Thann (Elsass), nach 1535, von Thann. 1511 kam er als Goldschmied nach Basel.",
    "1356 erstmals erw., 1399. Lehensträger des Bf. von Basel. Mitglied des Basler Rates.",
    "Ab 1425 wirkte er als Schaffner Wettingens in Basel, wo er sich später niederliess.",
    # no single strong phrase, but Basel is what the article is about
    "Ab 1469 in Basel, Rektor der Universität Basel, Prädikant zu St. Peter; verliess Basel 1529.",
])
def test_persons_of_the_town_are_strong(text):
    assert basel_relation(text) == "strong"


@pytest.mark.parametrize("text", [
    "27.12.1448, 20.2.1521 wohl Wettingen, von Baden. 1461 Stud. in Basel, 1463 Eintritt ins Kloster.",
    "1524 Altstätten, 1574 Warschau, von Zürich. 1540-1541 Student in Basel.",
    "Im Galgenkrieg 1531 vermittelte er zwischen Basel und Solothurn.",
    "1415 erstmals erwähnt, 1444 Konstanz. Teilnahme am Basler Konzil.",
    # the prince-bishop is not the town
    "Vermittler in einem Streit zwischen dem Fürstbf. von Basel mit Bern und Biel.",
    "Rat im Dienst des Fürstbischofs von Basel, 1692-1703 Obervogt.",
    "22.8.1444 St. Jakob an der Birs (Gemeinde Basel), katholisch, von Zug.",
])
def test_a_passing_mention_is_weak(text):
    assert basel_relation(text) == "weak"


def test_no_mention_and_no_text():
    assert basel_relation("Erstmals erwähnt 1538, 8.4.1585, katholisch, von Zug. "
                          "Sohn des Hans, Säckelmeisters.") == "none"
    assert basel_relation("") == ""          # unknown: the public table has no texts
    assert basel_relation(None) == ""
