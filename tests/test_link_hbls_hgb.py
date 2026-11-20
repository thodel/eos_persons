"""
link_hbls_hgb.direct_pass compares every HBLS person with every register person
of a similar name. These tests pin what the identity clusters rely on: the
candidates of one person come best first with ties in index order, dates are
checked (a namesake of another century is no candidate), and each row says
whether the HBLS person is connected to Basel — elsewhere a match on name and
dates is a namesake from another canton.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import link_hbls_hgb as L     # noqa: E402


def hgb(name, given, surname, m0, m1):
    return {"name": name, "given": given, "surname": surname, "m0": m0, "m1": m1,
            "dead": None, "ment": 3, "dos": 1}


def hbls(pid, given, surname, b, d, bio):
    return {"id": pid, "name": f"{given} {surname}", "given": given, "surname": surname,
            "keyword": surname.upper(), "birth_year": b, "death_year": d,
            "floruit_years": None, "bio": bio, "volume": 1, "page": 1, "backlink": "u"}


BY_INITIAL = {"m": [
    hgb("Andres Mitz", "andres", "mitz", 1660, 1684),
    hgb("Andreas Mitz", "andreas", "mitz", 1650, 1680),
    hgb("Andreas Mitz", "andreas", "mitz", 1440, 1460),        # another century
    hgb("Andreas Metz", "andreas", "metz", 1650, 1680),        # another surname
    hgb("Jakob Mettler", "jakob", "mettler", 1640, 1660),
]}


def test_candidates_are_dated_ranked_and_carry_the_basel_connection(monkeypatch):
    monkeypatch.setattr(L, "HERE", "/nonexistent")             # no article texts
    persons = [
        hbls("hbls:1:1", "Andreas", "Mitz", 1633, 1686, "1633-1686, Handelsmann zu Basel, des Rats"),
        hbls("hbls:1:2", "Jakob", "Mettler", None, 1727, "von Urnäsch, Landessäckelmeister 1695-1697"),
    ]
    rows, matched = L.direct_pass(persons, BY_INITIAL, 0.85, 0.74, 60)
    assert matched == 2
    mitz = [r for r in rows if r["hbls_id"] == "hbls:1:1"]
    # the two register persons of his own time, the exact spelling first
    assert [(r["hgb_name"], r["hgb_year_min"]) for r in mitz] == \
        [("Andreas Mitz", 1650), ("Andres Mitz", 1660)]
    assert all(r["n_candidates"] == 2 and r["hbls_basel"] == "bio" for r in mitz)
    mettler = [r for r in rows if r["hbls_id"] == "hbls:1:2"]
    assert len(mettler) == 1 and mettler[0]["hbls_basel"] == ""


def test_basel_connection_reads_bio_and_family_article(tmp_path, monkeypatch):
    import json
    (tmp_path / "hbls-extraction").mkdir()
    (tmp_path / "hbls-extraction" / "hbls_articles.json").write_text(json.dumps([
        {"source_file": "band_1.pdf", "page": 1, "keyword": "MITZ",
         "content": "MITZ. Familie der Stadt Basel, seit 1570 eingebürgert."},
        {"source_file": "band_1.pdf", "page": 2, "keyword": "METTLER",
         "content": "METTLER. Familien der Kantone Appenzell und Schwyz."},
    ]), encoding="utf-8")
    monkeypatch.setattr(L, "HERE", str(tmp_path))
    a = hbls("a", "Benedikt", "Mitz", 1665, 1738, "1665-1738, des Rats")
    b = hbls("b", "Jakob", "Mettler", None, 1727, "von Urnäsch"); b["page"] = 2
    c = hbls("c", "Jakob", "Mettler", None, 1700, "Bürger zu Basel 1650"); c["page"] = 2
    assert L.basel_connection([a, b, c]) == {"a": "article", "c": "bio"}
