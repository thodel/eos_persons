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

Splitting. On the raw index (build_data.py's mention lists still belong to it)
link_hls.py checks the life mention by mention, and a biography can be the
winner although only part of the person's mentions fit it: somebody of that
name acts before the person is of age, or after the death. Such a person is
taken apart here (lifedates.partition): the mentions of the life keep the
link, the earlier and the later ones become persons of their own — the
same-named father, son or grandson. What was split, and on what evidence, is
appended to hls_life_splits.csv. link_hls.py and this script are run in turn
until nothing splits any more (rebuild.sh), because a part split off may fit
another biography.
"""
import os
import re
import csv
import json
import argparse
import collections

csv.field_size_limit(10_000_000)

import lifedates  # noqa: E402
from link_hls import default_hls  # noqa: E402

MIN_SCORE = 0.90
MARGIN = 0.05
SPLITS = "hls_life_splits.csv"
SPLIT_COLS = ["person", "years", "mentions", "hls_id", "hls_title", "hls_birth",
              "birth_kind", "hls_death", "death_kind", "life", "conflicts",
              "kept", "earlier", "later"]


def hls_url(article_id, version):
    if version:
        return f"https://hls-dhs-dss.ch/de/articles/{article_id}/{version}/"
    return f"https://hls-dhs-dss.ch/de/articles/{article_id}/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="link_candidates_hls.csv")
    ap.add_argument("--hls", default=default_hls())
    ap.add_argument("--persons", default="persons_resolved.json")
    ap.add_argument("--graph", default="families_graph.json")
    ap.add_argument("--splits", default=SPLITS)
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--margin", type=float, default=MARGIN)
    args = ap.parse_args()

    # id -> version (for the dated online URL)
    print("Reading HLS versions …")
    version_of = {}
    with open(args.hls, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            version_of[row["id"]] = (row.get("version") or "").strip()

    persons = json.load(open(args.persons, encoding="utf-8"))

    # group candidates per HGB person (position in the index, checked by key)
    print("Selecting confident links …")
    groups = collections.defaultdict(list)
    stale = 0
    with open(args.candidates, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            i = int(r["hgb_idx"])
            p = persons[i] if i < len(persons) else None
            if not p or (p["n"], str(p["y"][0]), str(p["y"][1])) != \
                    (r["hgb_name"], r["hgb_year_min"], r["hgb_year_max"]):
                stale += 1
                continue
            groups[i].append(r)
    if stale:
        raise SystemExit(f"{stale} candidates do not fit {args.persons} — re-run link_hls.py")

    accepted = {}   # person position -> (hls payload, candidate row)
    for i, cands in groups.items():
        cands.sort(key=lambda r: -float(r["rank_score"]))
        top = cands[0]
        if float(top["score"]) < args.min_score:
            continue
        if len(cands) > 1:
            margin = float(top["rank_score"]) - float(cands[1]["rank_score"])
            if margin < args.margin:
                continue          # ambiguous — skip
        ver = version_of.get(top["hls_id"], top.get("hls_version", ""))
        link = {
            "id": top["hls_id"],
            "url": hls_url(top["hls_id"], ver),
            "t": top["hls_title"],
            "rel": top["date_relation"],
        }
        # the article's life dates, and the bounds they and Wikidata set
        # (lifedates.bounds): the dedupe passes keep a linked person inside them
        for fld, col in (("b", "hls_birth"), ("d", "hls_death")):
            if (top.get(col) or "").strip().lstrip("-").isdigit():
                link[fld] = int(top[col])
        for fld, col in (("bk", "hls_birth_kind"), ("dk", "hls_death_kind")):
            if top.get(col) and top[col] != "exact":
                link[fld] = top[col]              # "circa", "first_mention", …
        link["life"] = [int(x) for x in top["life"].split("|")]
        accepted[i] = (link, top)

    print(f"  {len(accepted)} confident links "
          f"(from {len(groups)} candidate persons)")

    # ── patch persons_resolved.json ──
    # Clear first, then set: this script used to only ever *set* `hls`, so a
    # link that stopped being accepted (candidates regenerated, thresholds
    # changed) stayed baked in forever. `wd` and `kin` are derived from `hls`
    # by enrich_wikidata.py / link_wikidata_kin.py, so they have to go with it
    # — otherwise a stale GND id keeps feeding Stage 3, which treats a shared
    # authority id as its strongest merge signal. Re-run those two scripts
    # afterwards to rebuild the enrichment from the surviving links.
    import build_data                              # pandas: for the mention lists
    side = build_data.read_rows(persons)
    rows = None
    if side is not None and any(int(c["n_early"]) or int(c["n_late"])
                                for _, c in accepted.values()):
        import pandas as pd
        rows = build_data.prepare_rows(pd.read_csv(build_data.INPUT_CSV))

    out, split_rows = [], []
    n_p = n_cleared = n_split = 0
    for i, p in enumerate(persons):
        if side is not None:
            p["_rows"] = side[i]
        if i not in accepted:
            if p.get("hls"):
                for field in ("hls", "wd", "kin"):
                    p.pop(field, None)
                n_cleared += 1
            out.append(p)
            continue
        link, cand = accepted[i]
        n_p += 1
        if rows is None or not (int(cand["n_early"]) or int(cand["n_late"])):
            if (p.get("hls") or {}).get("id") != link["id"]:
                p.pop("wd", None); p.pop("kin", None)
            p["hls"] = link
            out.append(p)
            continue
        # part of the mentions lie outside the life: take the person apart
        life = lifedates.Life(*link["life"])
        idx = [j for _, js in side[i] for j in js if rows[j]["_year"]]
        labels, _ = lifedates.partition(
            life, [(rows[j]["_year"], rows[j]["_dead"], rows[j]["_strong"], rows[j]["_past"])
                   for j in idx])
        lab = dict(zip(idx, labels))
        parts = build_data.split_person(side[i], rows, lambda r: lab.get(r["_i"], "F"))
        parts["F"]["hls"] = link
        n_split += 1

        def span(q):
            return f"{q['y'][0]}–{q['y'][1]} ×{q['c']}" if q else ""
        split_rows.append({
            "person": p["n"], "years": f"{p['y'][0]}–{p['y'][1]}", "mentions": p["c"],
            "hls_id": link["id"], "hls_title": link["t"],
            "hls_birth": link.get("b", ""), "birth_kind": link.get("bk", "exact"),
            "hls_death": link.get("d", ""), "death_kind": link.get("dk", "exact"),
            "life": cand["life"], "conflicts": cand["conflicts"],
            "kept": span(parts["F"]), "earlier": span(parts.get("E")),
            "later": span(parts.get("L"))})
        out.extend(parts[k] for k in ("F", "E", "L") if k in parts)

    if split_rows:
        new = not os.path.exists(args.splits)
        with open(args.splits, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SPLIT_COLS)
            if new:
                w.writeheader()
            w.writerows(split_rows)
    out.sort(key=lambda p: -p.get("c", 0))
    if side is not None:
        build_data.write_index(out, args.persons)
    else:
        json.dump(out, open(args.persons, "w", encoding="utf-8"),
                  separators=(",", ":"), ensure_ascii=False)
    print(f"  persons_resolved.json: linked {n_p} persons, "
          f"cleared {n_cleared} no longer supported")
    print(f"  split {n_split} persons whose mentions reach outside the life "
          f"→ {len(out)} persons" + (f"; see {args.splits}" if n_split else ""))

    # ── patch families_graph.json nodes ──
    by_key = {(p["n"], str(p["y"][0]), str(p["y"][1])): p["hls"] for p in out if p.get("hls")}

    def key_of(name, y):
        return (name, str(y[0]), str(y[1])) if y else None

    if os.path.exists(args.graph):
        graph = json.load(open(args.graph, encoding="utf-8"))
        n_n = n_n_cleared = 0
        for node in graph.get("nodes", []):
            k = key_of(node.get("name"), node.get("y"))
            if k and k in by_key:
                node["hls"] = by_key[k]
                n_n += 1
            elif node.get("hls"):
                node.pop("hls", None)
                n_n_cleared += 1
        json.dump(graph, open(args.graph, "w", encoding="utf-8"),
                  separators=(",", ":"), ensure_ascii=False)
        print(f"  families_graph.json: linked {n_n} nodes, "
              f"cleared {n_n_cleared} no longer supported")

    # report a few
    print("\nExamples:")
    for k, v in list(by_key.items())[:10]:
        print(f"  {k[0]} [{k[1]}–{k[2]}] → {v['t']} ({v['rel']}) {v['url']}")


if __name__ == "__main__":
    main()
