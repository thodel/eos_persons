#!/usr/bin/env python3
"""
build_dossiers_geo.py — dossiers_geo.json for map.html.

One feature per geolocated dossier (property) with WGS84 coordinates, document
count, year range, archival sources and the persons resolved to it:

  { "type": "dossier_geo",
    "features": [ { "id", "lat", "lon", "year_min", "year_max", "sources",
                    "n_docs", "n_persons",
                    "persons": [ {"n", "c", "y", "occ"}, … ]   # top mentions
                  }, … ] }

Inputs: dossiers.csv (extract_persons.py — LV95 point, doc count, years,
sources per dossier) and persons_resolved.json (the deduplicated person index;
each person lists the dossiers it was resolved in).

    python3 build_dossiers_geo.py
"""
import collections
import csv
import json

import hgb_corpus

DOSSIERS = "dossiers.csv"
PERSONS = "persons_resolved.json"
OUT = "dossiers_geo.json"
TOP_PERSONS = 8


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))
    by_dossier = collections.defaultdict(dict)       # dossier -> {person idx: ...}
    for p in persons:
        for e in p.get("dos", []):
            did = e[0] if isinstance(e, list) else e
            if did:
                by_dossier[did][id(p)] = p

    feats = []
    n_skipped = 0
    with open(DOSSIERS, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            E, N = hgb_corpus.parse_point(row.get("location"))
            if E is None:
                n_skipped += 1
                continue
            lat, lon = hgb_corpus.lv95_to_wgs84(E, N)
            pers = list(by_dossier.get(row["dossierid"], {}).values())
            pers.sort(key=lambda p: -p.get("c", 0))
            feats.append({
                "id": row["dossierid"],
                "lat": round(lat, 6), "lon": round(lon, 6),
                "street": row.get("street_name") or None,
                "address": row.get("address") or None,
                "type": row.get("dossiertype") or None,
                "year_min": int(row["year_min"]) if row.get("year_min") else None,
                "year_max": int(row["year_max"]) if row.get("year_max") else None,
                "sources": [s for s in (row.get("sources") or "").split(";") if s],
                "n_docs": int(row["n_docs"] or 0),
                "n_persons": len(pers),
                "persons": [{"n": p["n"], "c": p.get("c", 0), "y": p.get("y"),
                             "occ": p.get("occ", [])[:4]} for p in pers[:TOP_PERSONS]],
            })
    feats.sort(key=lambda f: f["id"])
    json.dump({"type": "dossier_geo", "features": feats},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"→ {OUT}: {len(feats)} geolocated dossiers "
          f"({n_skipped} without coordinates skipped), "
          f"{sum(f['n_persons'] for f in feats)} person–dossier links")


if __name__ == "__main__":
    main()
