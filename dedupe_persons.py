#!/usr/bin/env python3
"""
dedupe_persons.py — merge duplicate resolved persons using HLS/Wikidata signals.

Many real individuals are over-split in persons_resolved.json (OCR/spelling
variants landed in separate entries). The HLS link gives a strong anchor: all
entries sharing an HLS article id are the same *surname* in roughly the same
era. Within each such group we merge entries that

  • share the same canonical given-name sequence (Hans=Johann=Hanns, Jakob …),
    so father "Hans" and son "Johann Jakob" stay distinct, and
  • fall within one lifespan (≤ MAXLIFE years; bounded by the Wikidata
    birth/death envelope when known) — so same-name grandfather/grandson in
    one article split into generations.

This implements the rule: a notable person (e.g. a Bürgermeister) that
Wikidata records once for an epoch absorbs all same-name variants of that
epoch. Unlinked persons (no HLS/Wikidata signal) are left untouched.
"""
import json
import re
import unicodedata
import collections
from difflib import SequenceMatcher

PERSONS = "persons_resolved.json"
MAXLIFE = 85          # max span (yr) of one merged identity
POSTMORTEM = 60       # mentions up to this many yr after death still count

GIVEN_CANON = {
    "hs": "hans", "hans": "hans", "hanns": "hans", "hannß": "hans", "hansen": "hans",
    "johannes": "hans", "johann": "hans", "joh": "hans", "johans": "hans", "hennslin": "hans",
    "heinr": "heinrich", "heinrich": "heinrich", "heini": "heinrich", "heintz": "heinrich",
    "heinz": "heinrich", "heinrichen": "heinrich",
    "cunrat": "konrad", "conrat": "konrad", "conrad": "konrad", "cunratz": "konrad",
    "konrad": "konrad", "conr": "konrad", "kunz": "konrad", "cuonrat": "konrad",
    "jacob": "jakob", "jakob": "jakob", "jac": "jakob",
    "grg": "georg", "jergen": "georg", "jerg": "georg",
    "ulrich": "ulrich", "uli": "ulrich", "ueli": "ulrich",
    "ruedi": "rudolf", "rudolff": "rudolf", "rudi": "rudolf", "rudolph": "rudolf",
    "petter": "peter", "claus": "klaus", "niclaus": "klaus", "niklaus": "klaus",
    "symon": "simon", "anthoni": "anton", "anthonin": "anton", "antoni": "anton",
    "thoman": "thomas", "wernher": "werner",
}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(t):
    return strip_accents(re.sub(r"[^\wäöü]", "", t.lower()))


def canon(t):
    t = norm(t)
    return GIVEN_CANON.get(t, t)


def given_seq(name):
    """Canonical given-name tokens (all but the surname)."""
    toks = [t for t in re.split(r"[ .,]", name) if len(t) > 1]
    toks = [t for t in toks if norm(t)]
    if len(toks) < 2:
        return tuple(canon(t) for t in toks)
    return tuple(canon(t) for t in toks[:-1])


def given_match(a, b):
    if a == b:
        return True
    if len(a) != len(b) or not a:
        return False
    return all(x == y or SequenceMatcher(None, x, y).ratio() >= 0.8
               for x, y in zip(a, b))


def name_sim(a, b):
    ta = [canon(t) for t in re.split(r"[ .,]", a) if len(t) > 1]
    tb = [canon(t) for t in re.split(r"[ .,]", b) if len(t) > 1]
    if not ta or not tb:
        return 0.0
    s = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return s


def dedup_list(*lists):
    out, seen = [], set()
    for lst in lists:
        for x in (lst or []):
            k = x.lower() if isinstance(x, str) else json.dumps(x, sort_keys=True)
            if k not in seen:
                seen.add(k); out.append(x)
    return out


