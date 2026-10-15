#!/usr/bin/env python3
"""
freeze_authority_edges.py — keep the HBLS/HLS/GND/Wikidata side of the identity
graph when the HGB side is rebuilt.

Stage 3 (build_identity_clusters.py) unions records over the accepted links of
Stage 1 (HBLS↔HLS), the two GND tiers (HBLS↔GND via Wikidata / lobid) and
Stage 2 (HBLS↔HGB, HGB↔HLS). The candidate CSVs behind the first three are
regenerable only from the HBLS PDF extraction and the private HLS export, which
are not in the repository — but their *result* is: every merged person in
merged_persons.json lists the HBLS, HLS, GND and Wikidata nodes that were
clustered together.

This script writes those non-HGB node groups out as `authority_edges.csv`, one
row per node, grouped by the old cluster. build_identity_clusters.py unions the
rows of a group and so reproduces the authority-side clusters exactly; the HGB
records are then attached afresh from the newly computed Stage 2 / HGB↔HLS
candidates. In other words: the lexicon-and-authority identities are kept, the
land-register links are set again on the new person base.

HGB members are *not* frozen — they are what the rebuild re-derives.

    python3 freeze_authority_edges.py                 # merged_persons.json → authority_edges.csv
    python3 freeze_authority_edges.py --merged old.json
"""
import argparse
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = "authority_edges.csv"
COLS = ["group", "corpus", "node", "name", "birth", "death", "url", "status",
        "conflicts"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", default=os.path.join(HERE, "merged_persons.json"))
    ap.add_argument("--out", default=os.path.join(HERE, OUT))
    ap.add_argument("--hbls-id-map", default=None,
                    help="CSV old_id,new_id from hbls-extraction/rebuild_hbls_persons.py "
                         "(old HBLS ids are rewritten to the rebuilt ones)")
    args = ap.parse_args()

    id_map = {}
    if args.hbls_id_map and os.path.exists(args.hbls_id_map):
        for r in csv.DictReader(open(args.hbls_id_map, encoding="utf-8")):
            if r.get("new_id"):
                id_map[r["old_id"]] = r["new_id"]

    people = json.load(open(args.merged, encoding="utf-8"))
    rows = []
    n_groups = 0
    for p in people:
        prov = p.get("provenance") or {}
        auth = []
        for s in p.get("sources", []):
            c = s["corpus"]
            if c == "hgb":
                continue
            if c == "hbls":
                nid = "hbls:" + id_map.get(s["id"], s["id"])
                name = p.get("name") if prov.get("name") == "hbls" else ""
                b = p.get("birth_year") if prov.get("birth") == "hbls" else None
                d = p.get("death_year") if prov.get("death") == "hbls" else None
            elif c == "hls":
                nid = f"hls:{s['id']}"
                name = s.get("title") or (p.get("name") if prov.get("name") == "hls" else "")
                b = p.get("birth_year") if prov.get("birth") == "hls" else None
                d = p.get("death_year") if prov.get("death") == "hls" else None
            elif c == "gnd":
                nid, name, b, d = f"gnd:{s['id']}", "", None, None
            elif c == "wikidata":
                nid, name, b, d = f"wd:{s['id']}", "", None, None
            else:
                continue
            auth.append({"group": p["id"], "corpus": c, "node": nid, "name": name or "",
                         "birth": b or "", "death": d or "", "url": s.get("url") or "",
                         "status": p.get("status"),
                         "conflicts": "|".join(p.get("conflicts") or [])})
        if auth:
            n_groups += 1
            rows.extend(auth)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    by_c = {}
    for r in rows:
        by_c[r["corpus"]] = by_c.get(r["corpus"], 0) + 1
    print(f"→ {args.out}: {len(rows)} authority nodes in {n_groups} groups "
          f"({', '.join(f'{k} {v}' for k, v in sorted(by_c.items()))}; "
          f"{len(id_map)} HBLS ids remapped)")


if __name__ == "__main__":
    main()
