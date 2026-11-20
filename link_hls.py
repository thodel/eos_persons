#!/usr/bin/env python3
"""
link_hls.py — propose links between HGB person entries and HLS biographies.

Matches each resolved HGB person (persons_resolved.json) against the
biographical articles in the HLS export (hls_articles.csv, category == "bio"),
keeping only candidates where:

  • the article is a biography (category "bio"), and
  • the HGB mention period overlaps the person's HLS life span,
    EXCEPT that mentions after the death date are allowed as post-mortem
    references (common in a property register), within a grace window.

Output is a CSV of candidate links for human review — not automatic merges.
A given HGB person may yield several candidates; inspect the scores.

Run locally:
    python3 link_hls.py \
        --persons persons_resolved.json \
        --hls /Users/TH_1/Documents/HLS/hls_articles.csv \
        --out link_candidates_hls.csv
"""
import os
import re
import csv
import json
import argparse
import unicodedata
import collections
from difflib import SequenceMatcher

import lifedates

csv.field_size_limit(10_000_000)

# The HLS metadata export is private; when it is absent the linkers fall back
# to the public table built from Wikidata by build_hls_table.py (same column
# layout, see there for what it lacks). The export is looked for in
# $HLS_ARTICLES, on the maintainer's machine, and in private_inputs/ next to
# the scripts (gitignored — the export must never be committed).
_HERE = os.path.dirname(os.path.abspath(__file__))
HLS_PRIVATE = "/Users/TH_1/Documents/HLS/hls_articles.csv"
HLS_PUBLIC = os.path.join(_HERE, "hls_bios_wikidata.csv")


def private_hls():
    """Path of the private HLS export (with article texts and family articles),
    or None where only the public table is available."""
    for p in (os.environ.get("HLS_ARTICLES"), HLS_PRIVATE,
              os.path.join(_HERE, "private_inputs", "hls_articles.csv")):
        if p and os.path.exists(p):
            return p
    return None


def default_hls():
    return private_hls() or HLS_PUBLIC


# Particles that precede a surname; stripped before comparison.
PARTICLES = {"von", "vom", "van", "zem", "zum", "zur", "zer", "ze", "im", "in",
             "ab", "de", "der", "den", "am", "an", "zu", "of", "of."}

# Common given-name variants → canonical form (HGB OCR/early-modern spellings).
GIVEN_CANON = {
    "hs": "hans", "hans": "hans", "hanns": "hans", "hannß": "hans",
    "hansen": "hans", "hennslin": "hans", "johannes": "hans", "johann": "hans",
    "hanies": "hans", "joh": "hans", "johans": "hans",
    "heinr": "heinrich", "heinrich": "heinrich", "heinrichen": "heinrich",
    "heini": "heinrich", "heintz": "heinrich", "heinz": "heinrich",
    "cunrat": "konrad", "conrat": "konrad", "conrad": "konrad", "cunratz": "konrad",
    "konrad": "konrad", "conr": "konrad", "kunz": "konrad",
    "jacob": "jakob", "jakob": "jakob", "jacobs": "jakob", "jac": "jakob",
    "grg": "georg", "georg": "georg", "jergen": "georg", "jerg": "georg", "joerg": "georg",
    "hentzman": "heinzmann", "heinzman": "heinzmann",
    "ulrich": "ulrich", "uli": "ulrich", "ueli": "ulrich",
    "ruedi": "rudolf", "rudolf": "rudolf", "rudolff": "rudolf", "rudi": "rudolf",
    "rudolph": "rudolf", "ruod": "rudolf", "ruodolf": "rudolf",
    "peter": "peter", "petter": "peter", "petman": "peter",
    "claus": "klaus", "klaus": "klaus", "niclaus": "klaus", "nikolaus": "klaus",
    "niklaus": "klaus", "clewi": "klaus", "clausen": "klaus",
    "bartholome": "bartholomäus", "barthlome": "bartholomäus",
    "thoman": "thomas", "thomas": "thomas",
    "wernher": "werner", "werner": "werner",
    "símon": "simon", "symon": "simon", "simon": "simon",
    "anthoni": "anton", "anthonin": "anton", "anton": "anton", "antoni": "anton",
    "hieronymus": "hieronymus", "jeronimus": "hieronymus",
}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_token(t):
    return strip_accents(re.sub(r"[^\wäöü]", "", t.lower()))


