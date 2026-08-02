#!/usr/bin/env python3
"""
build_identity_clusters.py — Stage 3: cross-corpus identity deduplication.

Builds a graph whose nodes are records from the four corpora plus the authority
ids that connect them, unions them over the *accepted* links from Stages 1-2 and
the GND linking, and treats each connected component as one real person.

  node namespaces:  hbls:<id>  hgb:<name>#<year>  hls:<id>  gnd:<id>  wd:<qid>

  edges (only confident links are unioned — see the gates below):
    HBLS↔HLS   link_hbls_hls_candidates.csv      score≥.9, unambiguous
    HGB ↔HLS   link_candidates_hls.csv           score≥.85, unambiguous, overlap
    HBLS↔HGB   link_hbls_hgb_candidates.csv      score≥.8, unambiguous, overlap
    HBLS↔GND   link_hbls_gnd.csv                 date_check == ok  (+ its HLS/WD)
    HBLS↔GND   link_hbls_gnd_lobid_candidates    score≥.85, unambiguous
    HGB ↔GND   persons_resolved.json (wd.gnd/qid)

A shared GND/Wikidata id is itself a node, so two records pointing at the same
authority id merge transitively — the strongest dedup signal.

Guards against over-merge: a component with >1 record from the same corpus, or
with birth years spread > 15 y, is flagged (not silently merged). See
hbls-extraction/DEDUP_PLAN.md (Stage 3) and GND_LINKING_PLAN.md.

    python3 build_identity_clusters.py
"""
import csv
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
csv.field_size_limit(10_000_000)


# ── union-find ───────────────────────────────────────────────────────────────
parent = {}
meta = {}            # node -> {corpus, name, b, d}


def node(key, corpus, name="", b=None, d=None, span=None):
    parent.setdefault(key, key)
    m = meta.setdefault(key,
                        {"corpus": corpus, "name": name, "b": b, "d": d,
                         "span": span})
    if name and not m["name"]:
        m["name"] = name
    if b and not m["b"]:
        m["b"] = b
    if d and not m["d"]:
        m["d"] = d
    if span and not m.get("span"):
        m["span"] = span
    return key


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb


def to_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def rd(path):
    p = os.path.join(HERE, path)
    return csv.DictReader(open(p, encoding="utf-8")) if os.path.exists(p) else []


def hgb_key(name, year):
    return f"hgb:{name.strip()}#{year}"


# ── load authoritative HBLS person dates ─────────────────────────────────────
hbls_meta = {}
hp = os.path.join(HERE, "hbls-extraction", "hbls_persons.json")
if os.path.exists(hp):
    for p in json.load(open(hp, encoding="utf-8")):
        hbls_meta[p["id"]] = (p["name"], p.get("birth_year"), p.get("death_year"))


def hbls_node(hid, name=""):
    nm, b, d = hbls_meta.get(hid, (name, None, None))
    return node(f"hbls:{hid}", "hbls", nm or name, b, d)


# ── edges ────────────────────────────────────────────────────────────────────
stats = defaultdict(int)

# 1) HBLS ↔ HLS
for r in rd("link_hbls_hls_candidates.csv"):
    if float(r["score"]) >= 0.9 and r["n_candidates"] == "1":
        a = hbls_node(r["hbls_id"], r["hbls_name"])
        h = node(f"hls:{r['hls_id']}", "hls", r["hls_title"],
                 to_int(r["hls_birth"]), to_int(r["hls_death"]))
        union(a, h); stats["hbls_hls"] += 1

# 2) HGB ↔ HLS
for r in rd("link_candidates_hls.csv"):
    if (r["n_candidates_for_person"] == "1" and r["date_relation"] == "overlap"
            and float(r["score"]) >= 0.85):
        g = node(hgb_key(r["hgb_name"], r["hgb_year_min"]), "hgb", r["hgb_name"],
                 span=(to_int(r["hgb_year_min"]), to_int(r["hgb_year_max"])))
        h = node(f"hls:{r['hls_id']}", "hls", r.get("hls_title", ""),
                 to_int(r["hls_birth"]), to_int(r["hls_death"]))
        union(g, h); stats["hgb_hls"] += 1

