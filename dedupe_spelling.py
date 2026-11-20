#!/usr/bin/env python3
"""
dedupe_spelling.py — merge city-wide persons that a tighter resolution holds as
one and whose names differ only in spelling.

The other dedupe passes compare names: same canonical given names and a
phonetically equal surname (dedupe_corpus, dedupe_rare_surnames), or an HLS
anchor (dedupe_persons). HTR noise defeats all of them — *Emanuel Schönauwer*,
*Schönawer* and *Schönauer* own the same house in the same years and stay three
persons. Two independent resolutions of the same register cards do see that
they are one:

  bli     an owner actor of *Basler Liegenschaften 1400–1700 Interaktiv*: one
          owner of one property, named in the very documents the eos persons
          come from (DHBern/basler-liegenschaften-interaktiv, read-only)
  street  a person of the street-level index (build_hgb_street_persons.py):
          same canonical given names, phonetically equal surname, one street
  dossier the index itself: both persons carry the very same full name variant
          in one dossier in the same years — one of them got the variant in
          another dossier, so the two are known to be called alike — and
          neither is first mentioned after the other is called deceased

link_bli_hgb.py writes every pair of city-wide persons that one of these unites
and whose names stand in a pure spelling relation (link_bli_hgb.name_relation
== "spelling": same number of given names, each ≥0.75 similar after
canonicalisation, surnames phonetically equal or ≥0.6 similar) to
dedupe_spelling_candidates.csv. This script applies them under the guards every
pass of the index observes:

  • one lifespan — the merged group's mentions span at most 80 years;
  • the deceased constraint — nobody in the group is first mentioned more than
    15 years after the group's earliest "deceased" mention;
  • confirmed identities — two persons carrying different HLS/Wikidata links
    never merge, and nothing joins an HLS-linked person from outside that
    person's known life (link_hls.fits_life).

Pairs are applied strongest first (both sources, then more BLI owners), so when
a chain of pairwise merges would break a guard, the best-supported links win.

    python3 link_bli_hgb.py                # writes the candidates for the current index
    python3 dedupe_spelling.py             # dry run + dedupe_spelling_clusters.csv
    python3 dedupe_spelling.py --apply     # write persons_resolved.json
    python3 dedupe_spelling.py --sources bli   # one source only (bli, street, dossier)

The candidates are tied to one state of persons_resolved.json (positions plus
person keys); a file that no longer fits is refused. After --apply, re-run
link_bli_hgb.py and the downstream builds (README, "Person pipeline").
"""
import argparse
import collections
import csv
import json
import os
import shutil
import sys
import tempfile

from dedupe_corpus import link_key, merge_cluster
from link_hls import life_envelope, fits_life
from lifedates import extra, extra_merge

csv.field_size_limit(10 ** 8)
HERE = os.path.dirname(os.path.abspath(__file__))
PERSONS = os.path.join(HERE, "persons_resolved.json")
CANDIDATES = os.path.join(HERE, "dedupe_spelling_candidates.csv")
CLUSTERS = os.path.join(HERE, "dedupe_spelling_clusters.csv")
MAXLIFE = 80
DEAD_GRACE = 15


def pkey(p):
    y = p.get("y") or [0, 0]
    return f"{p['n']}#{y[0]}-{y[1]}"


def load_candidates(path, persons, sources):
    """Pairs [(a, b, row)] whose positions still name the same persons."""
    pairs, stale = [], 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            a, b = int(r["a_idx"]), int(r["b_idx"])
            if (a >= len(persons) or b >= len(persons)
                    or pkey(persons[a]) != r["a_key"] or pkey(persons[b]) != r["b_key"]):
                stale += 1
                continue
            src = set(r["sources"].split("+")) & sources
            if not src:
                continue
            r["_src"] = src
            pairs.append((a, b, r))
    return pairs, stale


def strength(row):
    """Order of application: more sources first, then the number of BLI owners."""
    return (len(row["_src"]), int(row["n_bli_actors"] or 0))