def canon_given(t):
    t = norm_token(t)
    return GIVEN_CANON.get(t, t)


def given_key(s):
    """Canonicalise a dedicated given-name field — every token, not just the first.

    "Hans Ulrich" -> "johann ulrich". Compare two of these with `given_ratio`,
    never with bare `ratio`: see that function for why.
    """
    toks = [t for t in re.sub(r"[.,]", " ", s or "").split() if len(t) > 1]
    return " ".join(canon_given(t) for t in toks
                    if norm_token(t) and norm_token(t) not in PARTICLES)


GIVEN_MODE = "prefix"   # "first" restores the pre-2026-07 first-token-only rule


def given_ratio(a, b):
    """Compare given names on their common prefix.

    Historically these were compared on the first token alone, which makes
    "Hans Ulrich" and "Johann Jakob" identical (both canonicalise to "johann")
    — yet in early-modern Swiss naming the *second* given name is the
    distinguishing one (Hans Heinrich / Hans Ulrich / Hans Jakob are three
    different men). Comparing the full string instead would over-penalise a
    source that merely omits a middle name, so we compare only as many tokens
    as the shorter side has: a *missing* middle name costs nothing, a
    *conflicting* one is caught.
    """
    ta, tb = (a or "").split(), (b or "").split()
    if not ta or not tb:
        return 0.0
    k = 1 if GIVEN_MODE == "first" else min(len(ta), len(tb))
    return ratio(" ".join(ta[:k]), " ".join(tb[:k]))


def article_given_ratio(register, article):
    """`given_ratio` of a register person against an HLS article — 0 where the
    register knows *more* given names than the article.

    The prefix rule forgives a missing middle name on either side. That is
    right for the register, whose clerks shorten ("Hans Faesch" for Johann
    Rudolf Faesch), but not for the lexicon: an article headed *Johannes
    Müller* is about a man of one given name, and Hans Georg, Hans Jakob and
    Hans Rudolf Müller are other people. Before this rule one such article
    collected five different double names.
    """
    if len((register or "").split()) > len((article or "").split()):
        return 0.0
    return given_ratio(register, article)


def split_name(name):
    """Return (given, surname) from a full name string, particles stripped.

    `given` carries every given token (see `given_key`); compare it with
    `given_ratio`.
    """
    toks = [t for t in re.sub(r"[.,]", " ", name).split() if len(t) > 1]
    toks = [t for t in toks if norm_token(t)]            # drop punctuation-only
    if len(toks) < 2:
        return (norm_token(toks[0]) if toks else "", "")
    # surname = last token, unless it's a particle (then second-to-last)
    rest = toks[1:]
    # drop a leading particle in the remainder ("von Hiltallingen")
    while rest and norm_token(rest[0]) in PARTICLES:
        rest = rest[1:]
    surname = rest[-1] if rest else toks[-1]
    given = toks[:1] + rest[:-1] if rest else toks[:1]
    return (given_key(" ".join(given)), norm_token(surname))


# A run of 3-4 digits that is not part of a longer number and is not cut short
# by an uncertainty placeholder. The trailing (?![\dXx]) is the point: GND
# writes an imprecise year by replacing its last digits with X, so a bare
# \d{3,4} search reads '[149X]' ("some year in the 1490s") as the year 149.
_YEAR_RE = re.compile(r"(?<!\d)(\d{3,4})(?![\dXx])")


def year_of(s):
    """First precise calendar year in a date string, else None.

    Shapes present in the HLS export and the GND enrichment:

        1724, 1792-06-16, 1695-10   -> 1724, 1792, 1695
        [1290/1300]                 -> 1290   (range: earliest bound)
        [149X], [16XX], [1XXX]      -> None   (decade/century only)
        [XXXX]                      -> None

    An imprecise date yields None rather than a guess: a wrong precise year
    propagates into life spans, year-range filters and the published corpus
    statistics, where it is indistinguishable from a real one.
    """
    if not s:
        return None
    m = _YEAR_RE.search(str(s))
    return int(m.group(1)) if m else None


def ratio(a, b):
    if a == b:
        return 1.0
    if not a or not b or a[0] != b[0]:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def hls_url(article_id, version=None):
    # online HLS pattern includes the article version date, e.g.
    # https://hls-dhs-dss.ch/de/articles/019314/2009-08-24/
    if version:
        return f"https://hls-dhs-dss.ch/de/articles/{article_id}/{version}/"
    return f"https://hls-dhs-dss.ch/de/articles/{article_id}/"


