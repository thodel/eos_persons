#!/usr/bin/env python3
"""
link_hbls_hgb.py — Stage 2: link HBLS person records to EOS/HGB persons.

Two complementary passes (see hbls-extraction/DEDUP_PLAN.md):

  (a) DIRECT — match HBLS persons (surname + given + life span) against the
      resolved HGB persons (persons_resolved.json), requiring the HGB *mention
      span* to overlap the HBLS life span (post-mortem references allowed within
      a grace window). Reuses link_hls.date_relation.

  (b) TRANSITIVE — if an HBLS person and an HGB person were each independently
      linked to the *same* HLS biography (link_hbls_hls_candidates.csv ∩
      link_candidates_hls.csv on hls_id), they denote the same person. These are
      the highest-confidence cross-links.

Scoped to the Basel slice by default (hbls-extraction/hbls_persons_basel.json),
because the HGB corpus is the Historisches Grundbuch *Basel*; pass --all to run
the whole HBLS corpus.

    python3 link_hbls_hgb.py            # Basel slice, both passes
    python3 link_hbls_hgb.py --all
"""
import argparse
import collections
import csv
import re
import json
import os

from link_hls import split_name, norm_token, given_key, given_ratio, ratio, date_relation

csv.field_size_limit(10_000_000)
HERE = os.path.dirname(os.path.abspath(__file__))


def load_hgb(path):
    persons = json.load(open(path, encoding="utf-8"))
    by_initial = collections.defaultdict(list)
    for p in persons:
        given, surname = split_name(p["n"])
        if not surname or not given:
            continue
        y = p.get("y")
        if not y:
            continue
        by_initial[surname[0]].append({
            "name": p["n"], "given": given, "surname": surname,
            "m0": y[0], "m1": y[1], "dead": p.get("dead_year"),
            "ment": p.get("c", 0), "dos": p.get("d", 0),
        })
    return by_initial


BASEL = re.compile(r"\bBasel\b|\bbasler\b|\bbaslerisch", re.I)


def basel_connection(hbls):
    """{HBLS person id: 'bio' | 'article'} for the persons connected to Basel.

    The HBLS covers all of Switzerland, the register one town: by name and
    dates a Landammann of Urnäsch fits a Basel namesake as well as a Basler
    does (191 of the 303 links the full corpus yielded were of that kind). A
    person counts as connected when the own entry mentions Basel ('bio') or
    the family article does ('article') — the definition of basel_subset.py.
    The article texts (hbls_articles.json) come from the PDF extraction; where
    they are missing only 'bio' can be told.
    """
    art = set()
    f = os.path.join(HERE, "hbls-extraction", "hbls_articles.json")
    if os.path.exists(f):
        for a in json.load(open(f, encoding="utf-8")):
            m = re.search(r"band_(\d+)", a.get("source_file") or "")
            if BASEL.search(a.get("content") or ""):
                art.add((int(m.group(1)) if m else None, a["page"], a["keyword"]))
    out = {}
    for p in hbls:
        if BASEL.search(p.get("bio") or ""):
            out[p["id"]] = "bio"
        elif (p.get("volume"), p.get("page"), p.get("keyword")) in art:
            out[p["id"]] = "article"
    return out


def hbls_lifespan(p):
    b, d = p.get("birth_year"), p.get("death_year")
    fl = p.get("floruit_years")
    if not (b or d) and fl:
        b, d = min(fl) - 30, max(fl) + 10
    return b, d


def direct_pass(hbls, by_initial, surname_min, given_min, grace):
    """Every HBLS person against every register person of a similar name whose
    mentions fit the life.

    27,838 HBLS persons against 95,000 register persons is 2.6 thousand million
    pairs, most of them centuries apart: the dates are checked before the
    names, and each pair of distinct surnames is compared once.
    """
    # register persons by surname, in index order (i keeps ties stable)
    by_surname = {}
    i = 0
    for ini, plist in by_initial.items():
        grp = by_surname.setdefault(ini, {})
        for h in plist:
            grp.setdefault(h["surname"], []).append((i, h))
            i += 1
    sratio, gratio = {}, {}
    basel = basel_connection(hbls)
    rows = []
    matched = 0
    for p in hbls:
        surname = norm_token(p["surname"].split()[-1]) if p["surname"] else ""
        given = given_key(p["given"])
        if not surname or not given:
            continue
        b, d = hbls_lifespan(p)
        if b is None and d is None:
            continue
        cands = []
        for hs, plist in by_surname.get(surname[0], {}).items():
            sr = sratio.get((surname, hs))
            if sr is None:
                sr = sratio[(surname, hs)] = ratio(surname, hs)
            if sr < surname_min:
                continue
            for i, h in plist:
                rel, gap = date_relation(h["m0"], h["m1"], h["dead"], b, d, grace=grace)
                if rel is None:
                    continue
                gr = gratio.get((given, h["given"]))
                if gr is None:
                    gr = gratio[(given, h["given"])] = given_ratio(given, h["given"])
                if gr < given_min:
                    continue
                score = round(0.4 * sr + 0.3 * gr +
                              0.3 * (1.0 if rel == "overlap" else 0.7), 3)
                cands.append((i, {
                    "hbls_id": p["id"], "hbls_name": p["name"],
                    "hbls_surname": p["surname"], "hbls_given": p["given"],
                    "hbls_birth": p.get("birth_year") or "",
                    "hbls_death": p.get("death_year") or "",
                    "hbls_volume": p["volume"], "hbls_page": p["page"],
                    "hbls_url": p["backlink"],
                    "hbls_basel": basel.get(p["id"], ""),
                    "hgb_name": h["name"], "hgb_year_min": h["m0"],
                    "hgb_year_max": h["m1"], "hgb_mentions": h["ment"],
                    "hgb_dossiers": h["dos"],
                    "surname_score": round(sr, 3), "given_score": round(gr, 3),
                    "date_relation": rel, "date_gap": gap, "score": score,
                }))
        if not cands:
            continue
        matched += 1
        cands.sort(key=lambda t: (-t[1]["score"], t[0]))
        for _, c in cands:
            c["n_candidates"] = len(cands)
        rows.extend(c for _, c in cands)
    return rows, matched


