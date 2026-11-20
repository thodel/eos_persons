#!/usr/bin/env python3
"""
lifedates.py — the life of an HLS-linked person, and what the register may say
inside it.

A register person linked to an HLS biography has to live inside that
biography's life. The older rule (link_hls.date_relation) judged a whole
cluster of mentions by its first and last year with generous tolerances: five
years before a birth, fifteen years as living after a death. Checked mention by
mention, a third of the linked persons held mentions the life excludes — a
buyer of 1678 for a man born in 1687, a seller of 1650 for one who died in 1629:
the same-named father, son or grandson. This module is the stricter test, and
the rule by which such a person is split.

The life
--------
Two sources say when somebody lived, and neither always gives a birth and a
death:

  HLS       the header of the article qualifies its dates — "um 1485", "vor
            1546", "nach 1535", "Erstmals erwähnt 1505", "letztmals 1499".
            `date_kinds` reads the qualifier, `bounds` turns date and qualifier
            into the earliest and latest possible year.
  Wikidata  dates with a precision (fetch_wikidata_dates.py). A date given to
            the year is a second opinion: it replaces a vague HLS date it is
            compatible with (a birth year for "first mentioned 1505"), and
            where it contradicts a firm HLS date the life is widened to hold
            both — a mention is only called impossible when both sources
            exclude it.

A life is (blo, bhi, dlo, dhi): born between blo and bhi, died between dlo and
dhi.

The mentions
------------
`mention_conflict` names what the life excludes for one mention (its year,
whether the person is called deceased, whether the person acts in the
document):

  before_birth   any mention before the earliest possible birth
  child          a party to a transaction younger than ADULT
  dead_early     called deceased before the earliest possible death
  after_death    a party to a transaction after the latest possible death
  late_naming    named as living more than NAMED_AFTER years after the death —
                 a neighbour's house keeps the name of its late owner for a
                 while, and a rent roll that of its late payer, but not for a
                 generation
  beyond         any mention more than POSTMORTEM years after the death

`partition` sorts the mentions of a person into those of an earlier bearer of
the name, those of the life, and those of a later bearer; `fits` is the same
test on the summary a person carries in persons_resolved.json (first and last
year, first "deceased" year, first and last year as a party), for the dedupe
passes that merge whole persons.

"Called deceased" is the mark the corpus annotates ("selig", "sel."). A name
carried by a widow or by heirs ("Hans Müllers Wittib") is not read as one: if
she sells after his death, that mention is split off — and she is not him.
"""
import collections
import re

ADULT = 14          # a party to a property transaction is at least this old
NAMED_AFTER = 15    # a name outlives its bearer in neighbour and rent entries
POSTMORTEM = 60     # references to the late X reach this far
TOL = 1             # year styles and dating slack

# event roles in which the person acts — sells, buys, sues, pledges, consents.
# Not among them: owner (named as such long after), payer (rent rolls are
# copied), location-a/b (the neighbour's house), family-a/b, decedent,
# beneficiary, represented — roles a dead or an absent person can fill.
STRONG_ROLES = frozenset({
    "seller", "buyer", "claimant", "representative", "party1", "party2",
    "debitor", "creditor", "bidder", "pledger", "pledgee", "lessee", "builder",
    "redeemer", "offeror", "proclaimer", "consenting", "repr_claimant",
    "repr_seller", "repr_buyer", "owner-new", "actor"})

# roles that speak of the past: the previous payer of a rent, the former owner,
# the decedent of an inheritance. Such a mention does not name anybody as living.
PAST_ROLES = frozenset({"previous-payer", "owner-prev", "decedent"})

Life = collections.namedtuple("Life", "blo bhi dlo dhi")

EARLY = ("before_birth", "child")
LATE = ("after_death", "late_naming", "beyond")


# ── the qualifiers of an HLS header ──────────────────────────────────────────

_START = re.compile(r"\d|\bum |\bvor |\bnach |[Ee]rstmals|[Ee]rw|[Gg]etauft|zwischen|"
                    r"Anfang|Ende|Mitte")
_KIN = re.compile(r"\b(?:Sohn|Tochter|Bruder|Schwester|Neffe|Nichte|Enkel|Vater|Mutter|"
                  r"Ledig|Stud|Verheiratet|Aus der Familie|Aus dem Geschlecht)|​|∞|"
                  r"\d\) ")


def header(text):
    """The line of vital dates an HLS biography opens with (after the caption
    of a picture and the author's name), up to the first word on the family."""
    text = text or ""
    m = re.search(r"Autorin/Autor:\s*(.*)", text, re.S)
    if m:
        text = m.group(1)
    text = " ".join(text.split())
    m = _START.search(text)
    if m:
        text = text[m.start():]
    m = _KIN.search(text)
    return text[:min(m.start() if m else 200, 200)]


