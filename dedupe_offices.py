#!/usr/bin/env python3
"""
dedupe_offices.py — dedupe holders of single-occupancy Basel offices.

Basel's head offices — Bürgermeister and Oberstzunftmeister — were held by one
person at a time. So two same-name holders whose attested periods OVERLAP cannot
be two different people: they are spelling variants of one office-holder. This
merges them even when they share no dossier/occupation context (the gap the
context-based deduper can't bridge).

Crucially, the ≤80-yr span cap is kept, so a recurring dynastic name (e.g.
Lienhart Grieb the elder vs. the younger, ~94 yr apart) is NOT merged — only
genuinely contemporaneous variants are.

Wikidata gave only a sparse Basel-Bürgermeister roster (the position exists,
but ~5 holders total), too thin to drive the merge; it is used only to avoid
merging two entries carrying *different* confirmed Wikidata/HLS identities.

    python3 dedupe_offices.py            # dry run
    python3 dedupe_offices.py --apply
"""
import json
import argparse
from difflib import SequenceMatcher

from dedupe_corpus import (koelner, given_seq, surname_raw, link_key,
                           merge_cluster, SequenceMatcher as _sm)

PERSONS = "persons_resolved.json"
MAXLIFE = 80

OFFICE_OCC = {
    "bürgermeister", "burgermeister", "alt-bürgermeister", "stadt-bürgermeister",
    "burgmeister", "alt-burgermeister",
    "oberster zunftmeister", "alt oberster zunftmeister", "oberstzunftmeister",
    "obristmeister", "alt oberstzunftmeister",
}
OFFICE_TIT = {"burgermeister", "burgmeister"}


def holds_office(p):
    if any(o.strip().lower() in OFFICE_OCC for o in p.get("occ", [])):
        return True
    if any(t.strip(". ").lower() in OFFICE_TIT for t in p.get("tit", [])):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    persons = json.load(open(PERSONS, encoding="utf-8"))
    office_set = {i for i, p in enumerate(persons) if holds_office(p)}
    print(f"single-occupancy office-holders: {len(office_set)}")

    # Block ALL persons by phonetic surname + canonical given-name sequence,
    # then only act on blocks that contain a confirmed office-holder: a same-name
    # contemporary of a one-at-a-time office-holder must be that same person.
    import collections
    allblocks = collections.defaultdict(list)
    for i, p in enumerate(persons):
        surn = surname_raw(p["n"])
        if surn:
            allblocks[(koelner(surn), given_seq(p["n"]))].append(i)
    blocks = {k: v for k, v in allblocks.items()
              if len(v) > 1 and any(i in office_set for i in v)}
    members_all = {i for v in blocks.values() for i in v}
    print(f"persons in office-bearing name-blocks: {len(members_all)} "
          f"across {len(blocks)} blocks")

    parent = {i: i for i in members_all}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def y(i):
        return persons[i].get("y")

    # union-find tracking the merged span and the confirmed-identity key
    grp = {i: {"y0": (y(i) or [None])[0], "y1": (y(i) or [None, None])[1],
               "lk": link_key(persons[i])} for i in members_all}

    def try_union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if grp[ra]["lk"] and grp[rb]["lk"] and grp[ra]["lk"] != grp[rb]["lk"]:
            return                                    # different confirmed people
        ya, yb = y(a), y(b)
        if not ya or not yb:
            return
        if not (ya[0] <= yb[1] and yb[0] <= ya[1]):   # require overlapping terms
            return
        lo = min(grp[ra]["y0"], grp[rb]["y0"])
        hi = max(grp[ra]["y1"], grp[rb]["y1"])
        if hi - lo > MAXLIFE:                         # protect dynastic recurrences
            return
        # surnames must be genuinely similar (phonetic block can be loose)
        sa, sb = surname_raw(persons[a]["n"]), surname_raw(persons[b]["n"])
        if sa != sb and SequenceMatcher(None, sa, sb).ratio() < 0.6:
            return
        parent[ra] = rb
        grp[rb] = {"y0": lo, "y1": hi, "lk": grp[ra]["lk"] or grp[rb]["lk"]}

    for members in blocks.values():
        for k in range(1, len(members)):
            try_union(members[0], members[k])

    clusters = collections.defaultdict(list)
    for i in members_all:
        clusters[find(i)].append(i)
    merges = [v for v in clusters.values() if len(v) > 1]
    collapsed = sum(len(v) - 1 for v in merges)
    print(f"merge clusters: {len(merges)}  (collapsing {collapsed} duplicates)")
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
    shutil.copy(PERSONS, "/tmp/persons_preoffices.json")
    merged_ids = set()
    out = []
    for v in merges:
        out.append(merge_cluster([persons[i] for i in v]))
        merged_ids.update(v)
    for i, p in enumerate(persons):
        if i not in merged_ids:
            out.append(p)
    out.sort(key=lambda p: -p.get("c", 0))
    json.dump(out, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nAPPLIED: {len(persons)} → {len(out)} persons "
          f"(backup /tmp/persons_preoffices.json)")


if __name__ == "__main__":
    main()
