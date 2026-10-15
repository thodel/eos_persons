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
import gzip
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "hbls-extraction", ".lobid_cache")
OUT = os.path.join(HERE, "hbls-extraction", "gnd_enrichment.json")
UA = ("eos-persons-linker/1.0 "
      "(https://github.com/thodel/eos_persons; tobias.hodel@unibe.ch)")

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


def load_records(paths, wanted):
    """gndIdentifier -> full record, read from lobid JSON-lines bulk dumps.

    The dumps already downloaded for Tier 1 (see GND_LINKING_PLAN.md) carry the
    complete record — professionOrOccupation, sameAs, places, bio prose,
    relations — so the per-id API fetch is only needed for accepted ids that
    fall outside both dump slices (Tier 0 ids arrive via Wikidata and can be
    any GND). Publications still come from the separate lobid-resources index.

    Only `wanted` ids are retained, so memory stays proportional to the
    accepted set rather than to the ~1.1M records on disk.
    """
    out = {}
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                g = rec.get("gndIdentifier")
                if g in wanted and g not in out:
                    out[g] = rec
    return out


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
    ap.add_argument("--pubs-fallback", default=os.path.join(HERE, "merged_persons.json"),
                    help="when publications are not fetched (flag above, or the "
                         "lobid-resources index is unreachable), keep the ones a "
                         "previous merged_persons.json recorded for the same GND id")
    ap.add_argument("--dump", default="",
                    help="comma-separated lobid JSON-lines dumps to read GND "
                         "records from instead of one API fetch per id")
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

    # Frozen authority clusters (freeze_authority_edges.py) carry the accepted
    # GND ids too — the only source when the Tier 0/1 candidate CSVs (which need
    # the private HBLS/HLS inputs) are not present.
    fz = os.path.join(HERE, "authority_edges.csv")
    if not gnds and os.path.exists(fz):
        groups = {}
        for r in csv.DictReader(open(fz, encoding="utf-8")):
            groups.setdefault(r["group"], []).append(r)
        for rows in groups.values():
            hb = {r["node"][5:] for r in rows if r["corpus"] == "hbls"}
            for r in rows:
                if r["corpus"] == "gnd":
                    gnds.setdefault(r["node"][4:], set()).update(hb)
        print(f"GND ids taken from {os.path.basename(fz)}")

    ids = sorted(gnds)
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids)} distinct accepted GND ids to enrich")

    from_dump = {}
    if args.dump:
        paths = [p if os.path.isabs(p) else os.path.join(HERE, p)
                 for p in (s.strip() for s in args.dump.split(",")) if p]
        print(f"reading GND records from {', '.join(os.path.basename(p) for p in paths)} …")
        from_dump = load_records(paths, set(ids))
        print(f"  {len(from_dump)}/{len(ids)} ids served from the dump; "
              f"{len(ids) - len(from_dump)} need an API fetch")

    # publications recorded on a previous run, by GND id (lobid-resources sits
    # behind a bot challenge at times; the GND record endpoint does not)
    old_pubs = {}
    if args.pubs_fallback and os.path.exists(args.pubs_fallback):
        for p in json.load(open(args.pubs_fallback, encoding="utf-8")):
            for g in (p.get("authority") or {}).get("gnd", []):
                if p.get("publications"):
                    old_pubs.setdefault(g, p["publications"])
        print(f"{len(old_pubs)} GND ids with publications from {os.path.basename(args.pubs_fallback)}")

    enrich = {}
    n_api = 0
    for i, g in enumerate(ids, 1):
        rec = from_dump.get(g)
        if rec is None:
            rec = fetch(f"https://lobid.org/gnd/{g}.json")
            n_api += 1
        if not rec:
            continue
        e = extract_record(rec)
        e["hbls_ids"] = sorted(gnds[g])
        if not args.no_publications:
            pubs, total = publications(g)
            if pubs:
                e["publications"] = pubs
                e["n_publications"] = total
        if "publications" not in e and g in old_pubs:
            e["publications"] = old_pubs[g]
            e["n_publications"] = len(old_pubs[g])
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
    print(f"  record fetches that hit the API: {n_api}")


if __name__ == "__main__":
    main()
