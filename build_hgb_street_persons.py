#!/usr/bin/env python3
"""
build_hgb_street_persons.py — street-level person index from the DHBern
*Economies of Space: Full Annotated Dataset*, with the HGB identity
resolution applied street by street.

The DHBern release (github.com/DHBern/economies-of-space-automatically-annotated-data,
read-only here) ships one XML per street (street_data/street_HGB_1_NNN.xml):
series = street, collection = dossier (with LV95 point), document = entry
with nested spans. Person references are <span element="reference"
class="per"> with a <span element="head" class="nam"> child; occupations,
titles and kin sit in appositions, a <span class="dead"> apposition ("selig",
"wilent") marks the person as deceased; event roles point at span ids.

Mentions are collected per street and then resolved into persons with the
same rules the corpus-wide index uses, scoped to the street:

  1. within a dossier, a name that is an unambiguous token-subset of exactly
     one other name in that dossier is the same person ("Hans Gysler" ⊂
     "Hans Heinrich Gysler"), 80-year cap          (build_data.tokens_subset)
  2. dossier clusters are binned into 80-year lifespans and split where live
     mentions follow a deceased mention            (build_data, step 2/3b)
  3. across the dossiers of ONE street, clusters with the same canonical
     key (≥2 tokens, abbreviations expanded) merge under the lifespan cap
     and the deceased constraint                   (build_data, step 4)
  4. across the street, clusters whose surnames are phonetically equal
     (Kölner Phonetik) with the same canonical given-name sequence merge
     when the raw surnames are ≥ 0.6 similar, the joint span fits one
     lifespan and nobody is first seen alive > 15 years after a recorded
     death. In dedupe_corpus.py this pass needs a shared dossier /
     occupation / location as context anchor; here the street *is* the
     anchor (the point of the street-level index), so it is not required.
                                                   (dedupe_corpus.koelner …)

Nothing merges across streets: a name on two streets stays two records.
The corpus-wide index (persons_resolved.json) remains the place where
cross-street identity is decided.

    python3 build_hgb_street_persons.py [--src ../economies-of-space-automatically-annotated-data/street_data]
        -> hgb_street_persons.json (gitignored: regenerable, ~50 MB)

Record:
  {"id": "HGB_1_028#17", "name": "Hans Jacob Rudin", "variants": [...],
   "street_id": "HGB_1_028", "street": "Freie Strasse", "n": 7, "n_clusters": 2,
   "years": [1540, 1552], "dead_year": null, "dossiers": ["HGB_1_028_012", ...],
   "location": "POINT(2611... 1267...)", "occ": ["schneider"], "roles": {"owner": 3},
   "merged_by": ["subset", "phonetic"]}
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

from build_data import clean_tokens, canonical_key, tokens_subset, UF
from dedupe_corpus import koelner, given_seq, surname_raw

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "..", "economies-of-space-automatically-annotated-data", "street_data")
OUT = os.path.join(HERE, "hgb_street_persons.json")
MIN_CONF = 0.5
LIFESPAN = 80
DEAD_GRACE = 15
SURNAME_SIM = 0.6


# ── 1. mentions from the street XML ──────────────────────────────────────────

def person_mentions(doc):
    """Yield (span_id, name, occupations, deceased) per singular specific person."""
    spans = doc.find("spans")
    if spans is None:
        return
    for ref in spans.iter("span"):
        if ref.get("element") != "reference" or ref.get("class") != "per":
            continue
        if ref.get("numerus") != "sgl" or ref.get("specificity") != "spc":
            continue
        try:
            if float(ref.get("confidence", "1")) < MIN_CONF:
                continue
        except ValueError:
            pass
        head = next((c for c in ref if c.get("element") == "head" and c.get("class") == "nam"), None)
        if head is None:
            continue
        name = re.sub(r"\s*\(\s*sic\s*\)\s*|\s*[.,;:]+$", "", head.get("text", "")).strip()
        if not name:
            continue
        occ, dead = [], False
        for ap in ref:
            if ap.get("element") != "appo":
                continue
            if ap.get("class") == "dead":
                dead = True
            elif ap.get("class") == "occ":
                for h in ap.iter("span"):
                    if h.get("element") == "head" and h.get("class") == "occ":
                        n = h.get("norm", "")
                        occ.append(n if n and n != "unk" else h.get("text", ""))
        yield ref.get("id"), name, occ, dead


def roles_by_span(doc):
    out = collections.defaultdict(collections.Counter)
    egs = doc.find("eventGroups")
    if egs is None:
        return out
    for role in egs.iter("role"):
        out[role.get("ref")][role.get("role")] += 1
    return out


def read_street(path):
    """(street_id, street, mentions) for one street file; iterparse, 30 MB files."""
    street_id = street = None
    coll_meta, mentions = {}, []
    for ev, el in ET.iterparse(path, events=("start", "end")):
        if ev == "start" and el.tag == "series":
            street_id, street = el.get("id"), el.get("name")
        elif ev == "end" and el.tag == "metadata" and el.find("location") is not None:
            coll_meta = {"location": (el.findtext("location") or "").strip()}
        elif ev == "end" and el.tag == "document":
            meta = el.find("metadata")
            try:
                year = int(meta.findtext("year"))
            except (TypeError, ValueError):
                year = None
            dossier = meta.findtext("dossier_id") or ""
            source = meta.findtext("source") or ""
            roles = roles_by_span(el)
            for sid, name, occ, dead in person_mentions(el):
                mentions.append({
                    "name": name, "year": year, "dossier": dossier, "dead": dead,
                    "occ": [o.lower() for o in occ if o], "roles": roles.get(sid, {}),
                    "source": source, "location": coll_meta.get("location", ""),
                })
            el.clear()
        elif ev == "end" and el.tag == "collection":
            el.clear()
    return street_id, street, mentions


# ── 2. street-scoped identity resolution ─────────────────────────────────────

def _pick_canonical(names):
    def score(n):
        toks = clean_tokens(n)
        abbr = sum(1 for t in toks if t.endswith(".") or len(t) <= 2)
        return (len(toks) - abbr, len(n))
    return max(names, key=score)


def _span_ok(entries, extra):
    years = [y for e in entries for y in e["years"] if y] + [y for y in extra["years"] if y]
    return not years or max(years) - min(years) <= LIFESPAN


def _dead_ok(entries, p):
    cluster_dead = min((e["dead_year"] for e in entries if e["dead_year"]), default=None)
    if cluster_dead and any(y > cluster_dead for y in p["live_years"]):
        return False
    if p["dead_year"]:
        if any(y > p["dead_year"] for e in entries for y in e["live_years"]):
            return False
    return True


def dossier_clusters(mentions):
    """Steps 1–2: subset-union inside each dossier, 80-year bins, death split."""
    uf = UF()
    by_dossier = collections.defaultdict(list)
    for m in mentions:
        by_dossier[m["dossier"]].append(m)
    for dossier, grp in by_dossier.items():
        name_years = collections.defaultdict(list)
        for m in grp:
            if m["year"]:
                name_years[m["name"]].append(m["year"])
        names = sorted({m["name"] for m in grp}, key=lambda n: -len(clean_tokens(n)))
        for a in names:
            supersets = [b for b in names if b != a and tokens_subset(a, b)]
            if len(supersets) != 1:
                continue
            ys = name_years.get(a, []) + name_years.get(supersets[0], [])
            if ys and max(ys) - min(ys) > LIFESPAN:
                continue
            uf.union((dossier, a), (dossier, supersets[0]))
    binned = collections.defaultdict(list)
    for m in mentions:
        root = uf.find((m["dossier"], m["name"]))
        binned[(root, (m["year"] or 0) // LIFESPAN)].append(m)
    out = []
    for (root, _), rows in binned.items():
        names = sorted({r["name"] for r in rows})
        years = [r["year"] for r in rows if r["year"]]
        dead_years = [r["year"] for r in rows if r["year"] and r["dead"]]
        live_years = [r["year"] for r in rows if r["year"] and not r["dead"]]
        out.append({
            "canonical": _pick_canonical(names), "variants": names,
            "dossier": root[0], "rows": rows,
            "years": [min(years), max(years)] if years else [0, 0],
            "dead_year": min(dead_years) if dead_years else None,
            "live_years": live_years, "ckey": canonical_key(_pick_canonical(names)),
            "merged_by": {"subset"} if len(names) > 1 else set(),
        })
    # step 3b: live mentions after the earliest deceased mention = later person
    split = []
    for p in out:
        late = [y for y in p["live_years"] if p["dead_year"] and y > p["dead_year"]]
        if not late:
            split.append(p)
            continue
        early = dict(p, live_years=[y for y in p["live_years"] if y <= p["dead_year"]])
        early["rows"] = [r for r in p["rows"] if r["dead"] or (r["year"] or 0) <= p["dead_year"]]
        early["years"] = [min(early["live_years"] + [p["dead_year"]]), max(early["live_years"] + [p["dead_year"]])]
        late_p = dict(p, dead_year=None, live_years=late, years=[min(late), max(late)],
                      merged_by=set(p["merged_by"]) | {"death-split"})
        late_p["rows"] = [r for r in p["rows"] if not r["dead"] and (r["year"] or 0) > p["dead_year"]]
        split.extend([early, late_p])
    split.sort(key=lambda p: (p["years"][0], p["dead_year"] or 9999))
    return split


def resolve_street(mentions):
    """Steps 3–4: merge dossier clusters across the street. Returns groups."""
    clusters = dossier_clusters(mentions)
    # step 3: canonical-key grouping (≥2 tokens) with span + deceased guards
    groups = []
    by_key = collections.defaultdict(list)
    for p in clusters:
        if len(p["ckey"].split()) < 2:
            groups.append([p])
            continue
        placed = False
        for g in by_key[p["ckey"]]:
            if _span_ok(g, p) and _dead_ok(g, p):
                g.append(p)
                placed = True
                break
        if not placed:
            g = [p]
            by_key[p["ckey"]].append(g)
            groups.append(g)
    # step 4: phonetic surname + canonical given sequence, street as anchor
    meta = []
    for g in groups:
        canon = _pick_canonical([p["canonical"] for p in g])
        surn = surname_raw(canon) or ""
        meta.append({"kp": koelner(surn) if surn else "", "gs": given_seq(canon), "surn": surn})
    blocks = collections.defaultdict(list)
    for i, mt in enumerate(meta):
        if mt["kp"] and mt["gs"] and len(clean_tokens(groups[i][0]["canonical"])) >= 2:
            blocks[(mt["kp"], mt["gs"])].append(i)
    uf = UF()
    gy = {i: [min(p["years"][0] for p in g), max(p["years"][1] for p in g)] for i, g in enumerate(groups)}
    gdead = {i: min((p["dead_year"] for p in g if p["dead_year"]), default=None) for i, g in enumerate(groups)}
    glive = {i: max((y for p in g for y in p["live_years"]), default=0) for i, g in enumerate(groups)}
    for members in blocks.values():
        # every pair, not the star of dedupe_corpus: if the first member is a
        # dead earlier namesake, the later two must still be compared
        for ai in range(len(members)):
            for bi in range(ai + 1, len(members)):
                a, b = members[ai], members[bi]
                if meta[a]["surn"] != meta[b]["surn"] and \
                   SequenceMatcher(None, meta[a]["surn"], meta[b]["surn"]).ratio() < SURNAME_SIM:
                    continue
                ra, rb = uf.find(a), uf.find(b)
                if ra == rb:
                    continue
                lo, hi = min(gy[ra][0], gy[rb][0]), max(gy[ra][1], gy[rb][1])
                if hi - lo > LIFESPAN:
                    continue
                dead = min([d for d in (gdead[ra], gdead[rb]) if d], default=None)
                if dead and lo > dead + DEAD_GRACE:
                    continue
                # same deceased constraint as step 3: nobody is seen alive after
                # the year a record already calls them dead
                if dead and max(glive[ra], glive[rb]) > dead:
                    continue
                uf.union(ra, rb)
                r = uf.find(ra)
                gy[r] = [lo, hi]
                gdead[r] = dead
                glive[r] = max(glive[ra], glive[rb])
    merged = collections.defaultdict(list)
    for i, g in enumerate(groups):
        merged[uf.find(i)].append(g)
    out = []
    for parts in merged.values():
        entries = [p for g in parts for p in g]
        if len(parts) > 1:
            for p in entries:
                p["merged_by"] = set(p["merged_by"]) | {"phonetic"}
        if any(len(g) > 1 for g in parts):
            for g in parts:
                if len(g) > 1:
                    for p in g:
                        p["merged_by"] = set(p["merged_by"]) | {"canonical-key"}
        out.append(entries)
    return out


def emit(street_id, street, groups):
    records = []
    for n, entries in enumerate(groups, 1):
        rows = [r for e in entries for r in e["rows"]]
        variants = collections.Counter(r["name"] for r in rows)
        years = [r["year"] for r in rows if r["year"]]
        dossiers = collections.Counter(r["dossier"] for r in rows)
        occ = collections.Counter(o for r in rows for o in r["occ"])
        roles = collections.Counter()
        sources = collections.Counter(r["source"] for r in rows)
        for r in rows:
            roles.update(r["roles"])
        loc = collections.Counter(r["location"] for r in rows if r["location"])
        dead = [e["dead_year"] for e in entries if e["dead_year"]]
        records.append({
            "id": f"{street_id}#{n}",
            "name": _pick_canonical([e["canonical"] for e in entries]),
            "variants": [v for v, _ in variants.most_common(10)],
            "street_id": street_id, "street": street,
            "n": len(rows), "n_clusters": len(entries),
            "years": [min(years), max(years)] if years else None,
            "dead_year": min(dead) if dead else None,
            "dossiers": [d for d, _ in dossiers.most_common()],
            "location": loc.most_common(1)[0][0] if loc else "",
            "occ": [o for o, _ in occ.most_common(6)],
            "roles": dict(roles.most_common()),
            "sources": dict(sources.most_common(4)),
            "merged_by": sorted(set().union(*[e["merged_by"] for e in entries])),
        })
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.src, "street_HGB_*.xml")))
    if not files:
        sys.exit(f"no street_HGB_*.xml under {a.src}")
    out, n_mentions = [], 0
    for i, f in enumerate(files, 1):
        street_id, street, mentions = read_street(f)
        groups = resolve_street(mentions)
        recs = emit(street_id, street, groups)
        out.extend(recs)
        n_mentions += len(mentions)
        print(f"[{i}/{len(files)}] {street_id} {street}: {len(mentions)} mentions -> "
              f"{len(recs)} persons", file=sys.stderr)
    out.sort(key=lambda r: (r["street_id"], -r["n"], r["name"]))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    merged = sum(1 for r in out if r["n_clusters"] > 1)
    print(f"{n_mentions} mentions -> {len(out)} street-level persons "
          f"({merged} merged from several clusters) -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
