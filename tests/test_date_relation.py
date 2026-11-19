"""
link_hls.date_relation decides whether an HGB person — a cluster of mentions —
can be the person of a biography. It used to accept any cluster that touched
the life span, so a "Hans Müller 1417–1500" was linked to a man born in 1448;
dedupe_persons.py then merged everything carrying the link into persons of up
to 187 years. The whole span has to fit the life.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from link_hls import date_relation     # noqa: E402
import dedupe_persons as DP            # noqa: E402

B, D = 1448, 1521


@pytest.mark.parametrize("m0,m1,dead,expected", [
    (1470, 1520, None, "overlap"),       # inside the life
    (1444, 1500, None, "overlap"),       # a few years before a known birth: tolerated
    (1417, 1500, None, None),            # begins 31 years before birth: an older namesake
    (1500, 1535, None, "overlap"),       # as living until 14 years after death: tolerated
    (1500, 1560, None, None),            # as living 39 years after death: a younger namesake
    (1500, 1560, 1522, "overlap"),       # same span, but called deceased: post-mortem references
    (1500, 1590, 1522, None),            # beyond the post-mortem window
    (1530, 1534, None, "postmortem"),    # first mention shortly after death
    (1540, 1560, 1540, "postmortem"),    # first mention later, as deceased
    (1540, 1560, None, None),            # first mention later, as living
])
def test_the_whole_mention_span_has_to_fit_the_life(m0, m1, dead, expected):
    assert date_relation(m0, m1, dead, B, D)[0] == expected


def test_postmortem_gap_is_reported():
    assert date_relation(1530, 1534, None, B, D) == ("postmortem", 9)


def test_unknown_death_is_estimated_from_birth():
    assert date_relation(1500, 1570, None, 1492, None)[0] == "overlap"
    assert date_relation(1500, 1590, None, 1492, None)[0] is None      # alive at 98
    assert date_relation(1470, 1520, None, 1492, None)[0] is None      # 22 years before birth


def test_unknown_birth_is_estimated_from_death():
    assert date_relation(1480, 1550, None, None, 1557)[0] == "overlap"
    assert date_relation(1460, 1550, None, None, 1557)[0] is None      # 97 years before death


def test_undated_or_dateless():
    assert date_relation(None, 1500, None, B, D) == (None, None)
    assert date_relation(1500, 1510, None, None, None) == (None, None)


# ── dedupe_persons: the envelope takes what lies inside it ───────────────────

def entry(n, y, c=1, **kw):
    hls = {"id": "025221", "t": "Johann Müller"}
    wd = {"qid": "Q1", "b": B, "d": D}
    return {"n": n, "v": [n], "c": c, "y": y, "dead_year": None, "dos": [["D1", n]],
            "hls": hls, "wd": wd, **kw}


def test_envelope_merges_entries_inside_it_only():
    inside = [entry("Hans Müller", [1470, 1500]), entry("Hanns Müller", [1505, 1560])]
    reaching_out = entry("Hans Müller", [1417, 1500])          # starts before birth − 10
    late = entry("Hans Müller", [1560, 1604])                  # ends after death + 60
    clusters = DP.cluster_group(inside + [reaching_out, late])
    spans = sorted((min(p["y"][0] for p in c), max(p["y"][1] for p in c)) for c in clusters)
    assert (1470, 1560) in spans
    assert all(hi - lo <= 90 for lo, hi in spans)
    assert len(clusters) == 3
