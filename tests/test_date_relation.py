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

from link_hls import date_relation, life_envelope, fits_life     # noqa: E402
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
    (1470, 1520, 1482, None),            # called deceased 39 years before the death
    (1470, 1525, 1518, "overlap"),       # called deceased shortly before it: tolerated
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
    # the life is 1448–1521; an entry is "inside" when lifedates.fits says so
    inside = [entry("Hans Müller", [1470, 1500]), entry("Hanns Müller", [1505, 1530]),
              entry("Hans Müller", [1525, 1560], dead_year=1525, ly=0)]   # post-mortem references
    before_birth = entry("Hans Müller", [1417, 1500])
    late_living = entry("Hans Müller", [1560, 1604])            # never called deceased
    child = entry("Hans Müller", [1455, 1458], a=[1455, 1458])   # a party at seven
    clusters = DP.cluster_group(inside + [before_birth, late_living, child])
    spans = sorted((min(p["y"][0] for p in c), max(p["y"][1] for p in c)) for c in clusters)
    # the three inside are one person; the two around the birth are left to
    # the lifespan rule (one older namesake), the late one stays alone
    assert spans == [(1417, 1500), (1470, 1560), (1560, 1604)]
    merged = DP.merge_cluster(inside + [entry("Hans Müller", [1490, 1510], a=[1492, 1509])],
                              "Johann Müller")
    assert merged["a"] == [1492, 1509]


# ── the guard every later dedupe pass asks ───────────────────────────────────

def test_life_envelope_and_fit():
    env = life_envelope({"wd": {"b": 1680, "d": 1762}})
    assert tuple(env) == (1680, 1680, 1762, 1762)
    assert fits_life(env, 1700, 1760, None, (None, 1760))
    assert not fits_life(env, 1624, 1699)            # first mention 56 years before birth
    assert not fits_life(env, 1679, 1760)            # … or one year before it
    # `extra` = (years as a party, last year named as living), lifedates.extra
    assert not fits_life(env, 1700, 1830, 1765)      # beyond the post-mortem window
    assert not fits_life(env, 1700, 1760, 1740)      # called deceased 22 years too early
    assert fits_life(env, 1700, 1780, 1765, (None, 1760))    # named after the death, as deceased
    assert fits_life(env, 1700, 1775, None, (None, 1775))    # … or for a while without the word
    assert not fits_life(env, 1700, 1780, None, (None, 1780))    # but not for a generation
    # the years as a party to a transaction
    assert fits_life(env, 1685, 1760, None, ([1700, 1760], 1760))
    assert not fits_life(env, 1685, 1760, None, ([1690, 1760], 1760))     # a seller at ten
    assert not fits_life(env, 1700, 1770, 1770, ([1700, 1768], 1768))     # a buyer six years dead
    assert life_envelope({"n": "nobody"}) is None
    assert fits_life(None, 1400, 1700)               # no known life: nothing to check
    # the bounds apply_hls_links.py keeps on the link take precedence
    assert tuple(life_envelope({"hls": {"id": "1", "b": 1505, "bk": "first_mention",
                                        "life": [1435, 1491, 1551, 1551]}})) \
        == (1435, 1491, 1551, 1551)


def test_no_dedupe_pass_adds_namesakes_from_outside_a_known_life():
    import dedupe_spelling as DS
    faesch = {"n": "Hanns Jacob Faesch", "v": [], "c": 5, "y": [1690, 1699], "dead_year": None,
              "dos": [["D1", "x"]], "hls": {"id": "1"}, "wd": {"qid": "Q1", "b": 1680, "d": 1762}}
    older = {"n": "Hans Jacob Fäsch", "v": [], "c": 9, "y": [1624, 1675], "dead_year": 1675,
             "dos": [["D1", "y"]]}
    row = {"_src": {"bli"}, "n_bli_actors": "1"}
    sets, refused = DS.cluster([faesch, older], [(0, 1, row)])
    assert not sets
    assert refused["outside the known life of an HLS-linked person"] == 1
    # a namesake inside the life does join
    older["y"], older["dead_year"] = [1695, 1720], None
    sets, _ = DS.cluster([faesch, older], [(0, 1, row)])
    assert [sorted(s) for s in sets] == [[0, 1]]


def test_merged_person_counts_dossiers_not_name_pairs():
    a = entry("Hans Müller", [1470, 1500], c=3)
    b = entry("Hanns Müller", [1505, 1520])
    b["dos"] = [["D1", "Hanns Müller"], ["D2", "Hanns Müller"]]
    m = DP.merge_cluster([a, b], "Johann Müller")
    assert len(m["dos"]) == 3 and m["d"] == 2 and m["c"] == 4


def test_life_dates_are_those_of_the_article_the_link_was_judged_against():
    from link_hls import life_dates
    only_hls = {"n": "Hans Muster", "hls": {"id": "1", "b": 1500, "d": 1560}}
    assert life_dates(only_hls) == (1500, 1560)
    assert life_envelope(only_hls) == life_envelope({"wd": {"b": 1500, "d": 1560}})
    # one source for both dates: Wikidata's century-rounded birth must not be
    # paired with the article's death (Peter Rot: "born 1500", died 1487)
    mixed = {"hls": {"id": "1", "d": 1487}, "wd": {"b": 1500, "d": 1487}}
    assert life_dates(mixed) == (None, 1487)
    # an older index without dates on the link falls back to Wikidata
    assert life_dates({"hls": {"id": "1"}, "wd": {"b": 1492}}) == (1492, None)
    assert life_envelope({"hls": {"id": "1"}}) is None
    assert life_envelope({"n": "x"}) is None


def test_an_article_of_one_given_name_does_not_take_double_names():
    from link_hls import article_given_ratio, given_key
    art = given_key("Johannes")
    assert article_given_ratio(given_key("Hans"), art) == 1.0
    assert article_given_ratio(given_key("Hans Georg"), art) == 0.0
    assert article_given_ratio(given_key("Hans Jakob"), art) == 0.0
    # the register may shorten, and a matching double name still fits
    art2 = given_key("Johann Rudolf")
    assert article_given_ratio(given_key("Hans"), art2) == 1.0
    assert article_given_ratio(given_key("Hans Rudolff"), art2) == 1.0
    assert article_given_ratio(given_key("Hans Jakob"), art2) < 0.74


def test_bio_years_puts_the_tables_dates_right():
    from link_hls import bio_years
    row = lambda i, b, d: {"id": i, "bio.birth_date": b, "bio.death_date": d}
    # the export's reverse order (Adam Petri)
    assert bio_years(row("1", "1527-11-15", "1454")) == (1454, 1527)
    assert bio_years(row("1", "1454", "1527-11-15")) == (1454, 1527)
    # Wikidata's century-rounded birth is no birth year (Peter Rot)
    assert bio_years(row("2", "1500-01-01", "1487-01-01")) == (None, 1487)
    # two alternatives for the birth are not a life: Wikidata's whole life wins
    alt = {"3": (1557, 1595), "4": (None, 1482), "5": (1497, 1543)}
    assert bio_years(row("3", "1557", "1560"), alt) == (1557, 1595)
    assert bio_years(row("5", "1547", "1548"), alt) == (1497, 1543)     # Holbein d. J.
    # … but only a whole life: first and last mention stay what they are
    assert bio_years(row("4", "1472", "1482"), alt) == (1472, 1482)
    assert bio_years(row("6", "1438", "1449"), alt) == (1438, 1449)
    assert bio_years(row("7", "", "1530-06-03")) == (None, 1530)