# ── Life dates of a biography ────────────────────────────────────────────────
#
# The two date columns of the HLS tables are not always a birth and a death:
#
#   • 1,009 rows of the export carry them in reverse order (Adam Petri:
#     "born 1527-11-15, died 1454") — such a biography never fitted anybody;
#   • where the birth is uncertain the export gives both alternatives and no
#     death (Hans Jakob Plepp "1557/60" → 1557–1560, Ludwig Senfl 1489–1491),
#     and for Hans Holbein the Younger it has 1547–1548;
#   • Wikidata rounds an unknown birth to the century ("1500-01-01", died 1487).
#
# bio_years() puts this right as far as the tables allow.

MIN_LIFE = 15            # fewer years between the two dates are not a life
WIKIDATA_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "hls_bios_wikidata.csv")


def load_alt_dates(path=WIKIDATA_TABLE):
    """{HLS id: (birth, death)} from the Wikidata table — a second opinion for
    the export's implausible pairs."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["id"]] = _ordered(r.get("bio.birth_date"), r.get("bio.death_date"))
    return out


def _ordered(birth, death):
    b, d = year_of(birth), year_of(death)
    if b and d and b > d:
        if re.search(r"00-01-01$", birth or ""):
            b = None                 # a century, not a year: birth unknown
        else:
            b, d = d, b              # the export's reverse order
    return b, d


def bio_years(row, alt=None):
    """(birth, death) of one row of an HLS table, see above. `alt` is
    load_alt_dates(): where the row's own dates lie less than MIN_LIFE years
    apart and Wikidata knows a whole life, that is taken."""
    b, d = _ordered(row.get("bio.birth_date"), row.get("bio.death_date"))
    if b and d and d - b < MIN_LIFE and alt:
        ab, ad = alt.get(row.get("id"), (None, None))
        if ab and ad and ad - ab >= MIN_LIFE:
            b, d = ab, ad
    return b, d


# ── Does the biography belong to Basel? ──────────────────────────────────────
#
# The HLS covers all of Switzerland, the register one town. A Hans Müller of
# Zug and a Hans Meyer of Fribourg fit Basel namesakes by name and dates just
# as well as a Basler does — on the first run with the article texts, 224 of
# the 458 linked articles did not mention Basel at all. So an article is only
# a candidate when its text ties the person to the town:
#
#   strong  born or died in Basel, citizen "von Basel", an office, a chair, a
#           house or a move there — or Basel named three times and more
#   weak    Basel is mentioned, but only in passing (studies, a mediation
#           between Basel and Solothurn, the Council of Basel …)
#   none    no mention
#
# The class is read from `content_text` of the private export. Without the
# export it comes from hls_basel.csv, the classes of the last run with it
# (written by this script — ids and classes only, no article text).

BASEL_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hls_basel.csv")
_BASEL = re.compile(r"\b(?:Klein|Gross)?[Bb]as(?:el|ler|lerin|lern|els)\b|\bBâle\b")
_NOT_THE_TOWN = re.compile(r"^(?:Bf|Bischof\w*|Bischöf\w*|Fürstbf|Fürstbischof\w*|"
                           r"Fürstbischöf\w*|Bistum\w*|Diözese|Hochstift\w*|Offizial\w*)\.?$")
_BASEL_ORIGIN = re.compile(r"(\S+) (?:von|zu) Basel\b")
_BASEL_STRONG = [
    # vital line: "12.3.1500 Basel, 4.5.1560 Basel" (not "1522 in Basel")
    re.compile(r"\b\d{4}(?:/\d{2,4})? (?:\(\?\) )?(?:wohl |vermutlich |wahrscheinlich )?"
               r"(?:Klein)?[Bb]asel\b"),
    # an institution of the town the person belongs to
    re.compile(r"\bBasler (?:Bürgerrecht|Rat(?:s|es)?\b|Kleinrat|Grossrat|Zunft\b|"
               r"Domkapitel|Domherr|Münster|Pädagogium|Universität|Dienstadel|"
               r"Achtburger|Geschlecht|Familie)"),
    # living or working there
    re.compile(r"\b(?:Bürger\w*|Burger\w*|Burgrecht|Hintersass\w*|Professor|Prof\.|Pfarrer|"
               r"Domherr|Kaplan|Chorherr|Ratsherr|Rat|Zunft\w*|Zünftig|niedergelassen|"
               r"Niederlassung|übersiedelte|zog|kam|Rückkehr|zurück|wohnhaft|wohnte|lebte|"
               r"wirkte|starb|liess sich|tätig|Tätigkeit|Schaffner|Werkstatt|Offizin|"
               r"Druckerei|Haus|Hof|Wohnsitz)\b[^.;]{0,40}?\b(?:in|nach|zu) Basel\b"),
]


def _basel_origin(text):
    """Citizenship or origin — "von Basel", "Bürger von Basel" — but not the
    bishop: "Bf. von Basel" names the prince-bishopric, not the town."""
    return any(not _NOT_THE_TOWN.match(m.group(1)) for m in _BASEL_ORIGIN.finditer(text))


def basel_relation(text):
    """'strong' | 'weak' | 'none' — how an HLS article ties its person to Basel
    ('' for an empty text: unknown)."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    n = len(_BASEL.findall(text))
    if not n:
        return "none"
    if n >= 3 or _basel_origin(text) or any(rx.search(text) for rx in _BASEL_STRONG):
        return "strong"
    return "weak"


