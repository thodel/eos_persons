"""
link_bli_hgb.py joins the actor list of "Basler Liegenschaften 1400–1700
Interaktiv" (BLI) with the eos person lists. These tests pin the three things
the join stands on — the name key, the document crosswalk for re-issued
register cards, the mention → person lookup — and run the whole script once on
a miniature of both datasets, built so that each of the main finding types has
to come out.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import link_bli_hgb as L   # noqa: E402


def test_name_key_bridges_the_two_tokenisations():
    # eos keeps the corpus tokens apart, BLI glues punctuation back on
    assert L.nkey("Joh . Grefin") == L.nkey("Joh. Grefin") == "joh grefin"
    assert L.nkey("Fridlin , Hüslern") == "fridlin hüslern"
    assert L.nkey("  Hans   MEYER ") == "hans meyer"


@pytest.mark.parametrize("a,b,expected", [
    ("Marx Harder", "Marx Harders", "spelling"),             # genitive
    ("Johann Groß", "Hanns Gross", "spelling"),              # Hanns = Johann
    ("Emanuel Schönauwer", "Emanuel Schönawer", "spelling"),
    ("Hans Meyer", "Hans Heinrich Meyer", "given_name_count"),
    ("Caspar Krug", "Caspar Kang", "surname_differs"),
    ("Peter Meyer", "Claus Meyer", "given_differs"),
    ("Elsin", "Elsin Stegerin", "bare_name"),
    ("Michel Bader", "Mantzen", "different"),
])
def test_name_relation(a, b, expected):
    assert L.name_relation(a, b) == expected
    assert L.name_relation(b, a) == expected


def test_group_relation_judges_persons_by_their_closest_spellings():
    # two persons, each known under two spellings: the closest pair decides
    assert L.group_relation([["Peter Dürring", "Petter Bürrung"],
                             ["Peter Thüring"]]) == "spelling"
    assert L.group_relation([["Hans Meyer"], ["Hans Meyers"], ["Claus Meyer"]]) == "given_differs"


def test_reissued_documents_are_matched_by_their_page_images():
    bli = {"a_20260528": {"dossier": "D1", "y": 1500, "img": ["u1"]},
           "b_20260528": {"dossier": "D1", "y": 1510, "img": ["u2", "u3"]},
           "c_20260528": {"dossier": "D1", "y": 1520, "img": ["gone"]}}
    eos = {"a_20260528": {"dossier": "D1", "year": 1500, "pages": ["u1"]},
           "z_20260615": {"dossier": "D1", "year": 1510, "pages": ["u3", "u2"]},
           "n_20260615": {"dossier": "D2", "year": 1600, "pages": ["new"]}}
    xw, reissued = L.doc_crosswalk(bli, eos)
    assert xw == {"a_20260528": "a_20260528", "b_20260528": "z_20260615"}
    assert reissued == {"b_20260528": "z_20260615"}


def _person(n, y, dos, c=1, **kw):
    return {"n": n, "v": [n], "c": c, "d": len(dos), "y": y, "dead_year": None,
            "dos": [[d, n] for d in dos], **kw}


def test_mention_lookup_statuses():
    P = [_person("Hans Meyer", [1500, 1520], ["D1"]),
         _person("Hans Meyer", [1600, 1620], ["D1"]),
         _person("Anna Roth", [1500, 1510], ["D2"], c=5),
         _person("Anna Roth", [1505, 1506], ["D2"], c=1)]
    CI = L.CorpusIndex(P)
    k = L.nkey("Hans Meyer")
    assert CI.resolve("D1", k, 1510)[:2] == (0, "unique")
    assert CI.resolve("D1", k, 1610)[:2] == (1, "unique")
    assert CI.resolve("D1", k, 1560)[1] == "year_outside"
    i, st, cands = CI.resolve("D2", L.nkey("Anna Roth"), 1505)
    assert st == "ambiguous" and sorted(cands) == [2, 3]
    assert CI.resolve("D9", "nobody here", 1500)[:2] == (None, "unmapped")


# ── the whole script on a miniature ──────────────────────────────────────────

DOS = "HGB_1_001_001"


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    d = tmp_path_factory.mktemp("mini")
    bli = d / "bli" / "prepare_data"
    bli.mkdir(parents=True)
    actors = {
        # one owner under two spellings — eos lists two persons
        "actor_0": {"c": "per", "n": "Peter Dürring",
                    "variants": ["Peter Dürring", "Peter Thüring"],
                    "doc": {"owner": ["d1_20260528", "d2_20260528"]}},
        # unnamed reference: must not be linked or reported as a gap
        "actor_1": {"c": "per", "n": "der Schaffner zu Klingental",
                    "doc": {"owner": "d1_20260528"}},
        # two women of the same bare name, 60 years apart — eos has one person
        "actor_2": {"c": "per", "n": "Elsin", "variants": ["Elsin"],
                    "doc": {"owner": "d3_20260528"}},
        "actor_3": {"c": "per", "n": "Elsin", "variants": ["Elsin"],
                    "doc": {"owner": "d4_20260528"}},
        # neighbour without documents, placed by the id order
        "actor_4": {"c": "per", "n": "Claus Roth", "variants": ["Claus Roth"]},
        "actor_5": {"c": "per", "n": "widow of Claus Roth", "rel": {"widow": ["actor_4"]}},
        "actor_6": {"c": "per", "n": "Hans Gut", "variants": ["Hans Gut"],
                    "doc": {"owner": "d5_20260528"}},
        "actor_7": {"c": "org", "n": "Spital", "variants": ["Spital"]},
    }
    docs = {
        "d1_20260528": {"y": 1596, "txt": "", "img": ["u1"], "dossier": DOS},
        "d2_20260528": {"y": 1602, "txt": "", "img": ["u2"], "dossier": DOS},
        "d3_20260528": {"y": 1440, "txt": "", "img": ["u3"], "dossier": DOS},
        "d4_20260528": {"y": 1500, "txt": "", "img": ["u4"], "dossier": DOS},
        "d5_20260528": {"y": 1610, "txt": "", "img": ["u5a", "u5b"], "dossier": DOS},
    }
    h = [{"p": "actor_0", "s": 1596, "e": 1602, "fc": 1596, "lc": 1602, "doc": []},
         {"p": "actor_2", "s": 1440, "e": 1440, "fc": 1440, "lc": 1440, "doc": []},
         {"p": "actor_3", "s": 1500, "e": 1500, "fc": 1500, "lc": 1500, "doc": []}]
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
         "properties": {"id": DOS, "adrs": "Teststrasse 1", "d": list(docs), "h": json.dumps(h)}}]}
    (bli / "actors.json").write_text(json.dumps(actors), encoding="utf-8")
    (bli / "documents.json").write_text(json.dumps(docs), encoding="utf-8")
    (bli / "geometries.geojson").write_text(json.dumps(geo), encoding="utf-8")

    # eos side: d5 was re-issued under a new id; one document is new
    with open(d / "documents.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "dossierid", "street_id", "year", "source",
                    "checked_by_gpt", "n_persons", "page_urls"])
        for did, y, pages in [("d1_20260528", 1596, "u1"), ("d2_20260528", 1602, "u2"),
                              ("d3_20260528", 1440, "u3"), ("d4_20260528", 1500, "u4"),
                              ("d5new_20260615", 1610, "u5b|u5a"),
                              ("d6_20260615", 1650, "u6")]:
            w.writerow([did, DOS, "HGB_1_001", y, "Gerichtsarchiv", 0, 1, pages])
    mentions = [("d1_20260528", "Peter Dürring", 1596), ("d1_20260528", "Claus Roth", 1596),
                ("d2_20260528", "Peter Thüring", 1602), ("d3_20260528", "Elsin", 1440),
                ("d4_20260528", "Elsin", 1500), ("d5new_20260615", "Hans Gut", 1610),
                # the index's own evidence: 'Marti Streiff' is a person here and,
                # from another dossier, a variant of 'Martin Streiff' who is here too
                ("d1_20260528", "Martin Streiff", 1596), ("d2_20260528", "Marti Streiff", 1602)]
    cols = ["doc_id", "dossierid", "street_id", "year", "source", "checked_by_gpt",
            "span_id", "name", "alias", "numerus", "specificity", "confidence",
            "occupation_text", "occupation_norm", "occupation_ohdab", "title",
            "family_relation", "location", "org_affiliation", "is_deceased", "roles",
            "page_url"]
    with open(d / "persons.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, (doc, name, y) in enumerate(mentions):
            w.writerow({"doc_id": doc, "dossierid": DOS, "street_id": "HGB_1_001",
                        "year": y, "span_id": i, "name": name, "is_deceased": 0})
    persons = [_person("Peter Dürring", [1596, 1596], [DOS]),
               _person("Peter Thüring", [1602, 1602], [DOS]),
               _person("Elsin", [1440, 1500], [DOS], c=2),
               _person("Claus Roth", [1596, 1596], [DOS]),
               _person("Hans Gut", [1610, 1610], [DOS]),
               {**_person("Martin Streiff", [1596, 1602], [DOS], c=3),
                "v": ["Martin Streiff", "Marti Streiff"]},
               _person("Marti Streiff", [1602, 1602], [DOS])]
    (d / "persons_resolved.json").write_text(json.dumps(persons), encoding="utf-8")
    out = {k: str(d / v) for k, v in [("out", "link.csv"), ("findings", "findings.csv"),
                                      ("report", "report.md"), ("docxw", "docxw.csv"),
                                      ("candidates", "candidates.csv")]}
    L.main(["--bli", str(d / "bli"), "--persons", str(d / "persons_resolved.json"),
            "--mentions", str(d / "persons.csv"), "--documents", str(d / "documents.csv"),
            "--street", str(d / "no_street_index.json"),
            "--out", out["out"], "--findings", out["findings"],
            "--report", out["report"], "--docxw", out["docxw"],
            "--candidates", out["candidates"]])
    read = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
    return {"link": {r["actor_id"]: r for r in read(out["out"])},
            "findings": read(out["findings"]), "docxw": read(out["docxw"]),
            "candidates": read(out["candidates"]), "dir": d,
            "report": Path(out["report"]).read_text(encoding="utf-8")}


def test_only_named_person_actors_are_listed(mini):
    assert set(mini["link"]) == {"actor_0", "actor_2", "actor_3", "actor_4", "actor_6"}


def test_owner_is_linked_through_its_documents(mini):
    r = mini["link"]["actor_0"]
    assert r["link_level"] == "doc" and r["n_owner_docs"] == "2" and r["n_persons"] == "2"
    assert "Peter Dürring#1596-1596" in r["persons"] and "Peter Thüring#1602-1602" in r["persons"]


def test_neighbour_is_placed_by_the_id_order(mini):
    r = mini["link"]["actor_4"]
    assert (r["dossier_source"], r["link_level"], r["dossiers"]) == ("id_block", "dossier", DOS)
    assert r["persons"] == "Claus Roth#1596-1596"


def test_reissued_document_carries_the_link(mini):
    assert mini["docxw"] == [{"bli_doc_id": "d5_20260528", "eos_doc_id": "d5new_20260615",
                              "dossier": DOS, "year": "1610"}]
    assert mini["link"]["actor_6"]["link_level"] == "doc"


def test_findings_name_both_kinds_of_disagreement(mini):
    kinds = {f["type"]: f for f in mini["findings"]}
    split = kinds["eos_split_spelling_variants"]
    assert split["likely_side"] == "eos" and "actor_0" in split["bli"]
    merged = kinds["eos_merges_owners_decades_apart"]
    assert "actor_2" in merged["bli"] and "actor_3" in merged["bli"]
    assert "bare given name" in merged["eos"] and merged["severity"] == "3"
    assert kinds["documents_missing_in_bli"]["eos"] == "1 documents"
    # the unnamed 'Schaffner' owner is not an extraction gap
    assert "owner_document_without_eos_mention" not in kinds
    assert "owner_name_not_in_eos" not in kinds


def test_report_is_written(mini):
    assert "## Findings by type" in mini["report"]
    assert "eos_split_spelling_variants" in mini["report"]


def test_spelling_pairs_are_written_as_dedupe_candidates(mini):
    by_src = {c["sources"]: c for c in mini["candidates"]}
    assert set(by_src) == {"bli", "dossier"}
    c = by_src["bli"]
    assert {c["a_key"], c["b_key"]} == {"Peter Dürring#1596-1596", "Peter Thüring#1602-1602"}
    assert c["bli_actors"] == "actor_0"
    # no BLI actor and no street index needed for this one
    c = by_src["dossier"]
    assert {c["a_key"], c["b_key"]} == {"Martin Streiff#1596-1602", "Marti Streiff#1602-1602"}
    assert c["where"] == DOS
