#!/usr/bin/env python3
"""
dedupe_rare_surnames.py — merge same-named persons across dossiers when the
surname is rare.

dedupe_corpus required a shared dossier/occupation/location to merge — the
precision gate against common-name collisions. For *rare, distinctive*
surnames that gate is unnecessary: a surname carried by only a handful of
people, combined with the same canonical given name and a one-lifespan window,
identifies one individual even when the two mentions sit in different
properties. This pass picks up exactly those cross-dossier duplicates.

Guards: phonetic-surname bearers ≤ RARE; same canonical given-name sequence;
raw surnames ≥ 0.7 similar; merged span ≤ 80 yr; never merges two different
confirmed HLS/Wikidata identities.

    python3 dedupe_rare_surnames.py            # dry run + CSV
    python3 dedupe_rare_surnames.py --apply
"""
import json
import csv
import argparse
import collections
from difflib import SequenceMatcher

from dedupe_corpus import (koelner, given_seq, surname_raw, link_key, merge_cluster)

PERSONS = "persons_resolved.json"
MAXLIFE = 80
RARE = 6          # phonetic-surname bearers at or below this are "rare"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default="dedupe_rare_candidates.csv")
    ap.add_argument("--rare", type=int, default=RARE)
    args = ap.parse_args()

    persons = json.load(open(PERSONS, encoding="utf-8"))

    # phonetic-surname frequency over surnamed persons (variants count together)
    kp_of, gs_of, surn_of = {}, {}, {}
    freq = collections.Counter()
    for i, p in enumerate(persons):
        sr = surname_raw(p["n"])
        if not sr:
            continue
        kp = koelner(sr)
        kp_of[i] = kp; surn_of[i] = sr; gs_of[i] = given_seq(p["n"])
        freq[kp] += 1

    # block by (phonetic surname, given-name sequence)
    blocks = collections.defaultdict(list)
    for i in kp_of:
        blocks[(kp_of[i], gs_of[i])].append(i)

    parent = {i: i for i in kp_of}
    grp = {i: {"y0": (persons[i].get("y") or [None])[0],
               "y1": (persons[i].get("y") or [None, None])[1],
               "lk": link_key(persons[i])} for i in kp_of}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x

    def try_union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if grp[ra]["lk"] and grp[rb]["lk"] and grp[ra]["lk"] != grp[rb]["lk"]:
            return
        ya0, ya1, yb0, yb1 = grp[ra]["y0"], grp[ra]["y1"], grp[rb]["y0"], grp[rb]["y1"]
        if None in (ya0, ya1, yb0, yb1):
            return
        lo, hi = min(ya0, yb0), max(ya1, yb1)
        if hi - lo > MAXLIFE:
            return
        sa, sb = surn_of[a], surn_of[b]
        if sa != sb and SequenceMatcher(None, sa, sb).ratio() < 0.7:
            return
        parent[ra] = rb
        grp[rb] = {"y0": lo, "y1": hi, "lk": grp[ra]["lk"] or grp[rb]["lk"]}

    n_pairs = 0
    for (kp, gs), idxs in blocks.items():
        if len(idxs) < 2 or freq[kp] > args.rare:
            continue
        for k in range(1, len(idxs)):
            before = find(idxs[0])
            try_union(idxs[0], idxs[k])
            if find(idxs[0]) != before or find(idxs[k]) == find(idxs[0]):
                n_pairs += 1

    clusters = collections.defaultdict(list)
    for i in kp_of:
        clusters[find(i)].append(i)
    merges = [v for v in clusters.values() if len(v) > 1]
    collapsed = sum(len(v) - 1 for v in merges)
    print(f"persons: {len(persons)}")
    print(f"rare-surname merge clusters: {len(merges)}  (collapsing {collapsed} duplicates "
          f"→ {len(persons) - collapsed})")

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster", "n", "canonical", "year_range", "surname_bearers", "variants"])
        for ci, v in enumerate(sorted(merges, key=lambda s: -len(s))):
            ms = [persons[i] for i in v]
            m = merge_cluster(ms)
            w.writerow([ci, len(v), m["n"],
                        f"{m['y'][0]}–{m['y'][1]}" if m.get("y") else "?",
                        freq[kp_of[v[0]]],
                        " | ".join(sorted({p["n"] for p in ms}))])
    print(f"wrote {args.csv}")
    print("\nSample merges:")
    for v in sorted(merges, key=lambda s: -len(s))[:15]:
        ms = [persons[i] for i in v]
        m = merge_cluster(ms)
        print(f"  {m['n']} ({len(v)}→1) {m['y'][0]}–{m['y'][1]}: "
              f"{', '.join(sorted({p['n'] for p in ms}))}")

    if not args.apply:
        print("\n(dry run — pass --apply to write)")
        return

    import shutil
    shutil.copy(PERSONS, "/tmp/persons_prerare.json")
    merged_ids = set(); out = []
    for v in merges:
        out.append(merge_cluster([persons[i] for i in v])); merged_ids.update(v)
    for i, p in enumerate(persons):
        if i not in merged_ids:
            out.append(p)
    out.sort(key=lambda p: -p.get("c", 0))
    json.dump(out, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nAPPLIED: {len(persons)} → {len(out)} persons (backup /tmp/persons_prerare.json)")


if __name__ == "__main__":
    main()
