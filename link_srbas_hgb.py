#!/usr/bin/env python3
"""
link_srbas_hgb.py — link person names from the Basel Jahrrechnungen (srbas,
GAMS Graz, 1535–1610) to persons of the Historisches Grundbuch Basel.

Input: srbas-extraction/srbas_name_mentions.csv (heuristic name mentions with
year, account and citable GAMS fragment URI; see srbas-extraction/README.md).
Mentions are first aggregated into srbas *name profiles*
(given_norm + surname_norm -> years, bookings, accounts), then each profile is
matched against two HGB targets:

  (a) CORPUS   persons_resolved.json — the corpus-wide HGB name index used by
               link_hbls_hgb.py. Broad recall, homonyms across the whole city.
  (b) STREET   hgb_street_persons.json — street-level persons built from the
               DHBern annotated release (build_hgb_street_persons.py), with
               the HGB identity resolution applied per street. Each candidate
               carries street, dossiers and LV95 point, so a hit places the
               Jahrrechnung name on the map; homonyms on different streets
               stay apart.

Name comparison reuses link_hls (ratio on surname, given_ratio on the
canonicalised given names). Surnames are compared on the raw form, the
normalised form and a de-inflected form (-en/-n/-s stripped) and the best
wins, because the accounts write names in the dative/genitive ("von Jacoben
Gebharten"). Temporal plausibility: the srbas mention years must fall inside
the HGB mention span widened by --year-tol (default 15); a person named in a
Jahrrechnung is alive and active at that moment, so no post-mortem grace.

    python3 link_srbas_hgb.py                 # both targets
    python3 link_srbas_hgb.py --no-street     # corpus target only

Outputs (tracked):
  link_srbas_hgb_candidates.csv         corpus target
  link_srbas_hgb_street_candidates.csv  street target
"""
import argparse
import collections
import csv
import json
import os
import re

from link_hls import norm_token, given_key, given_ratio, ratio

HERE = os.path.dirname(os.path.abspath(__file__))
MENTIONS = os.path.join(HERE, "srbas-extraction", "srbas_name_mentions.csv")
STREET = os.path.join(HERE, "hgb_street_persons.json")
csv.field_size_limit(10_000_000)


def surname_forms(*raw):
    """Candidate surname keys: as given, and with dative/genitive endings removed."""
    forms = set()
    for r in raw:
        t = norm_token(r.split()[-1]) if r else ""
        if not t:
            continue
        forms.add(t)
        if len(t) > 5 and t.endswith("en"):
            forms.add(t[:-2])
        if len(t) > 4 and t[-1] in "ns":
            forms.add(t[:-1])
    return forms


def _bigrams(t):
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t}


def best_surname_ratio(forms_a, forms_b, floor):
    """max ratio over the form pairs, with a cheap bigram pre-filter: pairs
    whose bigram overlap cannot reach `floor` never go to SequenceMatcher."""
    best = 0.0
    for a in forms_a:
        ba = _bigrams(a)
        for b in forms_b:
            if a[0] != b[0] or abs(len(a) - len(b)) > 3:
                continue
            bb = _bigrams(b)
            if len(ba & bb) / max(len(ba | bb), 1) < 0.3 and a != b:
                continue
            r = ratio(a, b)
            if r > best:
                best = r
                if best >= 1.0:
                    return best
    return best if best >= floor else 0.0


def index_by_prefix(persons):
    """Block HGB persons by the first two letters of each surname form."""
    idx = collections.defaultdict(list)
    for h in persons:
        for f in h["forms"]:
            idx[f[:2]].append(h)
    # a person can sit under several prefixes; dedupe at lookup time via id
    return idx


def load_profiles(path):
    prof = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        key = (r["given_norm"], r["surname_norm"])
        p = prof.get(key)
        if p is None:
            p = prof[key] = {
                "given_norm": r["given_norm"], "surname_norm": r["surname_norm"],
                "given_key": given_key(r["given_norm"]),
                "surname_forms": set(), "years": [], "n": 0,
                "accounts": collections.Counter(), "origins": collections.Counter(),
                "uris": [], "raw": collections.Counter(),
            }
        p["surname_forms"] |= surname_forms(r["surname_raw"], r["surname_norm"])
        p["years"].append(int(r["year"]))
        p["n"] += 1
        p["accounts"][r["account"]] += 1
        if r["origin"]:
            p["origins"][r["origin"]] += 1
        p["uris"].append(r["uri"])
        p["raw"][r["raw"]] += 1
    for p in prof.values():
        p["years"].sort()
        p["y0"], p["y1"] = p["years"][0], p["years"][-1]
    return list(prof.values())


def load_corpus(path):
    from link_hls import split_name
    persons = []
    for p in json.load(open(path, encoding="utf-8")):
        given, surname = split_name(p["n"])
        y = p.get("y")
        if not surname or not given or not y:
            continue
        persons.append({
            "id": p["n"], "name": p["n"], "given": given,
            "forms": surname_forms(surname) | {surname},
            "y0": y[0], "y1": y[1], "ment": p.get("c", 0), "dos": p.get("d", 0),
            "occ": ";".join(p.get("occ", [])[:4]), "street": "", "street_id": "",
            "location": "", "dossiers": ";".join(d[0] for d in p.get("dos", [])[:5]),
        })
    return index_by_prefix(persons)


