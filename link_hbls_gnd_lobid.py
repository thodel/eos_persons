#!/usr/bin/env python3
"""
link_hbls_gnd_lobid.py — Tier 1 GND linking: direct lobid lookup.

For HBLS persons that Tier 0 (link_hbls_gnd.py) could not resolve via
HLS→Wikidata, query the GND directly through lobid. We search differentiated
persons by surname+given and accept a hit only when the life dates also agree —
the same name+date model as the other linkers. See GND_LINKING_PLAN.md (Tier 1).

Polite usage (per https://lobid.org/usage-policy): descriptive User-Agent,
on-disk response cache (reruns are free), and a throttle between live calls.

    python3 link_hbls_gnd_lobid.py --basel            # Basel slice
    python3 link_hbls_gnd_lobid.py --basel --limit 50 # quick validation
"""
import argparse
import csv
import hashlib
import json
import os
import time
import unicodedata
import urllib.parse
import urllib.request

from link_hls import norm_token, canon_given, ratio
from link_hbls_hls import year_agreement

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "hbls-extraction", ".lobid_cache")
UA = ("eos-persons-linker/1.0 "
      "(https://github.com/thodel/eos_persons; tobiashodel@gmail.com)")
BASE = "https://lobid.org/gnd/search"


def ascii_fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def lobid_search(query, size=15, throttle=0.5):
    """Cached + throttled lobid GND search. Returns the `member` list."""
    os.makedirs(CACHE, exist_ok=True)
    params = urllib.parse.urlencode({
        "q": query, "filter": "type:DifferentiatedPerson",
        "format": "json", "size": size})
    url = f"{BASE}?{params}"
    key = hashlib.md5(url.encode()).hexdigest()
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8")).get("member", [])
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            json.dump(data, open(path, "w", encoding="utf-8"))
            time.sleep(throttle)
            return data.get("member", [])
        except Exception as e:
            if attempt == 3:
                print(f"    lobid error for {query!r}: {e}")
                return []
            time.sleep(2 + attempt * 3)


def first_year(date_list):
    for s in date_list or []:
        for tok in str(s).split("-"):
            if len(tok) == 4 and tok.isdigit():
                return int(tok)
    return None


def split_pref(name):
    """lobid preferredName 'Surname, Given' -> (given, surname)."""
    if "," in name:
        surname, given = name.split(",", 1)
        return given.strip(), surname.strip()
    parts = name.split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", name)


def score_member(p_surname, p_given, hb, hd, hfl, m):
    g_pref, s_pref = split_pref(m.get("preferredName", ""))
    sr = ratio(norm_token(p_surname), norm_token(s_pref))
    if sr < 0.85:
        # try variant names
        best = 0.0
        for v in m.get("variantName", []):
            _, vs = split_pref(v)
            best = max(best, ratio(norm_token(p_surname), norm_token(vs)))
        sr = max(sr, best)
        if sr < 0.85:
            return None
    gr = ratio(canon_given(p_given.split()[0]) if p_given else "",
               canon_given(g_pref.split()[0]) if g_pref else "")
    if gr < 0.74:
        return None
    gb = first_year(m.get("dateOfBirth"))
    gd = first_year(m.get("dateOfDeath"))
    ok, close, label = year_agreement(hb, hd, hfl, gb, gd)
    if not ok:
        return None
    score = round(0.4 * sr + 0.3 * gr + 0.3 * close, 3)
    return {
        "gnd": m.get("gndIdentifier"),
        "gnd_name": m.get("preferredName", ""),
        "gnd_birth": gb or "", "gnd_death": gd or "",
        "gnd_occupations": "|".join(
            o.get("label", "") for o in m.get("professionOrOccupation", [])),
        "surname_score": round(sr, 3), "given_score": round(gr, 3),
        "year_match": label, "score": score,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basel", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap lookups (testing)")
    ap.add_argument("--include-floruit", action="store_true",
                    help="also look up floruit-only persons (low GND yield)")
    ap.add_argument("--skip-tier0", default="link_hbls_gnd.csv",
                    help="CSV of persons already GND-linked by Tier 0")
    ap.add_argument("--out", default="link_hbls_gnd_lobid_candidates.csv")
    args = ap.parse_args()

    fname = "hbls_persons_basel.json" if args.basel else "hbls_persons.json"
    persons = json.load(open(os.path.join(HERE, "hbls-extraction", fname),
                             encoding="utf-8"))

    done = set()
    p0 = os.path.join(HERE, args.skip_tier0)
    if os.path.exists(p0):
        for r in csv.DictReader(open(p0, encoding="utf-8")):
            if r.get("date_check") == "ok":
                done.add(r["hbls_id"])
    # persons not already resolved by Tier 0, with a name and a usable date.
    # GND coverage for floruit-only (mostly medieval) persons is ~nil, so by
    # default we look up only those with an explicit birth/death year.
    def has_date(p):
        if p.get("birth_year") or p.get("death_year"):
            return True
        return args.include_floruit and bool(p.get("floruit_years"))
    todo = [p for p in persons if p["id"] not in done and has_date(p)
            and p.get("given") and p.get("surname")]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(persons)} persons; {len(done)} already GND-linked (Tier 0); "
          f"{len(todo)} to look up on lobid")

    rows = []
    for i, p in enumerate(todo, 1):
        sn = ascii_fold(p["surname"].split()[-1])
        gn = ascii_fold(p["given"].split()[0])
        q = f'preferredName.ascii:"{sn}" AND preferredName.ascii:"{gn}"'
        members = lobid_search(q)
        if not members:
            members = lobid_search(f'variantName.ascii:"{sn}" AND '
                                   f'preferredName.ascii:"{gn}"')
        hb, hd = p.get("birth_year"), p.get("death_year")
        hfl = p.get("floruit_years")
        cands = []
        for m in members:
            sc = score_member(p["surname"], p["given"], hb, hd, hfl, m)
            if sc:
                sc.update({"hbls_id": p["id"], "hbls_name": p["name"],
                           "hbls_birth": hb or "", "hbls_death": hd or "",
                           "hbls_volume": p["volume"], "hbls_page": p["page"]})
                cands.append(sc)
        cands.sort(key=lambda r: -r["score"])
        for c in cands:
            c["n_candidates"] = len(cands)
        rows.extend(cands)
        if i % 100 == 0:
            print(f"  …{i}/{len(todo)} looked up, {len(rows)} candidate rows")

    cols = ["hbls_id", "hbls_name", "hbls_birth", "hbls_death", "hbls_volume",
            "hbls_page", "gnd", "gnd_name", "gnd_birth", "gnd_death",
            "gnd_occupations", "surname_score", "given_score", "year_match",
            "score", "n_candidates"]
    with open(os.path.join(HERE, args.out), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    persons_hit = len({r["hbls_id"] for r in rows})
    uniq = len({r["hbls_id"] for r in rows if r["n_candidates"] == 1})
    print(f"\n{persons_hit} HBLS persons matched ≥1 GND ({uniq} unambiguous); "
          f"{len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
