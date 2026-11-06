"""
Human Lineage link stage (link_humanlineage.py) and what the site makes of it.

The join is an identity join (QID, or HLS id via Wikidata P902) on the server's
side and a Human Lineage id join on ours: a relative becomes a cross-link only
when the register person it points to was itself joined — never by name. The
dump asserts parents and couples, not siblings (the server derives those), so
no sibling ever reaches `hl` or the family graph. And the licence (CC BY-SA 4.0)
asks for the credit with the profile URL wherever the data is shown.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import link_humanlineage as L      # noqa: E402
import make_persons_web as W       # noqa: E402

SNAP = "2026-10-10"

FELIX_FULL = {   # shape of a `get_person` answer, trimmed
    "id": "HLH34AEMHQ8C", "name": "Felix Platter", "gender": "male",
    "birth_year": 1605, "death_year": 1671, "wikidata_id": "Q18624068",
    "tree": 2348, "url": "https://humanlineage.org/person/HLH34AEMHQ8C",
    "relatives": {
        "parents": [{"id": "HLZ3TBQ5SMTB", "name": "Thomas Platter der Jüngere",
                     "gender": "male", "wikidata_id": "Q116577"},
                    {"id": "HLMOTHER0001", "name": "Chrischona Jeckelmann",
                     "gender": "female", "wikidata_id": "Q99999901"}],
        "children": [],
        "spouses": [{"id": "HLSPOUSE0001", "name": "Helena Bischoff",
                     "gender": "female", "wikidata_id": None}],
        "siblings": [{"id": "HLH2FJFEWG9Y", "name": "Thomas Platter III",
                      "gender": "male", "wikidata_id": "Q134902714"}],
        "siblings_derived": True,
    },
    "snapshot": SNAP,
}
THOMAS_FULL = {
    "id": "HLZ3TBQ5SMTB", "name": "Thomas Platter der Jüngere", "gender": "male",
    "birth_year": 1574, "death_year": 1628, "wikidata_id": "Q116577", "tree": 2348,
    "url": "https://humanlineage.org/person/HLZ3TBQ5SMTB",
    "relatives": {"parents": [], "spouses": [],
                  "children": [{"id": "HLH34AEMHQ8C", "name": "Felix Platter",
                                "gender": "male", "wikidata_id": "Q18624068"},
                               {"id": "HLH2FJFEWG9Y", "name": "Thomas Platter III",
                                "gender": "male", "wikidata_id": "Q134902714"}],
                  "siblings": [], "siblings_derived": True},
    "snapshot": SNAP,
}


@pytest.fixture
def corpus():
    """Two register persons joined to the two profiles above; the mother,
    the spouse and the brother are not in the register."""
    felix = {"n": "Felix Platters", "y": [1638, 1682], "c": 3,
             "wd": {"qid": "Q18624068"}, "hl": L.hl_record(FELIX_FULL)}
    thomas = {"n": "Thomas Platterns", "y": [1600, 1628], "c": 5,
              "wd": {"qid": "Q116577"}, "hl": L.hl_record(THOMAS_FULL)}
    by_hlid = {"HLH34AEMHQ8C": felix, "HLZ3TBQ5SMTB": thomas}
    return felix, thomas, by_hlid


def test_hl_record_has_the_rendering_fields():
    hl = L.hl_record(FELIX_FULL)
    assert set(hl) == {"id", "url", "n", "b", "d", "parents", "children",
                       "spouses", "tree", "snapshot"}
    assert hl["id"] == "HLH34AEMHQ8C" and hl["url"].endswith("/person/HLH34AEMHQ8C")
    assert (hl["b"], hl["d"], hl["tree"], hl["snapshot"]) == (1605, 1671, 2348, SNAP)
    assert hl["parents"][0] == {"n": "Thomas Platter der Jüngere", "qid": "Q116577",
                                "id": "HLZ3TBQ5SMTB", "g": "m"}
    assert hl["spouses"][0]["qid"] is None and hl["spouses"][0]["g"] == "f"
    assert "siblings" not in hl, "siblings are derived by the server, not asserted"
    assert "status" not in hl
    assert L.hl_record(FELIX_FULL, "ambiguous")["status"] == "ambiguous"


def test_kinlinks_only_for_relatives_that_are_register_persons(corpus):
    felix, thomas, by_hlid = corpus
    assert L.kinlinks(felix["hl"], by_hlid) == [
        {"role": "Vater", "name": "Thomas Platterns", "qid": "Q116577", "hlid": "HLZ3TBQ5SMTB"}]
    assert L.kinlinks(thomas["hl"], by_hlid) == [
        {"role": "Kind", "name": "Felix Platters", "qid": "Q18624068", "hlid": "HLH34AEMHQ8C"}]
    # the brother is a sibling in the full record and would even be in the
    # register here — he must still not become a link
    by_hlid["HLH2FJFEWG9Y"] = {"n": "Thoman Platter III", "hl": {"id": "HLH2FJFEWG9Y"}}
    assert [k["hlid"] for k in L.kinlinks(felix["hl"], by_hlid)] == ["HLZ3TBQ5SMTB"]


def test_parent_role_follows_gender():
    hl = L.hl_record(FELIX_FULL)
    by_hlid = {"HLMOTHER0001": {"n": "Chrischona Jeckelmännin", "hl": {"id": "HLMOTHER0001"}}}
    assert L.kinlinks(hl, by_hlid)[0]["role"] == "Mutter"
    hl["parents"][1].pop("g")
    assert L.kinlinks(hl, by_hlid)[0]["role"] == "Elternteil"


def test_edges_between_register_persons_only_no_siblings(corpus):
    felix, thomas, by_hlid = corpus
    nodes = {"Felix Platters": "p1", "Thomas Platterns": "p2"}
    node_of = lambda p: nodes.get(p["n"])
    edges, pairs = L.hl_edges([felix, thomas], by_hlid, node_of)
    assert len(edges) == 1, "the pair is seen from both sides but gets one edge"
    e = edges[0]
    assert (e["a"], e["b"], e["type"]) == ("p2", "p1", "parent"), "a is the parent"
    assert e["src"] == "hl" and e["conf"] == 1.0 and e["b_dead"] is True
    assert e["dir"] == "hl" and e["trigger"] == "humanlineage"
    assert pairs == {frozenset({"p1", "p2"})}
    # a person who is no tree node yields nothing
    assert L.hl_edges([felix, thomas], by_hlid, lambda p: None) == ([], set())


def test_couple_edge(corpus):
    felix, thomas, by_hlid = corpus
    helena = {"n": "Helena Bischoffin", "y": [1640, 1660], "c": 1,
              "hl": {"id": "HLSPOUSE0001", "parents": [], "children": [],
                     "spouses": [{"n": "Felix Platter", "qid": "Q18624068", "id": "HLH34AEMHQ8C"}]}}
    by_hlid["HLSPOUSE0001"] = helena
    nodes = {"Felix Platters": "p1", "Helena Bischoffin": "p3"}
    edges, _ = L.hl_edges([felix, helena], by_hlid, lambda p: nodes.get(p["n"]))
    assert [(e["a"], e["b"], e["type"]) for e in edges] == [("p1", "p3", "spouse")]


def test_web_payload_keeps_what_the_card_shows(corpus):
    felix, _, by_hlid = corpus
    felix["hl"]["kinlinks"] = L.kinlinks(felix["hl"], by_hlid)
    c = W.compact_hl(felix["hl"])
    assert c == {"id": "HLH34AEMHQ8C", "u": "https://humanlineage.org/person/HLH34AEMHQ8C",
                 "b": 1605, "d": 1671,
                 "p": ["Thomas Platter der Jüngere", "Chrischona Jeckelmann"],
                 "ch": [], "sp": ["Helena Bischoff"], "snap": SNAP,
                 "k": [{"role": "Vater", "name": "Thomas Platterns"}]}
    merged = {"id": "person:1", "name": "Felix Platter", "birth_year": 1605,
              "death_year": 1671, "corpora": ["hgb", "hls"], "status": "merged",
              "occupations": [], "places": {}, "publications": [], "dossiers": [],
              "authority": {"wikidata": ["Q18624068"]}, "bio": "", "sources": []}
    assert W.compact(merged, {"Q18624068": felix["hl"]})["hl"]["id"] == "HLH34AEMHQ8C"
    assert "hl" not in W.compact(merged, {})


def test_modal_renders_profile_kin_xref_and_licence_line():
    html = (REPO / "index.html").read_text(encoding="utf-8")
    assert "section('Human Lineage'" in html
    assert "Quelle: Human Lineage, CC BY-SA 4.0" in html
    assert "h.kinlinks" in html and 'class="kin-xref"' in html
    assert "🔗 HL" in html
    assert "h.snapshot" in html, "the snapshot date belongs next to every stored link"
    assert "Human Lineage (CC BY-SA 4.0)" in (REPO / "identitaeten.html").read_text(encoding="utf-8")


# ── the tracked data ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def persons():
    return json.load(open(REPO / "persons_resolved.json", encoding="utf-8"))


@pytest.fixture(scope="module")
def graph():
    return json.load(open(REPO / "families_graph.json", encoding="utf-8"))


def test_tracked_hl_edges_join_register_persons_only(persons, graph):
    hl_edges = [e for e in graph["edges"] if e.get("src") == "hl"]
    assert hl_edges, "link_humanlineage.py has not been run"
    node = {n["id"]: n for n in graph["nodes"]}
    joined = {(p["n"], p["y"][0], p["y"][1]) for p in persons if p.get("hl") and p.get("y")}
    for e in hl_edges:
        assert e["type"] in ("parent", "spouse"), "no sibling edges from the dump"
        assert e["conf"] == 1.0 and e["b_dead"] is True and e["dir"] == "hl"
        for end in (e["a"], e["b"]):
            n = node[end]
            assert (n["name"], n["y"][0], n["y"][1]) in joined, \
                f"{end} is not a Human-Lineage-joined register person"
            assert n.get("cid") is not None, "a node the stage made must sit in a family unit"
    # the units the stage founded hold only its own nodes, sized from them
    for c in graph["components"]:
        if c.get("src") == "hl":
            members = [n for n in graph["nodes"] if n.get("cid") == c["cid"]]
            assert len(members) == c["size"] >= 2
            assert all(n.get("src") == "hl" for n in members)


def test_tracked_join_is_by_identifier_and_dated(persons):
    cache = json.load(open(REPO / "humanlineage_cache.json", encoding="utf-8"))
    linked = [p for p in persons if p.get("hl")]
    assert len(linked) > 200
    for p in linked:
        hl = p["hl"]
        assert (p.get("wd") or {}).get("qid") or (p.get("hls") or {}).get("id"), \
            "only QID and HLS joins"
        assert hl["snapshot"] == cache["snapshot"]
        assert hl["url"] == f"https://humanlineage.org/person/{hl['id']}"
        for k in hl.get("kinlinks", []):
            assert k["hlid"] != hl["id"]
    felix = next(p for p in linked if (p.get("wd") or {}).get("qid") == "Q18624068")
    assert felix["hl"]["id"] == "HLH34AEMHQ8C"
    assert any(k["role"] == "Vater" and k["qid"] == "Q116577" for k in felix["hl"]["kinlinks"])
