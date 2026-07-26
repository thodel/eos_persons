#!/usr/bin/env python3
"""
build_merged_persons.py — Stage 4: merge & emit.

Consumes the Stage-3 identity clusters (identity_clusters.json) and resolves
each one into a single merged person record: preferred display name, union of
life dates, occupations, family links, authority ids and a `sources[]` array
carrying full provenance back to every contributing corpus.

  inputs   identity_clusters.json                    (Stage 3 components)
           hbls-extraction/hbls_persons.json         (HBLS: bio, volume/page)
           persons_resolved.json                     (HGB: occ, dossiers, kin)
           /Users/TH_1/Documents/HLS/hls_articles.csv (HLS: title, dates, gender)
           hbls-extraction/gnd_enrichment.json       (GND: roles, publications)

  output   merged_persons.json   one record per cluster
           merged_persons.csv    flat summary for review

Field precedence follows DEDUP_PLAN.md (Stage 4): the HLS form of the name and
its life dates win where present (the online lexicon is the corrected successor
of the printed HBLS), GND is the next-best dated authority, HBLS last. Every
value records where it came from in `provenance`.

Clusters that Stage 3 flagged (`conflicts`) are emitted with status "review"
rather than dropped, so the review queue has something to consume; pass
--clean-only to emit merged records alone.

    python3 build_merged_persons.py
"""
import os
import re
import csv
import json
import argparse
from collections import defaultdict

from link_hls import year_of, hls_url, canon_given, norm_token, ratio, PARTICLES

HERE = os.path.dirname(os.path.abspath(__file__))
csv.field_size_limit(10_000_000)

HLS_DEFAULT = "/Users/TH_1/Documents/HLS/hls_articles.csv"
HBLS_URL = "https://biblio.unibe.ch/digibern/hist_bibliog_lexikon_schweiz"

# Below this, the source corpora disagree on the given name and the cluster
# goes to review. 0.6 keeps early-modern spelling variants (Lukas/Lucas,
# Matthäus/Matheus) merged while catching genuinely different names.
NAME_MIN = 0.6


def first(*vals):
    """First non-empty value, with the label it came from."""
    for label, v in vals:
        if v not in (None, "", [], {}):
            return v, label
    return None, None


def given_tokens(name):
    """Every given-name token, canonicalised — not just the first.

    `link_hls.split_name` compares `toks[0]` alone, so "Hans Ulrich" and
    "Johann Jakob" score a perfect match (both canonicalise to "johann").
    In early-modern Swiss naming the *second* given name is usually the
    distinguishing one (Hans Heinrich / Hans Ulrich / Hans Jakob are three
    different men), so agreement on the first token alone is weak evidence.

    Particles are dropped and the trailing token is taken as the surname, so
    HLS's noble epithets ("Escher vom Luchs") do not leak into the given part.
    """
    toks = [t for t in re.sub(r"[.,]", " ", name).split() if len(t) > 1]
    toks = [t for t in toks if norm_token(t) and norm_token(t) not in PARTICLES]
    return [canon_given(t) for t in toks[:-1]] if len(toks) >= 2 else []


def name_agreement(names):
    """Worst pairwise given-name agreement across a cluster's source names.

    Only the common prefix of the given names is compared: a source that
    simply omits a middle name ("Heinrich" vs "Heinrich Ludwig") should not
    count as disagreement, whereas a conflicting one ("Johann Jakob" vs
    "Johann Ulrich") should. Returns None when there is nothing to compare.
    """
    lists = [g for g in (given_tokens(n) for n in names) if g]
    if len(lists) < 2:
        return None
    worst = 1.0
    for i, a in enumerate(lists):
        for b in lists[i + 1:]:
            k = min(len(a), len(b))
            worst = min(worst, ratio(" ".join(a[:k]), " ".join(b[:k])))
    return worst


