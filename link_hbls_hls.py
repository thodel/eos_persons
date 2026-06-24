#!/usr/bin/env python3
"""
link_hbls_hls.py — propose links between HBLS person records and HLS biographies.

HBLS (Historisch-Biographisches Lexikon der Schweiz, 1921-34) is the printed
predecessor of the online HLS. Many HBLS persons therefore have a direct HLS
successor article. This script matches the clean HBLS person records
(hbls-extraction/hbls_persons.json) against the HLS biography export, keeping
candidates where surname + given name are similar AND the life dates agree.

Unlike link_hls.py (which matches HGB *mention spans* against HLS lifespans),
HBLS records carry explicit birth/death years, so we match life-date to
life-date — a much stronger signal. Output is a candidate CSV for review, not an
automatic merge.

    python3 link_hbls_hls.py \
        --hbls hbls-extraction/hbls_persons.json \
        --hls  /Users/TH_1/Documents/HLS/hls_articles.csv \
        --out  link_hbls_hls_candidates.csv
"""
import argparse
import collections
import csv
import json

# reuse the battle-tested name normalisation from the HGB→HLS linker
from link_hls import norm_token, canon_given, ratio, year_of, hls_url

csv.field_size_limit(10_000_000)

YEAR_TOL = 4        # birth/death years within this are "the same"
YEAR_TOL_LOOSE = 9  # both birth & death within this also counts


def load_hls_bios(path):
    """All HLS biography articles with at least one parsed life year."""
    bios = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("category") != "bio":
                continue
            fam = (row.get("bio.family_name") or "").strip()
            first = (row.get("bio.first_name") or "").strip()
            if not fam:
                continue
            b = year_of(row.get("bio.birth_date"))
            d = year_of(row.get("bio.death_date"))
            if b is None and d is None:
                continue
            bios.append({
                "id": row.get("id"),
                "version": (row.get("version") or "").strip(),
                "title": row.get("title", "").strip(),
                "first": first, "family": fam,
                "given_n": canon_given(first.split()[0]) if first else "",
                "surname_n": norm_token(fam.split()[-1]),
                "birth": b, "death": d,
                "lex": (row.get("lexical_class") or "").strip("[]'\""),
            })
    return bios


def year_agreement(hb, hd, hfl, b, d):
    """Return (ok, closeness 0..1, label) for HBLS (hb,hd,floruit) vs HLS (b,d)."""
    db = abs(hb - b) if (hb and b) else None
    dd = abs(hd - d) if (hd and d) else None
    if db is not None and db <= YEAR_TOL:
        return True, 1 - db / (YEAR_TOL + 1), f"birth±{db}"
    if dd is not None and dd <= YEAR_TOL:
        return True, 1 - dd / (YEAR_TOL + 1), f"death±{dd}"
    if (db is not None and dd is not None
            and db <= YEAR_TOL_LOOSE and dd <= YEAR_TOL_LOOSE):
        return True, 1 - (db + dd) / (2 * (YEAR_TOL_LOOSE + 1)), f"both±{max(db,dd)}"
    # HBLS only has floruit years: require them to sit within the HLS lifespan
    if hfl and (b or d):
        lo = (b or (d - 90)) - 5
        hi = (d or (b + 90)) + 5
        inside = [y for y in hfl if lo <= y <= hi]
        if inside and len(inside) / len(hfl) >= 0.6:
            return True, 0.4, "floruit-in-span"
    return False, 0.0, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hbls", default="hbls-extraction/hbls_persons.json")
    ap.add_argument("--hls", default="/Users/TH_1/Documents/HLS/hls_articles.csv")
    ap.add_argument("--out", default="link_hbls_hls_candidates.csv")
    ap.add_argument("--surname-min", type=float, default=0.85)
    ap.add_argument("--given-min", type=float, default=0.74)
    args = ap.parse_args()

    print("Loading HLS biographies …")
    bios = load_hls_bios(args.hls)
    by_initial = collections.defaultdict(list)
    for bio in bios:
        if bio["surname_n"]:
            by_initial[bio["surname_n"][0]].append(bio)
    print(f"  {len(bios)} HLS bios with life dates "
          f"({len(by_initial)} surname initials)")

    print("Loading HBLS persons …")
    persons = json.load(open(args.hbls, encoding="utf-8"))
    print(f"  {len(persons)} HBLS persons")

    rows = []
    matched_persons = 0
    for p in persons:
        surname = norm_token(p["surname"].split()[-1]) if p["surname"] else ""
        given = canon_given(p["given"].split()[0]) if p["given"] else ""
        if not surname or not given:
            continue
        hb, hd = p.get("birth_year"), p.get("death_year")
        hfl = p.get("floruit_years")
        if not (hb or hd or hfl):
            continue

        cands = []
        for bio in by_initial.get(surname[0], []):
            sr = ratio(surname, bio["surname_n"])
            if sr < args.surname_min:
                continue
            gr = ratio(given, bio["given_n"]) if bio["given_n"] else 0.0
            if gr < args.given_min:
                continue
            ok, close, label = year_agreement(hb, hd, hfl, bio["birth"], bio["death"])
            if not ok:
                continue
            score = round(0.4 * sr + 0.3 * gr + 0.3 * close, 3)
            cands.append({
                "hbls_id": p["id"], "hbls_name": p["name"],
                "hbls_surname": p["surname"], "hbls_given": p["given"],
                "hbls_birth": hb or "", "hbls_death": hd or "",
                "hbls_volume": p["volume"], "hbls_page": p["page"],
                "hls_id": bio["id"], "hls_title": bio["title"],
                "hls_first": bio["first"], "hls_family": bio["family"],
                "hls_birth": bio["birth"] or "", "hls_death": bio["death"] or "",
                "hls_lexical_class": bio["lex"],
                "surname_score": round(sr, 3), "given_score": round(gr, 3),
                "year_match": label, "score": score,
                "hls_url": hls_url(bio["id"], bio["version"]),
            })
        if not cands:
            continue
        matched_persons += 1
        cands.sort(key=lambda r: -r["score"])
        for c in cands:
            c["n_candidates"] = len(cands)
        rows.extend(cands)

    cols = ["hbls_id", "hbls_name", "hbls_surname", "hbls_given", "hbls_birth",
            "hbls_death", "hbls_volume", "hbls_page", "hls_id", "hls_title",
            "hls_first", "hls_family", "hls_birth", "hls_death",
            "hls_lexical_class", "surname_score", "given_score", "year_match",
            "score", "n_candidates", "hls_url"]
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    print(f"\n{matched_persons} HBLS persons matched ≥1 HLS bio; "
          f"{len(rows)} candidate rows -> {args.out}")
    uniq = len({r["hbls_id"] for r in rows if r["n_candidates"] == 1})
    print(f"  of which {uniq} are unambiguous (single HLS candidate)")


if __name__ == "__main__":
    main()
