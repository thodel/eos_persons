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
import re
import csv
import json
import argparse
import unicodedata
import collections
from difflib import SequenceMatcher

csv.field_size_limit(10_000_000)

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


# ── Load HLS biographies in the HGB era ──────────────────────────────────────

def load_hls(path, era_lo=1380, era_hi=1720):
    """Return list of bio dicts with parsed years, blocked by surname initial."""
    bios = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("category") != "bio":
                continue
            fam = (row.get("bio.family_name") or "").strip()
            first = (row.get("bio.first_name") or "").strip()
            if not fam and not first:
                continue
            b = year_of(row.get("bio.birth_date"))
            d = year_of(row.get("bio.death_date"))
            # estimate the missing bound so the era filter still works
            lo = b if b else (d - 90 if d else None)
            hi = d if d else (b + 90 if b else None)
            if not (lo and hi):
                continue
            if hi < era_lo or lo > era_hi:
                continue
            surname = norm_token(fam.split()[-1]) if fam else ""
            given = given_key(first)
            bios.append({
                "id": row.get("id"),
                "version": (row.get("version") or "").strip(),
                "title": row.get("title", "").strip(),
                "first": first, "family": fam,
                "given_n": given, "surname_n": surname,
                "birth": b, "death": d,
                "lex": (row.get("lexical_class") or "").strip("[]'\""),
            })
    return bios


# ── Date plausibility ────────────────────────────────────────────────────────

def date_relation(m0, m1, dead_year, birth, death, grace=60, tol=3):
    """Classify the temporal relation between an HGB mention span [m0,m1]
    (with optional HGB dead_year) and an HLS life span [birth,death].

    Returns (relation, gap) or (None, _) if implausible.
      relation ∈ {"overlap", "postmortem"}.
    """
    if m0 is None or m1 is None:
        return (None, None)
    b = birth
    d = death if death else (birth + 90 if birth else None)
    if b is None and death is not None:
        b = death - 90
    if b is None or d is None:
        return (None, None)

    # mentioned entirely before plausible birth → not the same person
    if m1 < b - tol:
        return (None, None)
    # life span and mention span intersect
    if m0 <= d + tol and m1 >= b - tol:
        return ("overlap", 0)
    # mentions begin after death → post-mortem reference (allowed within grace)
    if m0 > d:
        gap = m0 - d
        if gap <= grace:
            return ("postmortem", gap)
    return (None, None)


# ── Matching ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Link HGB persons to HLS biographies.")
    ap.add_argument("--persons", default="persons_resolved.json")
    ap.add_argument("--hls", default="/Users/TH_1/Documents/HLS/hls_articles.csv")
    ap.add_argument("--out", default="link_candidates_hls.csv")
    ap.add_argument("--surname-min", type=float, default=0.82)
    ap.add_argument("--given-min", type=float, default=0.74)
    ap.add_argument("--postmortem-grace", type=int, default=60)
    ap.add_argument("--given-mode", choices=("prefix", "first"), default="prefix",
                    help="'first' restores the old first-given-token-only rule, "
                         "for A/B measurement against the current prefix rule")
    args = ap.parse_args()

    global GIVEN_MODE
    GIVEN_MODE = args.given_mode

    print("Loading HLS biographies …")
    bios = load_hls(args.hls)
    by_initial = collections.defaultdict(list)
    for bio in bios:
        if bio["surname_n"]:
            by_initial[bio["surname_n"][0]].append(bio)
    print(f"  {len(bios)} HLS bios in the HGB era "
          f"({len(by_initial)} surname initials)")

    print("Loading HGB persons …")
    persons = json.load(open(args.persons, encoding="utf-8"))
    print(f"  {len(persons)} resolved persons")

    rows_out = []
    n_checked = 0
    for p in persons:
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
            gr = given_ratio(given, bio["given_n"]) if bio["given_n"] else 0.0
            if gr < args.given_min:
                continue
            rel, gap = date_relation(m0, m1, dead, bio["birth"], bio["death"],
                                     grace=args.postmortem_grace)
            if rel is None:
                continue
            score = round(0.6 * sr + 0.4 * gr - (0.0 if rel == "overlap" else 0.05), 3)
            best_for_person.append({
                "hgb_name": p["n"],
                "hgb_year_min": m0, "hgb_year_max": m1,
                "hgb_dead_year": dead if dead else "",
                "hgb_mentions": p.get("c", 0),
                "hls_id": bio["id"], "hls_title": bio["title"],
                "hls_first": bio["first"], "hls_family": bio["family"],
                "hls_birth": bio["birth"] or "", "hls_death": bio["death"] or "",
                "hls_lexical_class": bio["lex"],
                "surname_score": round(sr, 3), "given_score": round(gr, 3),
                "date_relation": rel, "date_gap": gap,
                "score": score,
                "hls_version": bio["version"],
                "hls_url": hls_url(bio["id"], bio["version"]),
            })
        # keep all candidates for this person, but flag ambiguity
        best_for_person.sort(key=lambda r: -r["score"])
        for rank, cand in enumerate(best_for_person):
            cand["n_candidates_for_person"] = len(best_for_person)
            cand["rank"] = rank + 1
            rows_out.append(cand)

    rows_out.sort(key=lambda r: (-r["score"], r["hgb_name"]))

    cols = ["score", "date_relation", "date_gap", "surname_score", "given_score",
            "hgb_name", "hgb_year_min", "hgb_year_max", "hgb_dead_year",
            "hgb_mentions", "hls_id", "hls_title", "hls_first", "hls_family",
            "hls_birth", "hls_death", "hls_lexical_class",
            "n_candidates_for_person", "rank", "hls_version", "hls_url"]
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
    print(f"   written to {args.out}")
    print("\nTop 15 candidates:")
    for r in rows_out[:15]:
        print(f"  {r['score']:.2f} {r['date_relation']:>9} | "
              f"{r['hgb_name']} [{r['hgb_year_min']}–{r['hgb_year_max']}] ⇄ "
              f"{r['hls_title']} ({r['hls_birth']}–{r['hls_death']})")


if __name__ == "__main__":
    main()