def uniq(seq):
    """Order-preserving dedup, case-insensitive on strings."""
    out, seen = [], set()
    for x in seq:
        k = x.lower() if isinstance(x, str) else json.dumps(x, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


# ── loaders ──────────────────────────────────────────────────────────────────

def load_hbls():
    p = os.path.join(HERE, "hbls-extraction", "hbls_persons.json")
    return {r["id"]: r for r in json.load(open(p, encoding="utf-8"))}


def load_hgb():
    """Index HGB persons by the Stage-3 node key `name#first_mention_year`.

    The key is not unique (≈3.1k collisions): distinct resolved persons can
    share a name and a first year. Stage 3 merged them into one node, so we
    keep every record under the key and mark the merged person ambiguous.
    """
    p = os.path.join(HERE, "persons_resolved.json")
    idx = defaultdict(list)
    for r in json.load(open(p, encoding="utf-8")):
        if r.get("y"):
            idx[f"{r['n'].strip()}#{r['y'][0]}"].append(r)
    return idx


def load_hls(path, wanted):
    """Stream the HLS export once, keeping only the article ids we need."""
    if not os.path.exists(path):
        return {}
    keep = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["id"] in wanted:
                keep[row["id"]] = {
                    "id": row["id"],
                    "version": row.get("version") or "",
                    "title": (row.get("title") or "").strip(),
                    "family": (row.get("bio.family_name") or "").strip(),
                    "first": (row.get("bio.first_name") or "").strip(),
                    "birth": year_of(row.get("bio.birth_date")),
                    "death": year_of(row.get("bio.death_date")),
                    "gender": (row.get("bio.gender") or "").strip(),
                }
    return keep


def load_gnd():
    p = os.path.join(HERE, "hbls-extraction", "gnd_enrichment.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


# ── merge ────────────────────────────────────────────────────────────────────

def merge(cluster, hbls, hgb, hls, gnd, seq):
    members = cluster["members"]
    hb = [hbls[m["node"][5:]] for m in members
          if m["corpus"] == "hbls" and m["node"][5:] in hbls]
    hl = [hls[m["node"][4:]] for m in members
          if m["corpus"] == "hls" and m["node"][4:] in hls]
    hg_keys = [m["node"][4:] for m in members if m["corpus"] == "hgb"]
    hg = [r for k in hg_keys for r in hgb.get(k, [])]
    gn = [gnd[g] for g in cluster["gnd"] if g in gnd]

    h0 = hb[0] if hb else {}
    l0 = hl[0] if hl else {}
    g0 = gn[0] if gn else {}

    name, name_src = first(("hls", l0.get("title")), ("hbls", h0.get("name")),
                           ("gnd", g0.get("preferredName")),
                           ("hgb", hg[0]["n"] if hg else None))
    surname, _ = first(("hls", l0.get("family")), ("hbls", h0.get("surname")))
    given, _ = first(("hls", l0.get("first")), ("hbls", h0.get("given")))

    birth, birth_src = first(("hls", l0.get("birth")),
                             ("gnd", year_of((g0.get("dateOfBirth") or [None])[0])),
                             ("hbls", h0.get("birth_year")))
    death, death_src = first(("hls", l0.get("death")),
                             ("gnd", year_of((g0.get("dateOfDeath") or [None])[0])),
                             ("hbls", h0.get("death_year")))
    gender, _ = first(("hls", l0.get("gender")),
                      ("gnd", (g0.get("gender") or [None])[0]))

    # occupations: HGB register terms + GND authority roles, kept apart and pooled
    occ_hgb = uniq([o for r in hg for o in r.get("occ", [])])
    roles_gnd = uniq([r for g in gn for r in g.get("roles", [])])

    # mention span across every contributing HGB record
    spans = [r["y"] for r in hg if r.get("y")]
    mention_span = [min(s[0] for s in spans), max(s[-1] for s in spans)] if spans else None

    sources = []
    for r in hb:
        sources.append({"corpus": "hbls", "id": r["id"], "url": r.get("backlink"),
                        "volume": r.get("volume"), "page": r.get("page")})
    for r in hl:
        sources.append({"corpus": "hls", "id": r["id"],
                        "url": hls_url(r["id"], r["version"]), "title": r["title"]})
    for k in hg_keys:
        recs = hgb.get(k, [])
        sources.append({"corpus": "hgb", "id": k,
                        "n_records": len(recs),
                        "n_mentions": sum(r.get("c", 0) for r in recs),
                        "n_dossiers": sum(r.get("d", 0) for r in recs)})
    for g in cluster["gnd"]:
        sources.append({"corpus": "gnd", "id": g,
                        "url": f"https://d-nb.info/gnd/{g}"})
    for q in cluster["wikidata"]:
        sources.append({"corpus": "wikidata", "id": q,
                        "url": f"https://www.wikidata.org/wiki/{q}"})

    same_as = {}
    for g in gn:
        same_as.update(g.get("sameAs") or {})

    conflicts = list(cluster["conflicts"])
    if any(len(hgb.get(k, [])) > 1 for k in hg_keys):
        conflicts.append("hgb_key_ambiguous")

    # Do the source corpora actually agree on the given name? (GND's
    # "Surname, Given" form is excluded — different token order.)
    agree = name_agreement([r["name"] for r in hb] + [r["title"] for r in hl] +
                           [k.rsplit("#", 1)[0] for k in hg_keys])
    if agree is not None and agree < NAME_MIN:
        conflicts.append("name_disagreement")

    rec = {
        "id": f"person:{seq:05d}",
        "cluster_id": cluster["id"],
        "status": "review" if conflicts else "merged",
        "conflicts": conflicts,
        "corpora": cluster["corpora"],
        "name": name,
        "surname": surname,
        "given": given,
        "birth_year": birth,
        "death_year": death,
        "floruit_years": h0.get("floruit_years"),
        "gender": gender,
        "mention_span": mention_span,
        "occupations": uniq(occ_hgb + roles_gnd),
        "occupations_hgb": occ_hgb,
        "roles_gnd": roles_gnd,
        "titles": uniq([t for r in hg for t in r.get("tit", [])]),
        "organisations": uniq([o for r in hg for o in r.get("org", [])]),
        "locations": uniq([o for r in hg for o in r.get("loc", [])]),
        "places": {
            "birth": uniq([p for g in gn for p in g.get("placeOfBirth", [])]),
            "death": uniq([p for g in gn for p in g.get("placeOfDeath", [])]),
            "activity": uniq([p for g in gn for p in g.get("placeOfActivity", [])]),
        },
        "family": uniq([f for r in hg for f in r.get("fam", [])]),
        "kin": uniq([k for r in hg for k in r.get("kin", [])]),
        "dossiers": uniq([d[0] for r in hg for d in r.get("dos", [])]),
        "name_variants": uniq([v for r in hg for v in r.get("v", [])]),
        "publications": uniq([p for g in gn for p in g.get("publications", [])]),
        "authority": {
            "gnd": cluster["gnd"],
            "wikidata": cluster["wikidata"],
            **same_as,
        },
        "bio": h0.get("bio"),
        "name_agreement": agree,
        "provenance": {"name": name_src, "birth": birth_src, "death": death_src},
        "sources": sources,
    }
    return rec


def main():
    global NAME_MIN
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", default="identity_clusters.json")
    ap.add_argument("--hls", default=HLS_DEFAULT)
    ap.add_argument("--out", default="merged_persons.json")
    ap.add_argument("--clean-only", action="store_true",
                    help="emit only conflict-free clusters (skip the review queue)")
    ap.add_argument("--name-min", type=float, default=NAME_MIN,
                    help="given-name agreement below which a cluster is flagged")
    args = ap.parse_args()
    NAME_MIN = args.name_min

    clusters = json.load(open(os.path.join(HERE, args.clusters), encoding="utf-8"))
    hbls, hgb, gnd = load_hbls(), load_hgb(), load_gnd()
    wanted = {m["node"][4:] for c in clusters for m in c["members"]
              if m["corpus"] == "hls"}
    hls = load_hls(args.hls, wanted)

    people = []
    for c in clusters:
        rec = merge(c, hbls, hgb, hls, gnd, len(people) + 1)
        if args.clean_only and rec["status"] != "merged":
            continue
        people.append(rec)

    out = os.path.join(HERE, args.out)
    json.dump(people, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    csv_out = out.rsplit(".", 1)[0] + ".csv"
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "status", "name", "birth", "death", "corpora",
                    "gnd", "wikidata", "n_occupations", "n_dossiers",
                    "n_publications", "conflicts"])
        for p in people:
            w.writerow([p["id"], p["status"], p["name"], p["birth_year"] or "",
                        p["death_year"] or "", "+".join(p["corpora"]),
                        ";".join(p["authority"]["gnd"]),
                        ";".join(p["authority"]["wikidata"]),
                        len(p["occupations"]), len(p["dossiers"]),
                        len(p["publications"]), ";".join(p["conflicts"])])

    # ── report ───────────────────────────────────────────────────────────────
    merged = [p for p in people if p["status"] == "merged"]
    review = [p for p in people if p["status"] == "review"]
    dated = [p for p in merged if p["birth_year"] or p["death_year"]]
    print(f"clusters in            : {len(clusters)}")
    print(f"merged persons emitted : {len(merged)}  -> {os.path.basename(out)}")
    print(f"  with life dates      : {len(dated)}")
    print(f"  with occupations     : {sum(1 for p in merged if p['occupations'])}")
    print(f"  with publications    : {sum(1 for p in merged if p['publications'])}")
    print(f"  with a GND id        : {sum(1 for p in merged if p['authority']['gnd'])}")
    print(f"  3-corpus             : {sum(1 for p in merged if len(p['corpora']) == 3)}")
    print(f"flagged for review     : {len(review)}")
    src = defaultdict(int)
    for p in merged:
        src[p["provenance"]["name"]] += 1
    print(f"name taken from        : {dict(src)}")
    print("\nexamples:")
    for p in sorted(merged, key=lambda p: -len(p["sources"]))[:8]:
        print(f"  {p['name'][:28]:28s} {p['birth_year'] or '?'}–{p['death_year'] or '?'}"
              f"  {'+'.join(p['corpora']):14s} occ={len(p['occupations'])}"
              f" pub={len(p['publications'])} src={len(p['sources'])}")


if __name__ == "__main__":
    main()
