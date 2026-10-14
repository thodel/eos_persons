"""
Regression tests for the srbas name heuristics.

The Basel Jahrrechnungen carry no persName markup, so names are found lexically
in the booking texts (srbas-extraction/extract_names.py) and compared with HGB
name forms (link_srbas_hgb.py). These pin down the inflection handling that
makes the match possible: the accounts write names in the dative/genitive
("empfangen von Jacoben Gebharten", "Daniel Steigers knecht"), the HGB register
in the nominative.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "srbas-extraction"))

from extract_names import find_names, norm_given, norm_surname  # noqa: E402
from link_srbas_hgb import surname_forms, best_surname_ratio, time_fit  # noqa: E402

PLACES = {"muttenz", "liestal", "basel"}


def names(text):
    return [(n["given_norm"], n["surname_norm"]) for n in find_names(text, PLACES)]


@pytest.mark.parametrize("tok,expected", [
    ("Jacoben", "jacob"),       # dative -en
    ("Hansen", "hans"),
    ("Wolffgangen", "wolffgang"),
    ("Petern", "peter"),        # dative -n
    ("Casparn", "caspar"),
    ("Hans", "hans"),           # nominative untouched
    ("Fridlin", "fridlin"),     # -in is part of the name, not an ending
])
def test_given_name_inflection(tok, expected):
    assert norm_given(tok) == expected


def test_surname_genitive_and_dative():
    assert norm_surname("Steigers") == "steiger"          # genitive -s
    assert norm_surname("Nesers") == "neser"
    assert norm_surname("Gebharten", dative=True) == "gebhart"
    assert norm_surname("Gebharten", dative=False) == "gebharten"
    assert norm_surname("Rüdin", dative=True) == "rüdin"  # -in stays


def test_extracts_dative_name_after_von():
    assert names("Item xxv lb empfangen von Steffan Bitterlin von Oberwilen") == [
        ("steffan", "bitterlin")]
    found = list(find_names("empfangen von Jacoben Gebharten, dem metzger", PLACES))
    assert found[0]["surname_norm"] == "gebhart"
    assert found[0]["given_raw"] == "Jacoben"


def test_origin_is_captured_not_taken_as_surname():
    found = list(find_names("von Steffan Bitterlin von Oberwilen", PLACES))
    assert found[0]["origin"] == "Oberwilen"


def test_lowercase_given_uppercase_surname_only():
    # transcription writes given names in lower case too
    assert names("daruf hans Fust sitzet") == [("hans", "fust")]
    # but a lower-case token after a given name is never a surname
    assert names("aber von Wolffen empfangen") == []


def test_particle_surnames_are_kept_whole():
    assert names("von Peter Im Kilchzimmer") == [("peter", "im kilchzimmer")]
    assert names("von Niclaus Zum Rappen") == [("niclaus", "zum rappen")]


def test_saints_feasts_and_places_are_not_persons():
    assert names("uff Sant Peter und Pauli") == []
    assert names("uff Johannis Baptistae") == []
    assert names("von Hans Muttenz") == []          # account place token
    assert names("Hans Jacob") == []                # two given names, no surname


def test_surname_forms_bridge_inflection():
    forms = surname_forms("Gebharten", "gebhart")
    assert {"gebharten", "gebhart"} <= forms
    assert best_surname_ratio(forms, {"gebhart"}, 0.85) == 1.0
    assert best_surname_ratio(surname_forms("Steigers"), {"steiger"}, 0.85) == 1.0
    # unrelated surnames never clear the floor
    assert best_surname_ratio({"gebhart"}, {"wursteisen"}, 0.85) == 0.0


def test_time_fit_rejects_distant_persons():
    srbas = {"years": [1550, 1552, 1555], "y0": 1550, "y1": 1555}
    assert time_fit(srbas, {"y0": 1540, "y1": 1560}, tol=15) == 1.0
    assert time_fit(srbas, {"y0": 1600, "y1": 1620}, tol=15) is None
    partial = time_fit(srbas, {"y0": 1553, "y1": 1570}, tol=15)
    assert 0.5 < partial < 1.0