def merge_cluster(members, hls_title):
    members = sorted(members, key=lambda p: -p.get("c", 0))
    # canonical name: variant closest to the HLS title, else most-mentioned
    base = max(members, key=lambda p: (name_sim(p["n"], hls_title or ""), p.get("c", 0)))
    variants, occ, tit, fam, org, loc, dos = [], [], [], [], [], [], []
    ys0, ys1, deads, c = [], [], [], 0
    wd = kin = None
    kinlinks = []
    for p in members:
        variants = dedup_list(variants, [p["n"]], p.get("v"))
        occ = dedup_list(occ, p.get("occ")); tit = dedup_list(tit, p.get("tit"))
        fam = dedup_list(fam, p.get("fam")); org = dedup_list(org, p.get("org"))
        loc = dedup_list(loc, p.get("loc")); dos = dedup_list(dos, p.get("dos"))
        c += p.get("c", 0)
        if p.get("y"):
            ys0.append(p["y"][0]); ys1.append(p["y"][1])
        if p.get("dead_year"):
            deads.append(p["dead_year"])
        if p.get("wd") and (wd is None or len(p["wd"]) > len(wd)):
            wd = p["wd"]
        if p.get("kin") and (kin is None or len(p["kin"]) > len(kin)):
            kin = p["kin"]
        if p.get("wd", {}).get("kinlinks"):
            kinlinks = dedup_list(kinlinks, p["wd"]["kinlinks"])
    m = dict(base)
    m["n"] = base["n"]
    m["v"] = variants
    m["c"] = c
    m["d"] = len(dos)
    m["y"] = [min(ys0), max(ys1)] if ys0 else base.get("y")
    m["dead_year"] = min(deads) if deads else None
    for k, v in (("occ", occ), ("tit", tit), ("fam", fam),
                 ("org", org), ("loc", loc), ("dos", dos)):
        if v:
            m[k] = v
        else:
            m.pop(k, None)
    if wd:
        if kinlinks:
            wd = dict(wd); wd["kinlinks"] = kinlinks
        m["wd"] = wd
    if kin:
        m["kin"] = kin
    return m


def cluster_group(members):
    """Split an HLS-id group into identity clusters (same given name + epoch)."""
    # life envelope from Wikidata, if present
    wd = next((p["wd"] for p in members if p.get("wd")), {})
    b, d = wd.get("b"), wd.get("d")

    # group by canonical given-name sequence (fuzzy)
    buckets = []
    for p in sorted(members, key=lambda x: (x.get("y") or [9999])[0]):
        gs = given_seq(p["n"])
        placed = False
        for bk in buckets:
            if given_match(gs, bk["gs"]):
                bk["items"].append(p); placed = True; break
        if not placed:
            buckets.append({"gs": gs, "items": [p]})

    # Wikidata life envelope (birth..death + postmortem) pins the confirmed
    # person; mentions inside it merge even across a long span.
    env = None
    if b or d:
        lo = (b - 10) if b else (d - 95)
        hi = (d + POSTMORTEM) if d else (b + 90)
        env = (lo, hi)

    clusters = []
    for bk in buckets:
        items = sorted(bk["items"], key=lambda x: (x.get("y") or [9999])[0])
        # if this bucket is the QID person's given name and we have an envelope,
        # everything overlapping the lifespan is one identity (strict merge)
        if env and given_match(bk["gs"], given_seq(next(
                (p["hls"]["t"] for p in members if p.get("hls", {}).get("t")), ""))):
            inside = [p for p in items if p.get("y")
                      and p["y"][0] <= env[1] and p["y"][1] >= env[0]]
            outside = [p for p in items if p not in inside]
            if inside:
                clusters.append(inside)
            items = outside
        # remaining: greedy clustering capped by TOTAL span ≤ MAXLIFE
        cur, lo, hi = [], None, None
        for p in items:
            y = p.get("y")
            y0 = y[0] if y else None
            y1 = y[1] if y else None
            if cur and y0 is not None and lo is not None:
                nlo, nhi = min(lo, y0), max(hi, y1)
                if nhi - nlo > MAXLIFE:
                    clusters.append(cur); cur, lo, hi = [], None, None
            cur.append(p)
            if y0 is not None:
                lo = y0 if lo is None else min(lo, y0)
                hi = y1 if hi is None else max(hi, y1)
        if cur:
            clusters.append(cur)
    return clusters


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))
    linked = [p for p in persons if p.get("hls")]
    others = [p for p in persons if not p.get("hls")]

    by_hls = collections.defaultdict(list)
    for p in linked:
        by_hls[p["hls"]["id"]].append(p)

    merged_persons = []
    n_clusters = n_collapsed = 0
    examples = []
    for hid, grp in by_hls.items():
        title = grp[0]["hls"].get("t")
        for cl in cluster_group(grp):
            if len(cl) > 1:
                n_collapsed += len(cl) - 1
                merged_persons.append(merge_cluster(cl, title))
                if len(examples) < 12 and len(cl) >= 4:
                    examples.append((title, len(cl), merge_cluster(cl, title)))
            else:
                merged_persons.append(cl[0])
            n_clusters += 1

    out = others + merged_persons
    # keep stable order: by mentions desc
    out.sort(key=lambda p: -p.get("c", 0))

    json.dump(out, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

    print(f"linked persons: {len(linked)}  →  {len(merged_persons)} "
          f"({n_collapsed} duplicates merged away)")
    print(f"total persons: {len(persons)}  →  {len(out)}")
    print("\nExamples of merges:")
    for title, n, m in examples:
        print(f"  {m['n']}  ({n} entries → 1)  y={m['y']} c={m['c']}  "
              f"variants={len(m['v'])}")


if __name__ == "__main__":
    main()