# 3) HBLS ↔ HGB (direct)
for r in rd("link_hbls_hgb_candidates.csv"):
    if (r["n_candidates"] == "1" and r["date_relation"] == "overlap"
            and float(r["score"]) >= 0.8):
        a = hbls_node(r["hbls_id"], r["hbls_name"])
        g = node(hgb_key(r["hgb_name"], r["hgb_year_min"]), "hgb", r["hgb_name"],
                 span=(to_int(r["hgb_year_min"]), to_int(r["hgb_year_max"])))
        union(a, g); stats["hbls_hgb"] += 1

# 4) HBLS ↔ GND (Tier 0, date-validated) — also ties in its HLS + Wikidata
for r in rd("link_hbls_gnd.csv"):
    if r.get("date_check") != "ok":
        continue
    a = hbls_node(r["hbls_id"], r["hbls_name"])
    union(a, node(f"gnd:{r['gnd']}", "gnd"))
    if r.get("wikidata_qid"):
        union(a, node(f"wd:{r['wikidata_qid']}", "wd"))
    if r.get("via_hls_id"):
        union(a, node(f"hls:{r['via_hls_id']}", "hls"))
    stats["hbls_gnd_t0"] += 1

# 5) HBLS ↔ GND (Tier 1, lobid)
for r in rd("link_hbls_gnd_lobid_candidates.csv"):
    if r["n_candidates"] == "1" and float(r["score"]) >= 0.85:
        a = hbls_node(r["hbls_id"], r["hbls_name"])
        union(a, node(f"gnd:{r['gnd']}", "gnd")); stats["hbls_gnd_t1"] += 1

# 6) HGB ↔ GND / Wikidata  (from the existing enrich_wikidata `wd` field)
pr = os.path.join(HERE, "persons_resolved.json")
if os.path.exists(pr):
    for p in json.load(open(pr, encoding="utf-8")):
        wd = p.get("wd")
        if not wd or not p.get("y"):
            continue
        g = node(hgb_key(p["n"], p["y"][0]), "hgb", p["n"],
                 span=(p["y"][0], p["y"][-1]))
        if wd.get("gnd"):
            union(g, node(f"gnd:{wd['gnd']}", "gnd")); stats["hgb_gnd"] += 1
        if wd.get("qid"):
            union(g, node(f"wd:{wd['qid']}", "wd"))


# TRIM_HGB: an HGB mention-cluster whose years fall entirely outside the person's
# authoritative life span (from HLS/HBLS dates) is a Basel homonym of another era
# that a loose HGB↔HLS name match pulled in. Detach it before scoring conflicts,
# so the remaining, in-span records form one clean identity.
TRIM_TOL_BEFORE = 5
TRIM_GRACE_AFTER = 15


def life_span(nodes):
    """Authoritative [lo, hi] from the HLS/HBLS dated nodes of a component."""
    dated = [meta[n] for n in nodes if meta[n]["corpus"] in ("hls", "hbls")]
    births = [m["b"] for m in dated if m["b"]]
    deaths = [m["d"] for m in dated if m["d"]]
    b = min(births) if births else None
    d = max(deaths) if deaths else None
    lo = b if b else (d - 80 if d else None)
    hi = d if d else (b + 80 if b else None)
    if lo is None:
        return None, None
    return lo - TRIM_TOL_BEFORE, hi + TRIM_GRACE_AFTER


def out_of_span(span, lo, hi):
    """Out of span if the FIRST mention year falls outside [lo, hi]. A person
    cannot appear in the register before birth (− tol) or after death (+ grace);
    the last-mention year may legitimately extend past death (post-mortem
    property references), so only the first mention is tested."""
    if not span:
        return False
    m0 = span[0] if span[0] is not None else span[1]
    if m0 is None:
        return False
    return m0 < lo or m0 > hi


# ── assemble components ──────────────────────────────────────────────────────
comp = defaultdict(list)
for n in parent:
    comp[find(n)].append(n)