def load_street(path):
    from link_hls import split_name
    persons = []
    for p in json.load(open(path, encoding="utf-8")):
        given, surname = split_name(p["name"])
        if not given or not surname or not p.get("years"):
            continue
        # every spelling the street-level resolution merged into this person
        forms = set()
        for v in [p["name"]] + p.get("variants", []):
            _, sn = split_name(v)
            if sn:
                forms |= surname_forms(sn) | {sn}
        persons.append({
            "id": p.get("id") or f"{p['street_id']}|{p['name']}", "name": p["name"],
            "given": given, "forms": forms,
            "y0": p["years"][0], "y1": p["years"][1], "ment": p["n"],
            "dos": len(p["dossiers"]), "occ": ";".join(p.get("occ", [])[:4]),
            "street": p.get("street", ""), "street_id": p["street_id"],
            "location": p.get("location", ""), "dossiers": ";".join(p["dossiers"][:5]),
            "roles": ";".join(f"{k}:{v}" for k, v in list(p.get("roles", {}).items())[:4]),
        })
    return index_by_prefix(persons)


def time_fit(p, h, tol):
    """1.0 if every srbas year lies in the HGB span, decaying with the overshoot."""
    lo, hi = h["y0"] - tol, h["y1"] + tol
    if p["y1"] < h["y0"] - tol or p["y0"] > h["y1"] + tol:
        return None
    over = max(0, lo - p["y0"]) + max(0, p["y1"] - hi)
    inside = sum(1 for y in p["years"] if h["y0"] <= y <= h["y1"]) / len(p["years"])
    return round(0.5 + 0.5 * inside - min(over, 20) / 40, 3)


def match(profiles, by_prefix, surname_min, given_min, tol):
    rows, matched = [], 0
    for p in profiles:
        if not p["given_key"] or not p["surname_forms"]:
            continue
        prefixes = {f[:2] for f in p["surname_forms"]}
        seen, cands = set(), []
        for pre in prefixes:
            for h in by_prefix.get(pre, []):
                if h["id"] in seen:
                    continue
                seen.add(h["id"])
                sr = best_surname_ratio(p["surname_forms"], h["forms"], surname_min)
                if sr < surname_min:
                    continue
                gr = given_ratio(p["given_key"], h["given"])
                if gr < given_min:
                    continue
                tf = time_fit(p, h, tol)
                if tf is None:
                    continue
                score = round(0.4 * sr + 0.3 * gr + 0.3 * tf, 3)
                cands.append({
                    "srbas_name": p["raw"].most_common(1)[0][0],
                    "srbas_given": p["given_norm"], "srbas_surname": p["surname_norm"],
                    "srbas_year_min": p["y0"], "srbas_year_max": p["y1"],
                    "srbas_mentions": p["n"],
                    "srbas_accounts": ";".join(a for a, _ in p["accounts"].most_common(3)),
                    "srbas_origin": ";".join(o for o, _ in p["origins"].most_common(2)),
                    "srbas_uri": p["uris"][0],
                    "hgb_id": h["id"], "hgb_name": h["name"],
                    "hgb_year_min": h["y0"], "hgb_year_max": h["y1"],
                    "hgb_mentions": h["ment"], "hgb_dossiers": h["dos"],
                    "hgb_occupations": h["occ"], "hgb_street": h["street"],
                    "hgb_street_id": h["street_id"], "hgb_location": h["location"],
                    "hgb_dossier_ids": h["dossiers"], "hgb_roles": h.get("roles", ""),
                    "surname_score": round(sr, 3), "given_score": round(gr, 3),
                    "time_score": tf, "score": score,
                })
        if not cands:
            continue
        matched += 1
        cands.sort(key=lambda r: -r["score"])
        for c in cands:
            c["n_candidates"] = len(cands)
        rows.extend(cands)
    return rows, matched


COLS = ["srbas_name", "srbas_given", "srbas_surname", "srbas_year_min",
        "srbas_year_max", "srbas_mentions", "srbas_accounts", "srbas_origin",
        "srbas_uri", "hgb_id", "hgb_name", "hgb_year_min", "hgb_year_max",
        "hgb_mentions", "hgb_dossiers", "hgb_occupations", "hgb_street",
        "hgb_street_id", "hgb_location", "hgb_dossier_ids", "hgb_roles",
        "surname_score", "given_score", "time_score", "score", "n_candidates"]


def write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def report(label, rows, matched, n_profiles, path):
    uniq = sum(1 for r in rows if r["n_candidates"] == 1)
    print(f"  {label}: {matched}/{n_profiles} srbas names matched, {len(rows)} "
          f"candidate rows ({uniq} unambiguous) -> {os.path.basename(path)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mentions", default=MENTIONS)
    ap.add_argument("--hgb", default=os.path.join(HERE, "persons_resolved.json"))
    ap.add_argument("--street", default=STREET)
    ap.add_argument("--no-street", action="store_true")
    ap.add_argument("--surname-min", type=float, default=0.85)
    ap.add_argument("--given-min", type=float, default=0.74)
    ap.add_argument("--year-tol", type=int, default=15)
    a = ap.parse_args()

    profiles = load_profiles(a.mentions)
    print(f"srbas name profiles: {len(profiles)} "
          f"({sum(p['n'] for p in profiles)} mentions)")

    print("Corpus target (persons_resolved.json) …")
    rows, matched = match(profiles, load_corpus(a.hgb), a.surname_min, a.given_min, a.year_tol)
    out = os.path.join(HERE, "link_srbas_hgb_candidates.csv")
    write(out, rows)
    report("corpus", rows, matched, len(profiles), out)

    if a.no_street:
        return
    if not os.path.exists(a.street):
        print(f"  street target skipped: {a.street} missing "
              f"(run build_hgb_street_persons.py)")
        return
    print("Street target (hgb_street_persons.json) …")
    rows, matched = match(profiles, load_street(a.street), a.surname_min, a.given_min, a.year_tol)
    out = os.path.join(HERE, "link_srbas_hgb_street_candidates.csv")
    write(out, rows)
    report("street", rows, matched, len(profiles), out)


if __name__ == "__main__":
    main()
