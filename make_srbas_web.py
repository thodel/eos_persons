#!/usr/bin/env python3
"""
make_srbas_web.py — compact web payload for the Jahrrechnungen tab.

Joins the srbas side (srbas-extraction/srbas_name_mentions.csv, the booking
texts in srbas-extraction/srbas_entries.jsonl, srbas_account_places.csv) with
the two HGB candidate tables (link_srbas_hgb_candidates.csv,
link_srbas_hgb_street_candidates.csv) into one JSON that jahrrechnungen.html
renders: one record per srbas name profile with up to BOOKINGS cited
bookings (year, account, GAMS fragment URI, short text excerpt) and up to
CANDS best HGB candidates per target, street candidates with WGS84 points
(LV95 converted with the same approximation movements.html uses).

    python3 make_srbas_web.py        # -> srbas_web.json (tracked)

Short keys keep the payload small; see jahrrechnungen.html for the reader.
"""
import collections
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRB = os.path.join(HERE, "srbas-extraction")
OUT = os.path.join(HERE, "srbas_web.json")
BOOKINGS = 4
CANDS = 3
EXCERPT = 140
csv.field_size_limit(10_000_000)


def lv95_to_wgs84(E, N):
    y = (E - 2_600_000) / 1_000_000
    x = (N - 1_200_000) / 1_000_000
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return round(lat * 100 / 36, 6), round(lon * 100 / 36, 6)


def point(wkt):
    m = re.match(r"POINT\(([\d.]+) ([\d.]+)\)", wkt or "")
    return lv95_to_wgs84(float(m.group(1)), float(m.group(2))) if m else (None, None)


def excerpt(text):
    t = " ".join(text.split())
    return t if len(t) <= EXCERPT else t[:EXCERPT].rsplit(" ", 1)[0] + " …"


def load_entries():
    """entry_id -> (text excerpt); account -> booking count. Optional input."""
    path = os.path.join(SRB, "srbas_entries.jsonl")
    texts, per_account = {}, collections.Counter()
    if not os.path.exists(path):
        print("  (srbas_entries.jsonl missing: no text excerpts, no booking counts)")
        return texts, per_account
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["kind"] != "bk_entry":
            continue
        texts[(r["pid"], r["entry_id"])] = excerpt(r["text"])
        per_account[r["account"]] += 1
    return texts, per_account


def load_candidates(path, kind):
    by_profile = collections.defaultdict(list)
    if not os.path.exists(path):
        return by_profile
    for r in csv.DictReader(open(path, encoding="utf-8")):
        key = (r["srbas_given"], r["srbas_surname"])
        c = {
            "t": kind, "n": r["hgb_name"], "y": [int(r["hgb_year_min"]), int(r["hgb_year_max"])],
            "c": int(r["hgb_mentions"]), "d": int(r["hgb_dossiers"]),
            "occ": [o for o in r["hgb_occupations"].split(";") if o][:3],
            "sc": float(r["score"]), "amb": int(r["n_candidates"]),
        }
        if kind == "street":
            lat, lon = point(r["hgb_location"])
            c.update({"st": r["hgb_street"], "sid": r["hgb_id"], "lat": lat, "lon": lon,
                      "dos": [d for d in r["hgb_dossier_ids"].split(";") if d][:3],
                      "roles": [x for x in r["hgb_roles"].split(";") if x][:3]})
        by_profile[key].append(c)
    for key, cs in by_profile.items():
        cs.sort(key=lambda c: -c["sc"])
        by_profile[key] = cs[:CANDS]
    return by_profile


def main():
    texts, per_account = load_entries()
    corpus = load_candidates(os.path.join(HERE, "link_srbas_hgb_candidates.csv"), "corpus")
    street = load_candidates(os.path.join(HERE, "link_srbas_hgb_street_candidates.csv"), "street")

    # srbas name profiles with their bookings
    prof = {}
    n_mentions = 0
    for r in csv.DictReader(open(os.path.join(SRB, "srbas_name_mentions.csv"), encoding="utf-8")):
        n_mentions += 1
        key = (r["given_norm"], r["surname_norm"])
        p = prof.setdefault(key, {"raw": collections.Counter(), "years": [], "acc": collections.Counter(),
                                  "orig": collections.Counter(), "b": []})
        p["raw"][r["raw"]] += 1
        p["years"].append(int(r["year"]))
        p["acc"][r["account"]] += 1
        if r["origin"]:
            p["orig"][r["origin"]] += 1
        p["b"].append({"y": int(r["year"]), "a": r["account"], "u": r["uri"],
                       "t": texts.get((r["pid"], r["entry_id"]), "")})
    profiles = []
    for key, p in prof.items():
        bookings = sorted(p["b"], key=lambda b: b["y"])
        # spread the cited bookings over the years rather than taking the first N
        step = max(1, len(bookings) // BOOKINGS)
        cited = bookings[::step][:BOOKINGS]
        cands = street.get(key, []) + corpus.get(key, [])
        profiles.append({
            "n": p["raw"].most_common(1)[0][0], "g": key[0], "s": key[1],
            "y": [min(p["years"]), max(p["years"])], "c": len(p["years"]),
            "acc": [a for a, _ in p["acc"].most_common(4)],
            "o": [o for o, _ in p["orig"].most_common(2)],
            "b": cited, "k": cands,
            "best": max((c["sc"] for c in cands), default=0),
            "uniq": any(c["amb"] == 1 for c in cands),
        })
    profiles.sort(key=lambda p: (-p["c"], p["s"], p["g"]))

    # bailiwick accounts, one marker per geocoded place
    places = {}
    for r in csv.DictReader(open(os.path.join(SRB, "srbas_account_places.csv"), encoding="utf-8")):
        if not r["lat"]:
            continue
        pl = places.setdefault(r["place"], {"p": r["place"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                                            "wd": r["wikidata"], "status": r["status"], "acc": [], "n": 0})
        pl["acc"].append(r["account_id"])
        pl["n"] += per_account.get(r["account_id"], 0)
        if r["status"] == "auto":
            pl["status"] = "auto"
    accounts = sorted(places.values(), key=lambda a: -a["n"])

    # account id -> label from the taxonomy, for the chips
    labels = {}
    kont = os.path.join(SRB, "tei", "o_srbas.konten.xml")
    if os.path.exists(kont):
        import xml.etree.ElementTree as ET
        T = "{http://www.tei-c.org/ns/1.0}"
        for cat in ET.parse(kont).getroot().iter(T + "category"):
            xid = cat.get("{http://www.w3.org/XML/1998/namespace}id")
            name = cat.find("./" + T + "catDesc/" + T + "name")
            if xid and name is not None:
                labels[xid] = " ".join(name.itertext()).strip()

    stats = {
        "bookings": sum(per_account.values()), "mentions": n_mentions, "profiles": len(profiles),
        "matched_street": sum(1 for p in profiles if any(c["t"] == "street" for c in p["k"])),
        "matched_corpus": sum(1 for p in profiles if any(c["t"] == "corpus" for c in p["k"])),
        "unambiguous": sum(1 for p in profiles if p["uniq"]),
        "places": len(accounts), "places_auto": sum(1 for a in accounts if a["status"] == "auto"),
    }
    out = {"stats": stats, "accounts": accounts, "labels": labels, "profiles": profiles}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(profiles)} profiles, {len(accounts)} places -> {OUT} "
          f"({os.path.getsize(OUT) / 1e6:.1f} MB)")
    print(stats)


if __name__ == "__main__":
    main()