def _kind(words, death):
    s = words.lower()
    if "letztmals" in s:
        return "last_mention"
    if "erw" in s or "erstmals" in s:
        return "last_mention" if death else "first_mention"
    if re.search(r"\bnach\b", s):
        return "after"
    if re.search(r"\bvor\b", s):
        return "before"
    if "zwischen" in s or re.search(r"\d{4}\s?[/-]\s?\d", s):
        return "range"
    if re.search(r"\bum\b|\bca\b|\bwohl\b|vermutl|wahrsch", s):
        return "circa"
    return "exact"


def _around(h, i, floor):
    """The words that qualify the year at h[i:i+4]: back to the last comma (not
    behind `floor`), forward to the next comma or full stop."""
    a = max(h.rfind(", ", 0, i) + 2 if h.rfind(", ", 0, i) >= 0 else 0, floor)
    m = re.search(r", |\. |; ", h[i + 4:i + 34])
    e = i + 4 + (m.start() if m else 30)
    return h[a:e]


def date_kinds(text, b, d):
    """(kind of birth date, kind of death date) from the article text:
    exact | circa | range | before | after | first_mention / last_mention;
    None where the year does not stand in the header."""
    h = header(text)
    kb = kd = None
    ib = h.find(str(b)) if b else -1
    if ib >= 0:
        kb = _kind(_around(h, ib, 0), False)
    if d:
        i = h.find(str(d), ib + 4) if ib >= 0 else h.find(str(d))
        if i < 0 and not (ib >= 0 and b == d):
            i = h.find(str(d))
        if i >= 0:
            kd = _kind(_around(h, i, ib + 4 if 0 <= ib < i else 0), True)
    return kb, kd


# ── the life ─────────────────────────────────────────────────────────────────

def _birth(v, k):
    if k == "circa" or k == "range":
        return v - 5, v + 5
    if k == "before":
        return v - 30, v
    if k == "after":
        return v, v + 20
    if k == "first_mention":
        return v - 70, v - ADULT        # an adult by then, and not yet ancient
    return v, v


def _death(v, k, bhi):
    if k == "circa" or k == "range":
        return v - 5, v + 5
    if k == "before":
        return v - 10, v
    if k in ("after", "last_mention"):
        return v, min(v + 40, bhi + 95) if bhi is not None else v + 40
    return v, v


def explain(b, kb=None, d=None, kd=None, wd_b=(), wd_d=()):
    """(life, how the birth was settled, how the death was settled).

    The two labels say what Wikidata's year-precise dates did to the HLS date:
      no_wikidata        nothing to compare with
      agree              Wikidata's year lies inside the HLS bounds
      wikidata_used      the HLS date is a fence ("first mentioned", "before",
                         "after"); Wikidata's year respects it and is taken
      same_year          … Wikidata merely repeats the fence year as the date
      wikidata_ignored   … it does not respect the fence
      disagree           two firm dates that differ: the life holds both
      wikidata_only      the HLS has no date
    life is None when neither birth nor death is known.
    """
    wd_b, wd_d = sorted(wd_b), sorted(wd_d)
    blo = bhi = dlo = dhi = None
    lb = ld = "no_wikidata"
    if b:
        blo, bhi = _birth(b, kb)
    if wd_b:
        lo, hi = wd_b[0], wd_b[-1]
        if not b:
            blo, bhi, lb = lo - 2, hi + 2, "wikidata_only"
        elif kb in ("first_mention", "before", "after"):
            # a year for a birth the HLS only fences in — if it respects the fence
            if (kb == "first_mention" and hi <= b - ADULT) or \
               (kb == "before" and hi <= b) or (kb == "after" and lo >= b):
                blo, bhi, lb = lo - 5, hi + 5, "wikidata_used"
            elif lo - TOL <= b <= hi + TOL:
                lb = "same_year"        # Wikidata repeats the fence as the date
            else:
                lb = "wikidata_ignored"
        elif hi < blo - TOL or lo > bhi + TOL:
            blo, bhi, lb = min(blo, lo), max(bhi, hi), "disagree"
        else:
            lb = "agree"
    if d:
        dlo, dhi = _death(d, kd, bhi)
    if wd_d:
        lo, hi = wd_d[0], wd_d[-1]
        if not d:
            dlo, dhi, ld = lo - 1, hi + 1, "wikidata_only"
        elif kd in ("after", "last_mention", "before"):
            if lo - TOL <= d <= hi + TOL and kd != "before":
                ld = "same_year"        # "last mentioned 1499" given as the death
            elif (kd == "before" and hi <= d) or (kd != "before" and lo >= d):
                dlo, dhi, ld = lo - 1, hi + 1, "wikidata_used"
            else:
                ld = "wikidata_ignored"
        elif hi < dlo - TOL or lo > dhi + TOL:
            dlo, dhi, ld = min(dlo, lo), max(dhi, hi), "disagree"
        else:
            ld = "agree"
    if blo is None and dlo is None:
        return None, lb, ld
    if blo is None:                     # only a death: nobody acts for a century
        blo, bhi = dlo - 100, dhi - ADULT
    if dlo is None:                     # only a birth
        dlo, dhi = blo + ADULT, bhi + 95
    return Life(blo, bhi, dlo, dhi), lb, ld


