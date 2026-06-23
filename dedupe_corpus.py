#!/usr/bin/env python3
"""
dedupe_corpus.py — merge duplicate resolved persons using internal context.

Targets the ~150k persons with no HLS/Wikidata anchor. Two entries are merged
only when they look like the *same* individual on three independent axes:

  1. NAME    — same normalized surname + same canonical given-name sequence
               (Hans=Johann=Hanns, Jakob…), so different given names never merge;
  2. CONTEXT — they share a concrete anchor: the same property dossier, the same
               normalized occupation, or the same location. Shared context is
               what distinguishes "one person, two spellings" from "two people,
               one common name";
  3. TIME    — their combined mention span fits one lifespan (≤80 yr) and does
               not violate the deceased constraint (nobody is first mentioned
               alive well after they are recorded dead).

Merges across two *different* HLS/Wikidata identities are forbidden (those are
confirmed-distinct). By default this only REPORTS (counts + sample + a CSV of
the clusters); pass --apply to write the merged person index.

    python3 dedupe_corpus.py                 # dry run + dedupe_corpus_candidates.csv
    python3 dedupe_corpus.py --apply         # write persons_resolved.json
"""
import re
import csv
import json
import argparse
import unicodedata
import collections
from difflib import SequenceMatcher

PERSONS = "persons_resolved.json"
MAXLIFE = 80
DEAD_GRACE = 15        # a new identity starting >this many yr after a death = different person

GIVEN_CANON = {
    "hs": "hans", "hans": "hans", "hanns": "hans", "hannß": "hans", "hansen": "hans",
    "johannes": "hans", "johann": "hans", "joh": "hans", "johans": "hans", "hennslin": "hans",
    "heinr": "heinrich", "heinrich": "heinrich", "heini": "heinrich", "heintz": "heinrich",
    "heinz": "heinrich", "heinrichen": "heinrich",
    "cunrat": "konrad", "conrat": "konrad", "conrad": "konrad", "cunratz": "konrad",
    "konrad": "konrad", "conr": "konrad", "kunz": "konrad", "cuonrat": "konrad",
    "jacob": "jakob", "jakob": "jakob", "jac": "jakob", "jacobs": "jakob",
    "grg": "georg", "jergen": "georg", "jerg": "georg", "joerg": "georg",
    "ulrich": "ulrich", "uli": "ulrich", "ueli": "ulrich",
    "ruedi": "rudolf", "rudolff": "rudolf", "rudi": "rudolf", "rudolph": "rudolf",
    "petter": "peter", "claus": "klaus", "niclaus": "klaus", "niklaus": "klaus",
    "clewi": "klaus", "symon": "simon", "anthoni": "anton", "anthonin": "anton",
    "antoni": "anton", "thoman": "thomas", "wernher": "werner", "bastian": "sebastian",
}
SURNAME_CANON = {
    "meiger": "meyer", "meyger": "meyer", "meier": "meyer", "meijer": "meyer",
    "mullers": "muller", "muller": "muller", "müller": "muller", "miller": "muller",
    "kellers": "keller", "vischer": "fischer", "fyscher": "fischer", "fischers": "fischer",
    "schmidt": "schmid", "schmied": "schmid", "beck": "beckh", "becker": "beckh",
    "jselin": "iselin", "yselin": "iselin", "burckhard": "burckhardt", "burkhardt": "burckhardt",
}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(t):
    return re.sub(r"[^a-zäöü]", "", t.lower())


def canon(t):
    t = strip_accents(norm(t))
    return GIVEN_CANON.get(t, t)


def name_tokens(name):
    return [t for t in re.split(r"[ .,]", name) if len(norm(t)) > 1]


def given_seq(name):
    toks = name_tokens(name)
    return tuple(canon(t) for t in toks[:-1]) if len(toks) >= 2 else tuple(canon(t) for t in toks)


def surname_key(name):
    toks = name_tokens(name)
    if len(toks) < 2:
        return None
    last = strip_accents(norm(toks[-1]))
    last = SURNAME_CANON.get(last, last)
    if last.endswith("s") and len(last) > 4:
        last = SURNAME_CANON.get(last[:-1], last[:-1])
    return SURNAME_CANON.get(last, last)


def dossier_ids(p):
    out = set()
    for e in p.get("dos", []):
        out.add(e[0] if isinstance(e, list) else e)
    return out


def link_key(p):
    if p.get("wd"):
        return "q:" + p["wd"]["qid"]
    if p.get("hls"):
        return "h:" + p["hls"]["id"]
    return None


# ── merge (same shape as dedupe_persons) ─────────────────────────────────────

def dedup_list(*lists):
    out, seen = [], set()
    for lst in lists:
        for x in (lst or []):
            k = x.lower() if isinstance(x, str) else json.dumps(x, sort_keys=True)
            if k not in seen:
                seen.add(k); out.append(x)
    return out


