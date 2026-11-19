"""
dedupe_spelling.py applies pairs of persons that BLI or the street-level index
hold as one. The pairs come with evidence, but the merged *group* must still
obey the rules of the index — one lifespan, the deceased constraint, distinct
confirmed identities — and a candidates file written for another state of the
index must be refused rather than applied to the wrong persons.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import dedupe_spelling as DS   # noqa: E402


def person(n, y, c=1, dead=None, **kw):
    return {"n": n, "v": [n], "c": c, "d": 1, "y": y, "dead_year": dead,
            "dos": [["D1", n]], **kw}


def row(src="bli", n=1):
    return {"_src": set(src.split("+")), "n_bli_actors": str(n)}


def test_pairs_form_one_cluster_within_a_lifespan():
    P = [person("Emanuel Schönauwer", [1597, 1640], c=3),
         person("Emanuel Schönawer", [1607, 1650], c=2),
         person("Emanuel Schönauer", [1641, 1661])]
    sets, refused = DS.cluster(P, [(0, 1, row()), (1, 2, row())])
    assert sorted(sets[0]) == [0, 1, 2] and not refused


def test_a_chain_may_not_outgrow_one_lifespan():
    # each pair fits 80 years, the chain 1500–1625 does not
    P = [person("Hans Gut", [1500, 1560]), person("Hans Gutt", [1550, 1575]),
         person("Hanns Gut", [1570, 1625])]
    sets, refused = DS.cluster(P, [(0, 1, row()), (1, 2, row())])
    assert [sorted(s) for s in sets] == [[0, 1]]
    assert refused["more than one lifespan"] == 1


def test_stronger_evidence_is_applied_first():
    # the same chain, but the second pair is backed by both sources: it wins
    P = [person("Hans Gut", [1500, 1560]), person("Hans Gutt", [1550, 1575]),
         person("Hanns Gut", [1570, 1625])]
    sets, _ = DS.cluster(P, [(0, 1, row("bli")), (1, 2, row("bli+street"))])
    assert [sorted(s) for s in sets] == [[1, 2]]


def test_nobody_joins_a_group_long_after_its_death():
    P = [person("Peter Roth", [1500, 1520], dead=1520),
         person("Peter Rot", [1545, 1550])]
    sets, refused = DS.cluster(P, [(0, 1, row())])
    assert not sets and refused["first mentioned long after a death"] == 1
    # a post-mortem mention within the grace period is the same man
    P[1]["y"] = [1530, 1533]
    sets, _ = DS.cluster(P, [(0, 1, row())])
    assert [sorted(s) for s in sets] == [[0, 1]]


def test_different_confirmed_identities_never_merge():
    P = [person("Felix Platter", [1571, 1614], hls={"id": "014592"}),
         person("Felix Plater", [1580, 1606], hls={"id": "025277"}),
         person("Felix Plattner", [1574, 1601])]
    sets, refused = DS.cluster(P, [(0, 1, row()), (0, 2, row())])
    assert [sorted(s) for s in sets] == [[0, 2]]
    assert refused["different HLS/Wikidata identities"] == 1


@pytest.fixture
def files(tmp_path):
    P = [person("Marx Harder", [1561, 1573], c=5), person("Marx Harders", [1573, 1585]),
         person("Anna Roth", [1500, 1500])]
    pj = tmp_path / "persons.json"
    pj.write_text(json.dumps(P), encoding="utf-8")
    cand = tmp_path / "cand.csv"

    def write(rows):
        with open(cand, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["a_idx", "a_key", "b_idx", "b_key", "sources", "n_bli_actors",
                        "bli_actors", "street_persons", "where"])
            w.writerows(rows)
    return P, pj, cand, write, tmp_path


def test_apply_merges_and_keeps_every_mention(files):
    P, pj, cand, write, tmp = files
    write([[0, "Marx Harder#1561-1573", 1, "Marx Harders#1573-1585", "bli", 1, "actor_1", "", "D1"]])
    DS.main(["--persons", str(pj), "--candidates", str(cand),
             "--csv", str(tmp / "clusters.csv"), "--apply"])
    out = json.loads(pj.read_text(encoding="utf-8"))
    assert len(out) == 2
    m = next(p for p in out if p["n"] == "Marx Harder")
    assert m["c"] == 6 and m["y"] == [1561, 1585]
    assert set(m["v"]) == {"Marx Harder", "Marx Harders"}
    assert sum(p["c"] for p in out) == sum(p["c"] for p in P)


def test_dry_run_leaves_the_index_alone(files):
    P, pj, cand, write, tmp = files
    write([[0, "Marx Harder#1561-1573", 1, "Marx Harders#1573-1585", "bli", 1, "actor_1", "", "D1"]])
    before = pj.read_bytes()
    DS.main(["--persons", str(pj), "--candidates", str(cand), "--csv", str(tmp / "c.csv")])
    assert pj.read_bytes() == before


def test_stale_candidates_are_refused(files):
    P, pj, cand, write, tmp = files
    # position 1 no longer holds the person the pair was computed for
    write([[0, "Marx Harder#1561-1573", 1, "Marx Harders#1570-1590", "bli", 1, "actor_1", "", "D1"]])
    before = pj.read_bytes()
    with pytest.raises(SystemExit, match="no longer fit"):
        DS.main(["--persons", str(pj), "--candidates", str(cand),
                 "--csv", str(tmp / "c.csv"), "--apply"])
    assert pj.read_bytes() == before


def test_sources_can_be_restricted(files):
    P, pj, cand, write, tmp = files
    write([[0, "Marx Harder#1561-1573", 1, "Marx Harders#1573-1585", "street", 0, "", "HGB_1_001#1", "HGB_1_001"]])
    sets, _ = DS.main(["--persons", str(pj), "--candidates", str(cand),
                       "--csv", str(tmp / "c.csv"), "--sources", "bli"])
    assert sets == []