def bounds(b, kb=None, d=None, kd=None, wd_b=(), wd_d=()):
    """Life from the HLS dates (with their kinds) and Wikidata's year-precise
    dates; None when neither birth nor death is known. See `explain`."""
    return explain(b, kb, d, kd, wd_b, wd_d)[0]


# ── one mention ──────────────────────────────────────────────────────────────

def mention_conflict(life, year, late, strong, past=False):
    """What the life excludes for a mention of `year`; None if nothing.
    `late`: the person is called deceased; `strong`: is a party (STRONG_ROLES)
    and not called deceased; `past`: named in a role of the past (PAST_ROLES),
    which is no naming as living."""
    if year < life.blo:
        return "before_birth"
    if strong and not late and year < life.blo + ADULT:
        return "child"
    if late and year < life.dlo - TOL:
        return "dead_early"
    if year > life.dhi + POSTMORTEM:
        return "beyond"
    if not late and strong and year > life.dhi + TOL:
        return "after_death"
    if not late and not past and year > life.dhi + NAMED_AFTER:
        return "late_naming"
    return None


def partition(life, mentions):
    """Sort mentions [(year, late, strong[, past])] into 'E' (an earlier bearer
    of the name), 'F' (the life) and 'L' (a later bearer).

    Returns (labels, kinds) — one label per mention, and a Counter of the
    conflicts found. Without a conflict everything is 'F'. Where one is found,
    the mentions around it follow: once somebody of that name acts before the
    person is of age, everything up to that age is the earlier bearer's; once
    somebody acts after the death, every later mention as living is the later
    bearer's — and so is a later "deceased", which then is that bearer's death.
    If nothing remains from the lifetime itself, nothing remains at all.
    """
    con = [mention_conflict(life, *m) for m in mentions]
    kinds = collections.Counter(k for k in con if k)
    if not kinds:
        return ["F"] * len(mentions), kinds
    early = any(k in EARLY for k in con)
    late_from = min((m[0] for m, k in zip(mentions, con) if k in LATE), default=None)
    labels = []
    for m, k in zip(mentions, con):
        y, late, past = m[0], m[1], len(m) > 3 and m[3]
        if k == "dead_early" or (early and y < life.blo + ADULT):
            labels.append("E")
        elif late_from is not None and y > life.dhi + TOL and \
                (not (late or past) or y >= late_from):
            labels.append("L")
        else:
            labels.append("F")
    if "L" in labels and not any(lab == "F" and m[0] <= life.dhi
                                 for lab, m in zip(labels, mentions)):
        labels = ["L" if lab == "F" else lab for lab in labels]
    return labels, kinds


# ── a whole person ───────────────────────────────────────────────────────────

def fits(life, y0, y1, dead_year=None, act=None, living=None):
    """Can a person mentioned y0…y1 — first called deceased in `dead_year`, a
    party to transactions in the years act[0]…act[1], last named as living in
    `living` (see `extra`) — be the one who lived `life`? The summary-level
    form of `mention_conflict`."""
    if life is None:
        return True
    if y0 < life.blo or y1 > life.dhi + POSTMORTEM:
        return False
    if act and (act[0] < life.blo + ADULT or act[1] > life.dhi + TOL):
        return False
    if dead_year and dead_year < life.dlo - TOL:
        return False
    if living is not None and living > life.dhi + NAMED_AFTER:
        return False
    return True


def extra(p):
    """What a person of the index knows beyond first and last year: (years as
    a party to a transaction, last year named as living). build_data.py keeps
    them as `a` and `ly`; `ly` is only written where it is not the last
    mention, and is 0 for somebody never named as living."""
    y = p.get("y") or [None, None]
    return (p.get("a"), p.get("ly", y[1]) or None)


def extra_merge(a, b):
    """`extra` of two persons taken together."""
    if a is None or b is None:
        return a or b
    living = [x for x in (a[1], b[1]) if x is not None]
    return (span_merge(a[0], b[0]), max(living) if living else None)


def span_merge(a, b):
    """Union of two optional [first, last] year spans."""
    if not a:
        return list(b) if b else None
    if not b:
        return list(a)
    return [min(a[0], b[0]), max(a[1], b[1])]