def load_basel_table(path=BASEL_TABLE):
    """{HLS id: (basel class, kind of birth date, kind of death date)} — what
    the last run with the article texts read from them."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["hls_id"]: (r["basel"], r.get("b_kind") or None, r.get("d_kind") or None)
                for r in csv.DictReader(f)}


WIKIDATA_DATES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "hls_wikidata_dates.csv")


def load_wikidata_years(path=WIKIDATA_DATES):
    """{HLS id: ([birth years], [death years])} — Wikidata's dates given to the
    year or better (fetch_wikidata_dates.py), the second opinion on a life."""
    out = collections.defaultdict(lambda: ([], []))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if int(r["precision"]) >= 9:
                    out[r["hls_id"]][0 if r["prop"] == "b" else 1].append(int(r["year"]))
    return out


# ── Load HLS biographies in the HGB era ──────────────────────────────────────

def load_hls(path, era_lo=1380, era_hi=1720, classes=None):
    """Return list of bio dicts with parsed years, blocked by surname initial.

    `classes`, if given, collects {id: (basel_relation, kind of birth date,
    kind of death date)} for every biography that comes with a text — also
    those outside the era, whose dates another table may give differently.
    Each bio carries its `life` (lifedates.bounds) from the article's dates,
    their qualifiers and Wikidata's year-precise dates."""
    bios = []
    known = load_basel_table()
    alt = load_alt_dates()
    wd_years = load_wikidata_years()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("category") != "bio":
                continue
            text = row.get("content_text")
            basel = basel_relation(text)
            b, d = bio_years(row, alt)
            if basel:
                kb, kd = lifedates.date_kinds(text, b, d)
                if classes is not None:
                    classes[row.get("id")] = (basel, kb or "", kd or "")
            else:
                basel, kb, kd = known.get(row.get("id"), ("", None, None))
            fam = (row.get("bio.family_name") or "").strip()
            first = (row.get("bio.first_name") or "").strip()
            if not fam and not first:
                continue
            # estimate the missing bound so the era filter still works
            lo = b if b else (d - 90 if d else None)
            hi = d if d else (b + 90 if b else None)
            if not (lo and hi):
                continue
            if hi < era_lo or lo > era_hi:
                continue
            surname = norm_token(fam.split()[-1]) if fam else ""
            given = given_key(first)
            wb, wd = wd_years.get(row.get("id"), ((), ()))
            life, how_b, how_d = lifedates.explain(b, kb, d, kd, wb, wd)
            bios.append({
                "id": row.get("id"),
                "version": (row.get("version") or "").strip(),
                "title": row.get("title", "").strip(),
                "first": first, "family": fam,
                "given_n": given, "surname_n": surname,
                "birth": b, "death": d, "birth_kind": kb, "death_kind": kd,
                "wd_birth": wb, "wd_death": wd, "life": life, "life_how": (how_b, how_d),
                "lex": (row.get("lexical_class") or "").strip("[]'\""),
                # from the text where there is one, else from the last run with texts
                "basel": basel,
            })
    return bios