def transitive_pass(hbls_ids):
    """Join HBLS↔HLS and HGB↔HLS candidate tables on hls_id."""
    f_hbls = os.path.join(HERE, "link_hbls_hls_candidates.csv")
    f_hgb = os.path.join(HERE, "link_candidates_hls.csv")
    if not (os.path.exists(f_hbls) and os.path.exists(f_hgb)):
        print("  (transitive pass skipped: candidate CSVs missing)")
        return []
    hbls_by_hls = collections.defaultdict(list)
    for r in csv.DictReader(open(f_hbls, encoding="utf-8")):
        hbls_by_hls[r["hls_id"]].append(r)
    # collapse the cartesian product to one row per (hbls_id, hgb_name) pair,
    # keeping the best (lowest-ambiguity) supporting evidence.
    best = {}
    for r in csv.DictReader(open(f_hgb, encoding="utf-8")):
        for hb in hbls_by_hls.get(r["hls_id"], []):
            if hbls_ids is not None and hb["hbls_id"] not in hbls_ids:
                continue
            key = (hb["hbls_id"], r["hgb_name"].strip())
            row = {
                "hbls_id": hb["hbls_id"], "hbls_name": hb["hbls_name"],
                "hgb_name": r["hgb_name"].strip(),
                "via_hls_id": r["hls_id"], "hls_title": r.get("hls_title", ""),
                "hbls_hls_score": hb["score"], "hgb_hls_score": r["score"],
                "hbls_hls_ambig": hb.get("n_candidates", ""),
                "hgb_hls_ambig": r.get("n_candidates_for_person", ""),
            }
            prev = best.get(key)
            if prev is None or _ambig(row) < _ambig(prev):
                best[key] = row
    return list(best.values())


def _ambig(r):
    try:
        return int(r["hbls_hls_ambig"] or 9) + int(r["hgb_hls_ambig"] or 9)
    except ValueError:
        return 18


def write_csv(path, rows, cols):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hgb", default="persons_resolved.json")
    ap.add_argument("--all", action="store_true",
                    help="use the full HBLS corpus instead of the Basel slice")
    ap.add_argument("--surname-min", type=float, default=0.85)
    ap.add_argument("--given-min", type=float, default=0.74)
    ap.add_argument("--postmortem-grace", type=int, default=60)
    args = ap.parse_args()

    hbls_path = os.path.join(
        HERE, "hbls-extraction",
        "hbls_persons.json" if args.all else "hbls_persons_basel.json")
    hbls = json.load(open(hbls_path, encoding="utf-8"))
    scope = "ALL HBLS" if args.all else "Basel slice"
    print(f"HBLS persons ({scope}): {len(hbls)}")

    print("Loading HGB persons …")
    by_initial = load_hgb(args.hgb)
    print(f"  {sum(len(v) for v in by_initial.values())} dated HGB persons")

    print("Direct pass …")
    direct, matched = direct_pass(hbls, by_initial, args.surname_min,
                                  args.given_min, args.postmortem_grace)
    out_direct = "link_hbls_hgb_candidates.csv"
    write_csv(out_direct, direct,
              ["hbls_id", "hbls_name", "hbls_surname", "hbls_given",
               "hbls_birth", "hbls_death", "hbls_volume", "hbls_page",
               "hbls_url", "hbls_basel", "hgb_name", "hgb_year_min", "hgb_year_max",
               "hgb_mentions", "hgb_dossiers", "surname_score", "given_score",
               "date_relation", "date_gap", "score", "n_candidates"])
    uniq = len({r["hbls_id"] for r in direct if r["n_candidates"] == 1})
    n_basel = len({r["hbls_id"] for r in direct
                   if r["n_candidates"] == 1 and r["hbls_basel"]})
    print(f"  {matched} HBLS persons matched ≥1 HGB person; {len(direct)} rows "
          f"({uniq} unambiguous, {n_basel} of them connected to Basel) -> {out_direct}")

    print("Transitive pass (via shared HLS bio) …")
    hbls_ids = None if args.all else {p["id"] for p in hbls}
    trans = transitive_pass(hbls_ids)
    out_trans = "link_hbls_hgb_transitive.csv"
    write_csv(out_trans, trans,
              ["hbls_id", "hbls_name", "hgb_name", "via_hls_id", "hls_title",
               "hbls_hls_score", "hgb_hls_score", "hbls_hls_ambig",
               "hgb_hls_ambig"])
    print(f"  {len(trans)} transitive HBLS↔HGB pairs -> {out_trans}")


if __name__ == "__main__":
    main()
