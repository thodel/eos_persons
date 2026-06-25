#!/usr/bin/env python3
"""
gnd_enrich.py — Tier 2: fetch GND records + publications for accepted GND ids.

Input is the union of accepted GND ids from Tier 0 (link_hbls_gnd.csv, date_check
== ok) and Tier 1 (link_hbls_gnd_lobid_candidates.csv, unambiguous). For each
gndIdentifier we fetch the lobid record once (cached) and extract roles, external
ids (sameAs: Wikidata / VIAF / Deutsche Biographie / ISNI), places, biographical
notes and relations; then one lobid-resources query for the person's publications.

Output: hbls-extraction/gnd_enrichment.json keyed by gndIdentifier. See
GND_LINKING_PLAN.md (Tier 2).

    python3 gnd_enrich.py            # all accepted GND ids
    python3 gnd_enrich.py --limit 50
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "hbls-extraction", ".lobid_cache")
OUT = os.path.join(HERE, "hbls-extraction", "gnd_enrichment.json")
UA = ("eos-persons-linker/1.0 "
      "(https://github.com/thodel/eos_persons; tobiashodel@gmail.com)")

# sameAs collection ids we care about -> short key
SAMEAS = {
    "https://www.wikidata.org": "wikidata",
    "http://viaf.org": "viaf",
    "https://www.deutsche-biographie.de": "deutsche_biographie",
    "http://isni.org": "isni",
    "http://id.loc.gov": "lc",
}


def fetch(url, throttle=0.4):
    os.makedirs(CACHE, exist_ok=True)
    key = urllib.parse.quote(url, safe="") + ".json"
    path = os.path.join(CACHE, key[:200])
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            json.dump(data, open(path, "w", encoding="utf-8"))
            time.sleep(throttle)
            return data
        except Exception as e:
            if attempt == 3:
                print(f"    error {url}: {e}")
                return None
            time.sleep(2 + attempt * 3)


def labels(items):
    return [i.get("label") for i in (items or []) if i.get("label")]


def extract_record(rec):
    out = {
        "preferredName": rec.get("preferredName"),
        "dateOfBirth": rec.get("dateOfBirth"),
        "dateOfDeath": rec.get("dateOfDeath"),
        "roles": labels(rec.get("professionOrOccupation")),
        "placeOfBirth": labels(rec.get("placeOfBirth")),
        "placeOfDeath": labels(rec.get("placeOfDeath")),
        "placeOfActivity": labels(rec.get("placeOfActivity")),
        "gender": labels(rec.get("gender")),
        "bio": rec.get("biographicalOrHistoricalInformation"),
    }
    sa = {}
    for s in rec.get("sameAs", []):
        sid = s.get("id", "")
        coll = (s.get("collection") or {}).get("id", "")
        for prefix, key in SAMEAS.items():
            if sid.startswith(prefix) or coll.startswith(prefix):
                sa.setdefault(key, sid)
    out["sameAs"] = sa
    rels = []
    for fld in ("familialRelationship", "relatedPerson", "associatedPlace"):
        for r in rec.get(fld, []):
            if r.get("label"):
                rels.append({"type": fld, "label": r["label"]})
    out["relations"] = rels
    return {k: v for k, v in out.items() if v}


def publications(gnd, size=25):
    url = ("https://lobid.org/resources/search?q="
           + urllib.parse.quote(f'contribution.agent.id:"https://d-nb.info/gnd/{gnd}"')
           + f"&format=json&size={size}")
    data = fetch(url)
    if not data:
        return [], 0
    pubs = []
    for m in data.get("member", []):
        title = m.get("title")
        year = None
        for p in m.get("publication", []):
            y = p.get("startDate") or p.get("publicationYear")
            if y:
                year = str(y)[:4]
                break
        if title:
            pubs.append({"title": title, "year": year})
    return pubs, data.get("totalItems", len(pubs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-publications", action="store_true")
    args = ap.parse_args()

    gnds = {}
    t0 = os.path.join(HERE, "link_hbls_gnd.csv")
    if os.path.exists(t0):
        for r in csv.DictReader(open(t0, encoding="utf-8")):
            if r.get("date_check") == "ok" and r.get("gnd"):
                gnds.setdefault(r["gnd"], set()).add(r["hbls_id"])
    t1 = os.path.join(HERE, "link_hbls_gnd_lobid_candidates.csv")
    if os.path.exists(t1):
        for r in csv.DictReader(open(t1, encoding="utf-8")):
            if r.get("n_candidates") == "1" and r.get("gnd"):
                gnds.setdefault(r["gnd"], set()).add(r["hbls_id"])

    ids = sorted(gnds)
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids)} distinct accepted GND ids to enrich")

    enrich = {}
    for i, g in enumerate(ids, 1):
        rec = fetch(f"https://lobid.org/gnd/{g}.json")
        if not rec:
            continue
        e = extract_record(rec)
        e["hbls_ids"] = sorted(gnds[g])
        if not args.no_publications:
            pubs, total = publications(g)
            if pubs:
                e["publications"] = pubs
                e["n_publications"] = total
        enrich[g] = e
        if i % 100 == 0:
            print(f"  …{i}/{len(ids)} enriched")

    json.dump(enrich, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    nrole = sum(1 for e in enrich.values() if e.get("roles"))
    npub = sum(1 for e in enrich.values() if e.get("publications"))
    nsa = sum(1 for e in enrich.values() if e.get("sameAs"))
    print(f"\nenriched {len(enrich)} GND records -> {OUT}")
    print(f"  with roles: {nrole}  with publications: {npub}  with sameAs: {nsa}")


if __name__ == "__main__":
    main()