# ── Date plausibility ────────────────────────────────────────────────────────

BEFORE_BIRTH = 5      # mentions this long before a known birth are tolerated
ALIVE_AFTER_DEATH = 15  # … and mentions as living this long after a known death
DEAD_BEFORE_DEATH = 5   # … and a "deceased" this long before a known death
POSTMORTEM = 60         # post-mortem references reach this far


def life_dates(p):
    """(birth, death) of an HLS-linked person: the dates of the HLS article the
    link was judged against (apply_hls_links.py keeps them on the link), else
    those of Wikidata. One source for both — Wikidata rounds an unknown birth
    to the century, and mixing "born 1500" with the article's "died 1487"
    describes nobody."""
    wd, hls = p.get("wd") or {}, p.get("hls") or {}
    if hls.get("b") or hls.get("d"):
        return hls.get("b"), hls.get("d")
    return wd.get("b"), wd.get("d")


def life_envelope(p):
    """The life (lifedates.Life) of an HLS-linked person, else None.

    apply_hls_links.py keeps the bounds on the link — born between the first
    two years, died between the last two; they come from the article's dates
    with their qualifiers and from Wikidata (lifedates.bounds). A link without
    them is read as exact dates.
    """
    life = (p.get("hls") or {}).get("life")
    if life:
        return lifedates.Life(*life)
    b, d = life_dates(p)
    if not (b or d):
        return None
    return lifedates.bounds(b, None, d, None)


def fits_life(env, y0, y1, dead_year=None, extra=None):
    """Can mentions y0..y1 — first called deceased in `dead_year`; `extra` =
    (years as a party to a transaction, last year named as living), see
    lifedates.extra — belong to the life `env` (from life_envelope)? True
    where nothing is known.

    Every dedupe pass asks this before it merges into an HLS-linked person:
    without it a later pass adds namesakes from outside the life, and the
    biography ends up on a person first mentioned 56 years before the birth.
    """
    if env is None or y0 is None or y1 is None:
        return True
    return lifedates.fits(env, y0, y1, dead_year, *(extra or (None, None)))


def person_fits(env, p):
    """`fits_life` for a person of the index."""
    y = p.get("y") or [None, None]
    return fits_life(env, y[0], y[1], p.get("dead_year"), lifedates.extra(p))


def date_relation(m0, m1, dead_year, birth, death, grace=60, tol=3,
                  before=BEFORE_BIRTH, alive_after=ALIVE_AFTER_DEATH):
    """Classify the temporal relation between an HGB mention span [m0,m1]
    (with optional HGB dead_year, the first year the person is called
    deceased) and a life span [birth,death].

    Returns (relation, gap) or (None, _) if implausible.
      relation ∈ {"overlap", "postmortem"}.

    The whole mention span has to fit the life, not merely touch it: an HGB
    person is a cluster of mentions, and a cluster that begins before the birth
    or runs on as living after the death holds an older or a younger namesake
    as well. Linking it would hand the biography to all of them — and
    dedupe_persons.py then merges everything that carries the link (Hans Müller
    1417–1604 for a man who lived 1448–1521).

      • first mention not more than `before` years before a known birth
        (`tol` years before one estimated as death − 90);
      • last mention within `grace` years after the death (post-mortem
        references are common in a property register);
      • if the cluster never calls the person deceased, its last mention is at
        most `alive_after` years after a known death (not after birth + 90
        where the death is unknown);
      • the cluster does not call the person deceased more than
        DEAD_BEFORE_DEATH years before a known death.
    """
    if m0 is None or m1 is None:
        return (None, None)
    b = birth
    d = death if death else (birth + 90 if birth else None)
    if b is None and death is not None:
        b = death - 90
    if b is None or d is None:
        return (None, None)

    # mentioned before birth → the cluster holds an older namesake
    if m0 < b - (before if birth is not None else tol):
        return (None, None)
    # mentioned beyond the post-mortem window → it holds a younger one
    if m1 > d + grace:
        return (None, None)
    # never called deceased, yet mentioned long after the death
    if dead_year is None and m1 > (death + alive_after if death else d):
        return (None, None)
    # called deceased well before the known death → an older namesake died
    if death and dead_year and dead_year < death - DEAD_BEFORE_DEATH:
        return (None, None)
    # life span and mention span intersect
    if m0 <= d + tol:
        return ("overlap", 0)
    # mentions begin after death → post-mortem reference (within grace, see above)
    return ("postmortem", m0 - d)


