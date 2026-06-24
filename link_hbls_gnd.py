#!/usr/bin/env python3
"""
link_hbls_gnd.py — Tier 0 GND linking: HBLS → HLS → Wikidata → GND.

The cheapest, highest-precision GND links need no lobid traffic at all: Wikidata
stores the HLS article id as P902 and the GND id as P227, so our Stage-1 HBLS↔HLS
links (link_hbls_hls_candidates.csv) bridge straight to GND. For every linked HLS
id we run one batched WDQS query and read back the Wikidata QID, GND (P227), VIAF
(P214), Wikidata birth/death (P569/P570) and occupations (P106).

The Wikidata life dates also CROSS-VALIDATE the HBLS↔HLS chain: if they disagree
with the HBLS person's dates, the underlying HLS link is suspect (flagged, not
dropped). See hbls-extraction/GND_LINKING_PLAN.md (Tier 0).

    python3 link_hbls_gnd.py                 # all HBLS↔HLS candidates
    python3 link_hbls_gnd.py --min-score 0.9 # only strong HLS links
    python3 link_hbls_gnd.py --basel         # restrict to the Basel slice

Lobid (Tier 1) is a separate later script; this one only touches WDQS.
"""
import argparse
import csv
import json
import os

# reuse the WDQS plumbing (request + 429 backoff) and year parser
from enrich_wikidata import run_sparql, year

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK = 480  # HLS ids per WDQS query (WDQS is rate-limited; keep requests few)

QUERY = """
SELECT ?hls ?item ?gnd ?viaf ?birth ?death
  (GROUP_CONCAT(DISTINCT ?occL; separator="|") AS ?occs)
WHERE {
  VALUES ?hls { %s }
  ?item wdt:P902 ?hls.
  OPTIONAL { ?item wdt:P227 ?gnd. }
  OPTIONAL { ?item wdt:P214 ?viaf. }
  OPTIONAL { ?item wdt:P569 ?birth. }
  OPTIONAL { ?item wdt:P570 ?death. }
  OPTIONAL { ?item wdt:P106 ?occ. ?occ rdfs:label ?occL. FILTER(lang(?occL) = "de") }
}
GROUP BY ?hls ?item ?gnd ?viaf ?birth ?death
"""


def date_check(hb, hd, wb, wd):
    """Agreement between HBLS (hb,hd) and Wikidata (wb,wd) life dates."""
    for a, b in ((hb, wb), (hd, wd)):
        if a and b and abs(a - b) > 5:
            return "MISMATCH"
    if (hb and wb) or (hd and wd):
        return "ok"
    return "unchecked"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", default="link_hbls_hls_candidates.csv")
    ap.add_argument("--basel", action="store_true",
                    help="restrict to the Basel HBLS slice")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="only follow HBLS↔HLS links at/above this score")
    ap.add_argument("--out", default="link_hbls_gnd.csv")
    args = ap.parse_args()

    links = list(csv.DictReader(open(os.path.join(HERE, args.links),
                                     encoding="utf-8")))
    links = [r for r in links if float(r["score"]) >= args.min_score]

    if args.basel:
        basel_ids = {p["id"] for p in json.load(open(os.path.join(
            HERE, "hbls-extraction", "hbls_persons_basel.json"), encoding="utf-8"))}
        links = [r for r in links if r["hbls_id"] in basel_ids]

    hls_ids = sorted({r["hls_id"] for r in links})
    print(f"{len(links)} HBLS↔HLS links over {len(hls_ids)} distinct HLS ids "
          f"-> querying Wikidata for GND")

    facts = {}
    for i in range(0, len(hls_ids), CHUNK):
        chunk = hls_ids[i:i + CHUNK]
        values = " ".join(f'"{h}"' for h in chunk)
        for r in run_sparql(QUERY % values):
            hid = r["hls"]["value"]
            f = {"qid": r["item"]["value"].rsplit("/", 1)[-1]}
            if r.get("gnd"):
                f["gnd"] = r["gnd"]["value"]
            if r.get("viaf"):
                f["viaf"] = r["viaf"]["value"]
            if r.get("birth"):
                f["b"] = year(r["birth"]["value"])
            if r.get("death"):
                f["d"] = year(r["death"]["value"])
            if r.get("occs", {}).get("value"):
                f["occ"] = [o for o in r["occs"]["value"].split("|") if o]
            facts[hid] = f
        print(f"  …{min(i + CHUNK, len(hls_ids))}/{len(hls_ids)} ids, "
              f"{len(facts)} Wikidata items, "
              f"{sum(1 for v in facts.values() if 'gnd' in v)} with GND")

    rows = []
    for r in links:
        f = facts.get(r["hls_id"])
        if not f or "gnd" not in f:
            continue
        hb = int(r["hbls_birth"]) if r["hbls_birth"] else None
        hd = int(r["hbls_death"]) if r["hbls_death"] else None
        rows.append({
            "hbls_id": r["hbls_id"], "hbls_name": r["hbls_name"],
            "hbls_birth": r["hbls_birth"], "hbls_death": r["hbls_death"],
            "via_hls_id": r["hls_id"], "hbls_hls_score": r["score"],
            "hbls_hls_ambig": r.get("n_candidates", ""),
            "wikidata_qid": f["qid"],
            "gnd": f["gnd"], "gnd_url": f"https://d-nb.info/gnd/{f['gnd']}",
            "viaf": f.get("viaf", ""),
            "wd_birth": f.get("b", ""), "wd_death": f.get("d", ""),
            "wd_occupations": "|".join(f.get("occ", [])),
            "date_check": date_check(hb, hd, f.get("b"), f.get("d")),
        })

    cols = ["hbls_id", "hbls_name", "hbls_birth", "hbls_death", "via_hls_id",
            "hbls_hls_score", "hbls_hls_ambig", "wikidata_qid", "gnd", "gnd_url",
            "viaf", "wd_birth", "wd_death", "wd_occupations", "date_check"]
    with open(os.path.join(HERE, args.out), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    persons = len({r["hbls_id"] for r in rows})
    ok = sum(1 for r in rows if r["date_check"] == "ok")
    bad = sum(1 for r in rows if r["date_check"] == "MISMATCH")
    print(f"\n{len(rows)} GND links for {persons} HBLS persons -> {args.out}")
    print(f"  date cross-check: {ok} ok, {bad} mismatch (suspect HLS link)")


if __name__ == "__main__":
    main()