def merge_cluster(members):
    base = max(members, key=lambda p: p.get("c", 0))
    m = dict(base)
    m["v"] = dedup_list(*[[p["n"]] for p in members], *[p.get("v") for p in members])
    m["c"] = sum(p.get("c", 0) for p in members)
    ys0 = [p["y"][0] for p in members if p.get("y")]
    ys1 = [p["y"][1] for p in members if p.get("y")]
    m["y"] = [min(ys0), max(ys1)] if ys0 else base.get("y")
    deads = [p["dead_year"] for p in members if p.get("dead_year")]
    m["dead_year"] = min(deads) if deads else None
    for k in ("occ", "tit", "fam", "org", "loc", "dos"):
        v = dedup_list(*[p.get(k) for p in members])
        if v:
            m[k] = v
        else:
            m.pop(k, None)
    m["d"] = len(dossier_ids(m))
    # keep any HLS/Wikidata payload present (at most one identity in a cluster)
    for k in ("hls", "wd", "kin"):
        val = next((p[k] for p in members if p.get(k)), None)
        if val is not None:
            m[k] = val
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write merged index")
    ap.add_argument("--csv", default="dedupe_corpus_candidates.csv")
    args = ap.parse_args()

    persons = json.load(open(PERSONS, encoding="utf-8"))

    # precompute per-person keys
    meta = []
    for p in persons:
        sk = surname_key(p["n"])
        meta.append({
            "sk": sk, "gs": given_seq(p["n"]),
            "dos": dossier_ids(p),
            "occ": set(o.lower() for o in p.get("occ", [])),
            "loc": set(l.lower() for l in p.get("loc", [])),
            "y0": (p.get("y") or [None])[0], "y1": (p.get("y") or [None, None])[1],
            "dead": p.get("dead_year"), "lk": link_key(p),
        })

    # block by (surname, given-sequence); only blockable (has surname) persons
    blocks = collections.defaultdict(list)
    for i, mt in enumerate(meta):
        if mt["sk"] and mt["gs"]:
            blocks[(mt["sk"], mt["gs"])].append(i)

    # union-find with group guards (span / deceased / distinct-identity)
    parent = list(range(len(persons)))
    gy0 = [m["y0"] for m in meta]
    gy1 = [m["y1"] for m in meta]
    gdead = [m["dead"] for m in meta]
    glk = [m["lk"] for m in meta]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def try_union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # distinct confirmed identities never merge
        if glk[ra] and glk[rb] and glk[ra] != glk[rb]:
            return
        y0s = [v for v in (gy0[ra], gy0[rb]) if v is not None]
        y1s = [v for v in (gy1[ra], gy1[rb]) if v is not None]
        if y0s and y1s:
            lo, hi = min(y0s), max(y1s)
            if hi - lo > MAXLIFE:
                return
            dead = min([d for d in (gdead[ra], gdead[rb]) if d is not None], default=None)
            if dead is not None and lo > dead + DEAD_GRACE:
                return
        parent[ra] = rb
        gy0[rb] = min(y0s) if y0s else gy1[rb]
        gy1[rb] = max(y1s) if y1s else gy1[rb]
        gdead[rb] = min([d for d in (gdead[ra], gdead[rb]) if d is not None], default=None)
        glk[rb] = glk[ra] or glk[rb]

    # within each block, link persons that share a concrete context anchor
    for members in blocks.values():
        if len(members) < 2:
            continue
        for axis in ("dos", "occ", "loc"):
            inv = collections.defaultdict(list)
            for i in members:
                for v in meta[i][axis]:
                    inv[v].append(i)
            for shared in inv.values():
                for k in range(1, len(shared)):
                    try_union(shared[0], shared[k])

    # gather clusters
    clusters = collections.defaultdict(list)
    for i in range(len(persons)):
        clusters[find(i)].append(i)
    merge_sets = [idxs for idxs in clusters.values() if len(idxs) > 1]

    collapsed = sum(len(s) - 1 for s in merge_sets)
    print(f"persons: {len(persons)}")
    print(f"merge clusters: {len(merge_sets)}  (collapsing {collapsed} duplicates "
          f"→ {len(persons) - collapsed} persons)")

    # what evidence drove each merge (for the report)
    def evidence(idxs):
        ax = []
        for axis in ("dos", "occ", "loc"):
            common = set.intersection(*[meta[i][axis] for i in idxs]) if all(meta[i][axis] for i in idxs) else set()
            if common:
                ax.append(axis)
        return ",".join(ax) or "mixed"

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster", "n_entries", "evidence", "canonical", "year_range",
                    "total_mentions", "variants"])
        for ci, idxs in enumerate(sorted(merge_sets, key=lambda s: -len(s))):
            ms = [persons[i] for i in idxs]
            m = merge_cluster(ms)
            w.writerow([ci, len(idxs), evidence(idxs), m["n"],
                        f"{m['y'][0]}–{m['y'][1]}" if m.get("y") else "?",
                        m["c"], " | ".join(sorted({x for p in ms for x in [p["n"]]}))])
    print(f"wrote cluster report → {args.csv}")

    print("\nLargest sample merges:")
    for idxs in sorted(merge_sets, key=lambda s: -len(s))[:12]:
        ms = [persons[i] for i in idxs]
        m = merge_cluster(ms)
        names = sorted({p["n"] for p in ms})
        print(f"  [{evidence(idxs):3s}] {m['n']} ({len(idxs)}→1) "
              f"{m['y'][0]}–{m['y'][1]} c={m['c']}: {', '.join(names[:5])}"
              f"{' …' if len(names) > 5 else ''}")

    if not args.apply:
        print("\n(dry run — pass --apply to write persons_resolved.json)")
        return

    import shutil
    shutil.copy(PERSONS, "/tmp/persons_predcorpus.json")
    merged_idx = set()
    out = []
    for idxs in merge_sets:
        out.append(merge_cluster([persons[i] for i in idxs]))
        merged_idx.update(idxs)
    for i, p in enumerate(persons):
        if i not in merged_idx:
            out.append(p)
    out.sort(key=lambda p: -p.get("c", 0))
    json.dump(out, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nAPPLIED: {len(persons)} → {len(out)} persons "
          f"(backup at /tmp/persons_predcorpus.json)")


if __name__ == "__main__":
    main()
