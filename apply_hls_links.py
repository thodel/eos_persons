#!/usr/bin/env python3
"""
apply_hls_links.py — write confident HGB↔HLS links into the site data.

Reads link_candidates_hls.csv (from link_hls.py) and keeps only the
unambiguous, high-confidence candidates, then attaches an `hls` field to the
matching persons in persons_resolved.json and to the matching nodes in
families_graph.json. The link uses the online HLS pattern with the article
version date:  https://hls-dhs-dss.ch/de/articles/<id>/<version>/

A person is linked only when its single best candidate is clearly the winner:
    • rank 1 and score ≥ MIN_SCORE, and
    • either the only candidate, or ahead of the runner-up by ≥ MARGIN.
Ambiguous many-to-one cases are left unlinked on purpose.
"""
import re
import csv
import json
import argparse
import collections

csv.field_size_limit(10_000_000)

MIN_SCORE = 0.90
MARGIN = 0.05


def hls_url(article_id, version):
    if version:
        return f"https://hls-dhs-dss.ch/de/articles/{article_id}/{version}/"
    return f"https://hls-dhs-dss.ch/de/articles/{article_id}/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="link_candidates_hls.csv")
    ap.add_argument("--hls", default="/Users/TH_1/Documents/HLS/hls_articles.csv")
    ap.add_argument("--persons", default="persons_resolved.json")
    ap.add_argument("--graph", default="families_graph.json")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--margin", type=float, default=MARGIN)
    args = ap.parse_args()

    # id -> version (for the dated online URL)
    print("Reading HLS versions …")
    version_of = {}
    with open(args.hls, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            version_of[row["id"]] = (row.get("version") or "").strip()

    # group candidates per HGB person key = (name, ymin, ymax)
    print("Selecting confident links …")
    groups = collections.defaultdict(list)
    with open(args.candidates, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["hgb_name"], r["hgb_year_min"], r["hgb_year_max"])
            groups[key].append(r)

    accepted = {}   # key -> hls payload
    for key, cands in groups.items():
        cands.sort(key=lambda r: -float(r["score"]))
        top = cands[0]
        if float(top["score"]) < args.min_score:
            continue
        if len(cands) > 1:
            margin = float(top["score"]) - float(cands[1]["score"])
            if margin < args.margin:
                continue          # ambiguous — skip
        ver = version_of.get(top["hls_id"], top.get("hls_version", ""))
        accepted[key] = {
            "id": top["hls_id"],
            "url": hls_url(top["hls_id"], ver),
            "t": top["hls_title"],
            "rel": top["date_relation"],
        }

    print(f"  {len(accepted)} confident links "
          f"(from {len(groups)} candidate persons)")

    def key_of(name, y):
        return (name, str(y[0]), str(y[1])) if y else None

    # ── patch persons_resolved.json ──
    persons = json.load(open(args.persons, encoding="utf-8"))
    n_p = 0
    for p in persons:
        k = key_of(p["n"], p.get("y"))
        if k and k in accepted:
            p["hls"] = accepted[k]
            n_p += 1
    json.dump(persons, open(args.persons, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  persons_resolved.json: linked {n_p} persons")

    # ── patch families_graph.json nodes ──
    graph = json.load(open(args.graph, encoding="utf-8"))
    n_n = 0
    for node in graph.get("nodes", []):
        k = key_of(node.get("name"), node.get("y"))
        if k and k in accepted:
            node["hls"] = accepted[k]
            n_n += 1
    json.dump(graph, open(args.graph, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  families_graph.json: linked {n_n} nodes")

    # report a few
    print("\nExamples:")
    for k, v in list(accepted.items())[:10]:
        print(f"  {k[0]} [{k[1]}–{k[2]}] → {v['t']} ({v['rel']}) {v['url']}")


if __name__ == "__main__":
    main()