def cluster(persons, pairs):
    """Union-find over the pairs with group-level guards.

    Returns (clusters, refused) — clusters as lists of person positions,
    refused as a Counter of the guard that stopped a pair.
    """
    n = len(persons)
    parent = list(range(n))
    y0 = [(p.get("y") or [None, None])[0] for p in persons]
    y1 = [(p.get("y") or [None, None])[1] for p in persons]
    start_max = list(y0)                       # latest first mention in the group
    dead = [p.get("dead_year") for p in persons]
    lk = [link_key(p) for p in persons]
    env = [life_envelope(p) for p in persons]
    ex = [extra(p) for p in persons]           # lifedates.extra of each group
    refused = collections.Counter()

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, row in sorted(pairs, key=lambda t: strength(t[2]), reverse=True):
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if lk[ra] and lk[rb] and lk[ra] != lk[rb]:
            refused["different HLS/Wikidata identities"] += 1
            continue
        if None in (y0[ra], y0[rb], y1[ra], y1[rb]):
            refused["undated"] += 1
            continue
        lo, hi = min(y0[ra], y0[rb]), max(y1[ra], y1[rb])
        if hi - lo > MAXLIFE:
            refused["more than one lifespan"] += 1
            continue
        d = min((x for x in (dead[ra], dead[rb]) if x), default=None)
        latest = max(start_max[ra], start_max[rb])
        if d and latest > d + DEAD_GRACE:
            refused["first mentioned long after a death"] += 1
            continue
        if not fits_life(env[ra] or env[rb], lo, hi, d, extra_merge(ex[ra], ex[rb])):
            refused["outside the known life of an HLS-linked person"] += 1
            continue
        parent[ra] = rb
        env[rb] = env[ra] or env[rb]
        ex[rb] = extra_merge(ex[ra], ex[rb])
        y0[rb], y1[rb] = lo, hi
        start_max[rb] = latest
        dead[rb] = d
        lk[rb] = lk[ra] or lk[rb]

    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return [g for g in groups.values() if len(g) > 1], refused


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the merged index")
    ap.add_argument("--persons", default=PERSONS)
    ap.add_argument("--candidates", default=CANDIDATES)
    ap.add_argument("--csv", default=CLUSTERS)
    ap.add_argument("--sources", default="bli,street,dossier",
                    help="which evidence to apply: bli, street, dossier (default: all)")
    args = ap.parse_args(argv)
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    if not sources <= {"bli", "street", "dossier"}:
        sys.exit("--sources takes bli, street and/or dossier")
    if not os.path.exists(args.candidates):
        sys.exit(f"{args.candidates} not found — run link_bli_hgb.py first")

    persons = json.load(open(args.persons, encoding="utf-8"))
    pairs, stale = load_candidates(args.candidates, persons, sources)
    if stale:
        sys.exit(f"{stale} candidate pairs no longer fit {os.path.basename(args.persons)} — "
                 "the index changed; re-run link_bli_hgb.py")
    by_src = collections.Counter("+".join(sorted(r["_src"])) for _, _, r in pairs)
    print(f"persons: {len(persons)}")
    print(f"candidate pairs: {len(pairs)}  ({dict(by_src)})")

    merge_sets, refused = cluster(persons, pairs)
    collapsed = sum(len(s) - 1 for s in merge_sets)
    print(f"refused by a guard: {sum(refused.values())}  {dict(refused)}")
    print(f"merge clusters: {len(merge_sets)}  (collapsing {collapsed} duplicates "
          f"→ {len(persons) - collapsed} persons)")
    sizes = collections.Counter(len(s) for s in merge_sets)
    print("cluster sizes:", dict(sorted(sizes.items())))

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster", "n_entries", "canonical", "year_range",
                    "total_mentions", "members"])
        for ci, idxs in enumerate(sorted(merge_sets, key=lambda s: -len(s))):
            ms = [persons[i] for i in idxs]
            m = merge_cluster(ms)
            w.writerow([ci, len(idxs), m["n"], f"{m['y'][0]}–{m['y'][1]}", m["c"],
                        " | ".join(f"{pkey(p)} ×{p.get('c', 0)}" for p in
                                   sorted(ms, key=lambda p: -p.get("c", 0)))])
    print(f"wrote cluster report → {args.csv}")

    print("\nLargest merges:")
    for idxs in sorted(merge_sets, key=lambda s: -len(s))[:10]:
        ms = [persons[i] for i in idxs]
        m = merge_cluster(ms)
        names = sorted({p["n"] for p in ms})
        print(f"  {m['n']} ({len(idxs)}→1) {m['y'][0]}–{m['y'][1]} c={m['c']}: "
              f"{', '.join(names[:6])}{' …' if len(names) > 6 else ''}")

    if not args.apply:
        print("\n(dry run — pass --apply to write persons_resolved.json)")
        return merge_sets, refused

    backup = os.path.join(tempfile.gettempdir(), "persons_prespelling.json")
    shutil.copy(args.persons, backup)
    merged_idx, out = set(), []
    for idxs in merge_sets:
        out.append(merge_cluster([persons[i] for i in idxs]))
        merged_idx.update(idxs)
    out.extend(p for i, p in enumerate(persons) if i not in merged_idx)
    out.sort(key=lambda p: -p.get("c", 0))
    json.dump(out, open(args.persons, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nAPPLIED: {len(persons)} → {len(out)} persons (backup at {backup})")
    return merge_sets, refused


if __name__ == "__main__":
    main()