# ── Matching ─────────────────────────────────────────────────────────────────

def person_mentions(persons):
    """Per person the mentions [(year, called deceased, party)] — or None when
    the mention lists of build_data.py do not belong to this index."""
    import build_data                     # pandas: only needed here
    side = build_data.read_rows(persons)
    if side is None:
        return None
    import pandas as pd
    rows = build_data.prepare_rows(pd.read_csv(build_data.INPUT_CSV))
    return [[(rows[i]["_year"], rows[i]["_dead"], rows[i]["_strong"], rows[i]["_past"])
             for _, idx in entries for i in idx if rows[i]["_year"]]
            for entries in side]


def main():
    ap = argparse.ArgumentParser(description="Link HGB persons to HLS biographies.")
    ap.add_argument("--persons", default="persons_resolved.json")
    ap.add_argument("--hls", default=default_hls())
    ap.add_argument("--out", default="link_candidates_hls.csv")
    ap.add_argument("--surname-min", type=float, default=0.82)
    ap.add_argument("--given-min", type=float, default=0.74)
    ap.add_argument("--postmortem-grace", type=int, default=60)
    ap.add_argument("--any-place", action="store_true",
                    help="also keep articles that do not tie their person to Basel "
                         "(see basel_relation); the column hls_basel tells them apart")
    ap.add_argument("--given-mode", choices=("prefix", "first"), default="prefix",
                    help="'first' restores the old first-given-token-only rule, "
                         "for A/B measurement against the current prefix rule")
    args = ap.parse_args()

    global GIVEN_MODE
    GIVEN_MODE = args.given_mode

    print("Loading HLS biographies …")
    classes = {}
    bios = load_hls(args.hls, classes=classes)
    n_era = len(bios)
    by_basel = collections.Counter(b["basel"] or "unknown" for b in bios)
    if classes:
        # the texts are at hand: keep what was read from them for runs without the export
        with open(BASEL_TABLE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["hls_id", "basel", "b_kind", "d_kind"])
            w.writerows((i,) + classes[i] for i in sorted(classes))
        print(f"  wrote {BASEL_TABLE} ({len(classes)} biographies)")
    if not args.any_place:
        bios = [b for b in bios if b["basel"] in ("strong", "")]
    print(f"  Basel relation of the {n_era} bios in the era: {dict(by_basel)}"
          f" → {len(bios)} kept")
    by_initial = collections.defaultdict(list)
    for bio in bios:
        if bio["surname_n"]:
            by_initial[bio["surname_n"][0]].append(bio)
    print(f"  {len(bios)} HLS bios in the HGB era "
          f"({len(by_initial)} surname initials)")

    print("Loading HGB persons …")
    persons = json.load(open(args.persons, encoding="utf-8"))
    print(f"  {len(persons)} resolved persons")

    # On the raw index (build_data.py just wrote it) every person's mentions
    # are at hand: the life is checked mention by mention, a biography is a
    # candidate when part of the mentions fit, and apply_hls_links.py splits
    # the person there. Later (after the dedupe passes) a person has to fit as
    # a whole.
    mentions = person_mentions(persons)
    print("  mention-level life check" if mentions else
          "  no mention lists for this index: persons are checked as a whole")

    rows_out = []
    n_checked = 0
    for pi, p in enumerate(persons):
        names = [p["n"]] + [v for v in p.get("v", []) if v != p["n"]]
        # use the canonical name for splitting; variants only widen given/surname
        given, surname = split_name(p["n"])
        if not surname or not given:
            continue
        y = p.get("y")
        if not y:
            continue
        m0, m1 = y[0], y[1]
        dead = p.get("dead_year")

        n_checked += 1
        if n_checked % 20000 == 0:
            print(f"  …{n_checked} persons, {len(rows_out)} candidates")

        block = by_initial.get(surname[0], [])
        best_for_person = []
        for bio in block:
            sr = ratio(surname, bio["surname_n"])
            if sr < args.surname_min:
                continue
            gr = article_given_ratio(given, bio["given_n"]) if bio["given_n"] else 0.0
            if gr < args.given_min:
                continue
            life = bio["life"]
            if m1 < life.blo or m0 > life.dhi + lifedates.POSTMORTEM:
                continue
            if mentions:
                ms = mentions[pi]
                labels, kinds = lifedates.partition(life, ms)
                fit = [m[0] for m, lab in zip(ms, labels) if lab == "F"]
                if not fit:
                    continue
                n_early, n_late = labels.count("E"), labels.count("L")
            else:
                if not person_fits(life, p):
                    continue
                fit, kinds, n_early, n_late = [m0], {}, 0, 0
            n_fit = len(fit) if mentions else p.get("c", 0)
            share = n_fit / (n_fit + n_early + n_late)
            first = min(fit)
            rel = "overlap" if first <= life.dhi else "postmortem"
            gap = max(0, first - life.dhi)
            score = round(0.6 * sr + 0.4 * gr - (0.0 if rel == "overlap" else 0.05), 3)
            best_for_person.append({
                "hgb_idx": pi,
                "n_fit": n_fit, "n_early": n_early, "n_late": n_late,
                "conflicts": "|".join(f"{k}:{n}" for k, n in sorted(kinds.items())),
                # among several biographies the one that holds more of the
                # mentions comes first (a father and a son of one name)
                "rank_score": round(score - 0.1 * (1 - share), 3),
                "hls_birth_kind": bio["birth_kind"] or "",
                "hls_death_kind": bio["death_kind"] or "",
                "life": "|".join(map(str, life)),
                "hgb_name": p["n"],
                "hgb_year_min": m0, "hgb_year_max": m1,
                "hgb_dead_year": dead if dead else "",
                "hgb_mentions": p.get("c", 0),
                "hls_id": bio["id"], "hls_title": bio["title"],
                "hls_first": bio["first"], "hls_family": bio["family"],
                "hls_birth": bio["birth"] or "", "hls_death": bio["death"] or "",
                "hls_lexical_class": bio["lex"], "hls_basel": bio["basel"],
                "surname_score": round(sr, 3), "given_score": round(gr, 3),
                "date_relation": rel, "date_gap": gap,
                "score": score,
                "hls_version": bio["version"],
                "hls_url": hls_url(bio["id"], bio["version"]),
            })
        # keep all candidates for this person, but flag ambiguity
        best_for_person.sort(key=lambda r: -r["rank_score"])
        for rank, cand in enumerate(best_for_person):
            cand["n_candidates_for_person"] = len(best_for_person)
            cand["rank"] = rank + 1
            rows_out.append(cand)

    rows_out.sort(key=lambda r: (-r["score"], r["hgb_name"]))

    cols = ["score", "date_relation", "date_gap", "surname_score", "given_score",
            "hgb_name", "hgb_year_min", "hgb_year_max", "hgb_dead_year",
            "hgb_mentions", "hls_id", "hls_title", "hls_first", "hls_family",
            "hls_birth", "hls_death", "hls_lexical_class", "hls_basel",
            "n_candidates_for_person", "rank", "hls_version", "hls_url",
            "hgb_idx", "rank_score", "n_fit", "n_early", "n_late", "conflicts",
            "hls_birth_kind", "hls_death_kind", "life"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows_out)

    n_persons_linked = len({r["hgb_name"] for r in rows_out})
    n_overlap = sum(1 for r in rows_out if r["date_relation"] == "overlap")
    n_pm = sum(1 for r in rows_out if r["date_relation"] == "postmortem")
    high = sum(1 for r in rows_out if r["score"] >= 0.9)
    print(f"\n→ {len(rows_out)} candidate links "
          f"({n_persons_linked} distinct HGB persons)")
    print(f"   overlap: {n_overlap}, postmortem: {n_pm}, high-conf (≥0.90): {high}")
    partial = sum(1 for r in rows_out if r["n_early"] or r["n_late"])
    if mentions:
        print(f"   {partial} of them hold only part of the person's mentions")
    print(f"   written to {args.out}")
    print("\nTop 15 candidates:")
    for r in rows_out[:15]:
        print(f"  {r['score']:.2f} {r['date_relation']:>9} | "
              f"{r['hgb_name']} [{r['hgb_year_min']}–{r['hgb_year_max']}] ⇄ "
              f"{r['hls_title']} ({r['hls_birth']}–{r['hls_death']})")


if __name__ == "__main__":
    main()