SRC = {"hbls", "hgb", "hls"}
clusters = []
n_trimmed_hgb = 0
n_trimmed_clusters = 0
for root, nodes in comp.items():
    if len(nodes) < 2:
        continue

    # trim out-of-span HGB homonyms first, using the HLS/HBLS life span
    lo, hi = life_span(nodes)
    trimmed = []
    if lo is not None:
        kept = []
        for n in nodes:
            if meta[n]["corpus"] == "hgb" and out_of_span(meta[n].get("span"), lo, hi):
                trimmed.append(n)
            else:
                kept.append(n)
        nodes = kept
    if trimmed:
        n_trimmed_hgb += len(trimmed)
        n_trimmed_clusters += 1
    if len(nodes) < 2:
        continue

    by_corpus = defaultdict(list)
    for n in nodes:
        by_corpus[meta[n]["corpus"]].append(n)
    corpora = {c for c in by_corpus if c in SRC}
    if len(corpora) < 2 and not (len(by_corpus.get("hbls", [])) and
                                 (by_corpus.get("gnd") or by_corpus.get("wd"))):
        # keep only clusters that actually bridge ≥2 source corpora OR attach an
        # authority id to a source record (the useful dedup/enrichment cases)
        if len(corpora) < 2:
            continue
    conflicts = []
    for c in SRC | {"gnd", "wd"}:
        if len(by_corpus.get(c, [])) > 1:
            conflicts.append(f"multi_{c}")
    births = [meta[n]["b"] for n in nodes if meta[n]["b"]]
    if births and max(births) - min(births) > 15:
        conflicts.append("birth_spread")
    members = [{"node": n, **{k: meta[n][k] for k in ("corpus", "name", "b", "d")}}
               for n in sorted(nodes)]
    clusters.append({
        "id": min(nodes),
        "size": len(nodes),
        "corpora": sorted(corpora),
        "n_hbls": len(by_corpus.get("hbls", [])),
        "n_hgb": len(by_corpus.get("hgb", [])),
        "n_hls": len(by_corpus.get("hls", [])),
        "gnd": [n[4:] for n in by_corpus.get("gnd", [])],
        "wikidata": [n[3:] for n in by_corpus.get("wd", [])],
        "conflicts": conflicts,
        "trimmed_hgb": [n[4:] for n in trimmed],
        "members": members,
    })

clusters.sort(key=lambda c: (-len(c["corpora"]), -c["size"]))
json.dump(clusters, open(os.path.join(HERE, "identity_clusters.json"), "w"),
          ensure_ascii=False, indent=1)

# clean merged CSV: multi-source, conflict-free
clean = [c for c in clusters if len(c["corpora"]) >= 2 and not c["conflicts"]]
with open(os.path.join(HERE, "identity_clusters.csv"), "w",
          encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["cluster_id", "corpora", "name", "birth", "death",
                "gnd", "wikidata", "hbls_ids", "hgb_names", "hls_ids"])
    for c in clean:
        hb = [m for m in c["members"] if m["corpus"] == "hbls"]
        hl = [m for m in c["members"] if m["corpus"] == "hls"]
        name = (hl or hb)[0]["name"] if (hl or hb) else ""
        b = next((m["b"] for m in c["members"] if m["b"]), "")
        d = next((m["d"] for m in c["members"] if m["d"]), "")
        w.writerow([
            c["id"], "+".join(c["corpora"]), name, b, d,
            ";".join(c["gnd"]), ";".join(c["wikidata"]),
            ";".join(m["node"][5:] for m in hb),
            ";".join(m["node"][4:] for m in c["members"] if m["corpus"] == "hgb"),
            ";".join(m["node"][4:] for m in hl)])

# ── report ───────────────────────────────────────────────────────────────────
multi = [c for c in clusters if len(c["corpora"]) >= 2]
flagged = [c for c in clusters if c["conflicts"]]
withgnd = [c for c in clusters if c["gnd"]]
print("edges unioned:", dict(stats))
print(f"trimmed HGB homonyms         : {n_trimmed_hgb} "
      f"from {n_trimmed_clusters} clusters (out-of-span, detached)")
print(f"\nclusters (size≥2)            : {len(clusters)}")
print(f"  multi-corpus (dedup links) : {len(multi)}")
print(f"  conflict-free multi-corpus : {len(clean)}  -> identity_clusters.csv")
print(f"  carry a GND id             : {len(withgnd)}")
print(f"  flagged (review)           : {len(flagged)}")
tri = [c for c in multi if len(c["corpora"]) == 3]
print(f"  span all 3 source corpora  : {len(tri)}")
print("\nexamples (3-corpus, clean):")
for c in [c for c in clean if len(c["corpora"]) == 3][:8]:
    nm = next((m["name"] for m in c["members"] if m["corpus"] == "hls"), c["members"][0]["name"])
    print(f"  {nm:26s} gnd={','.join(c['gnd']) or '-':12s} "
          f"hbls={c['n_hbls']} hgb={c['n_hgb']} hls={c['n_hls']}")


if __name__ == "__main__":
    pass
