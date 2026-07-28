#!/usr/bin/env python3
"""
audit_authority_edges.py — verify the GND/Wikidata edges Stage 3 trusts most.

`build_identity_clusters.py` treats a shared authority id as its strongest merge
signal: two records pointing at the same `gnd:`/`wd:` node collapse into one
person transitively, with no name or date check. For HGB records those ids are
not independently sourced — `enrich_wikidata.py` assigns them straight from the
HLS article id (`p["wd"] = facts[p["hls"]["id"]]`), and that HLS id comes from
`apply_hls_links.py` picking a winner out of `link_candidates_hls.csv`.

So every HGB authority edge rests entirely on one HGB↔HLS name match. If that
match is wrong, two different people are fused and nothing downstream notices.
This script re-derives what `apply_hls_links.py` would accept from the *current*
candidates file and classifies each baked-in link:

  confirmed  the same HLS id still wins
  changed    a different HLS id now wins   -> the authority id is for someone else
  revoked    nothing is accepted any more  -> the authority id is unsupported

It also scores each surviving link's HGB name against the HLS title with the
fixed `given_ratio`, so links that are merely *stale* are separated from links
that were never plausible.

    python3 audit_authority_edges.py
    python3 audit_authority_edges.py --write-clean   # drop unsupported hls/wd
"""
import csv
import json
import argparse
import collections

from link_hls import given_key, given_ratio, split_name, norm_token, ratio
from apply_hls_links import MIN_SCORE, MARGIN

csv.field_size_limit(10_000_000)


def accepted_links(path, min_score, margin):
    """Re-run apply_hls_links.py's winner selection over a candidates file."""
    groups = collections.defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups[(r["hgb_name"], r["hgb_year_min"], r["hgb_year_max"])].append(r)
    out = {}
    for key, cands in groups.items():
        cands.sort(key=lambda r: -float(r["score"]))
        top = cands[0]
        if float(top["score"]) < min_score:
            continue
        if len(cands) > 1 and float(top["score"]) - float(cands[1]["score"]) < margin:
            continue
        out[key] = top
    return out


def hls_bio_names(path, wanted):
    """id -> "first family" from the HLS bio fields.

    The article *title* is not a reliable name: for ~0.1% of bios it drops a
    given name the record itself carries ("Konrad Fässler" for bio.first_name
    "Johann Konrad"), which would read as a false given-name conflict.
    """
    out = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["id"] in wanted:
                first = (row.get("bio.first_name") or "").strip()
                fam = (row.get("bio.family_name") or "").strip()
                out[row["id"]] = f"{first} {fam}".strip() or row.get("title", "")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persons", default="persons_resolved.json")
    ap.add_argument("--candidates", default="link_candidates_hls.csv")
    ap.add_argument("--hls", default="/Users/TH_1/Documents/HLS/hls_articles.csv")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--margin", type=float, default=MARGIN)
    ap.add_argument("--name-min", type=float, default=0.6,
                    help="given-name agreement below which a link is implausible")
    ap.add_argument("--write-clean", action="store_true",
                    help="strip hls/wd/kin from persons whose link no longer holds")
    args = ap.parse_args()

    persons = json.load(open(args.persons, encoding="utf-8"))
    now = accepted_links(args.candidates, args.min_score, args.margin)

    linked = [p for p in persons if p.get("hls")]
    bio_name = hls_bio_names(args.hls, {p["hls"]["id"] for p in linked})
    verdict = collections.Counter()
    rows = []
    for p in linked:
        y = p.get("y") or []
        key = (p["n"], str(y[0]), str(y[1])) if y else None
        top = now.get(key)
        old_id = p["hls"]["id"]
        if top is None:
            v = "revoked"
            title, score = "", ""
        elif top["hls_id"] != old_id:
            v = "changed"
            title, score = top["hls_title"], top["score"]
        else:
            v = "confirmed"
            title, score = top["hls_title"], top["score"]
        # plausibility of the link as recorded, under the fixed comparison
        gr = given_ratio(given_key(split_name(p["n"])[0]),
                         given_key(split_name(bio_name.get(old_id,
                                                           p["hls"]["t"]))[0]))
        verdict[v] += 1
        rows.append({
            "verdict": v, "hgb_name": p["n"],
            "hgb_year_min": y[0] if y else "", "hgb_year_max": y[1] if y else "",
            "old_hls_id": old_id, "old_hls_title": p["hls"]["t"],
            "new_hls_id": top["hls_id"] if top else "", "new_hls_title": title,
            "new_score": score, "given_agreement": round(gr, 3),
            "gnd": p.get("wd", {}).get("gnd", ""),
            "wikidata": p.get("wd", {}).get("qid", ""),
            "has_kin": bool(p.get("kin")),
        })

    with open("audit_authority_edges.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["verdict"], r["given_agreement"])))

    # ── report ───────────────────────────────────────────────────────────────
    bad = [r for r in rows if r["verdict"] != "confirmed"]
    weak = [r for r in rows if r["given_agreement"] < args.name_min]
    with_auth = [r for r in bad if r["gnd"] or r["wikidata"]]
    print(f"HGB persons carrying an HLS link : {len(linked)}")
    for v in ("confirmed", "changed", "revoked"):
        print(f"  {v:9s} : {verdict[v]}")
    print(f"\nunsupported links that carry an authority id : {len(with_auth)}")
    print(f"  ...of which also propagated kinship (kin)   : "
          f"{sum(1 for r in with_auth if r['has_kin'])}")
    print(f"links failing the given-name check (<{args.name_min}) : {len(weak)}")
    print(f"  ...still counted 'confirmed'                : "
          f"{sum(1 for r in weak if r['verdict'] == 'confirmed')}")
    print("\n-> audit_authority_edges.csv")

    print("\nlowest given-name agreement among confirmed links "
          f"(anything ≥ {args.name_min} is a permitted missing middle name):")
    for r in sorted([r for r in rows if r["verdict"] == "confirmed"],
                    key=lambda r: r["given_agreement"])[:10]:
        print(f"  {r['given_agreement']:.2f}  {r['hgb_name'][:30]:30s} "
              f"=> {r['old_hls_title'][:32]:32s} gnd={r['gnd'] or '-'}")

    if args.write_clean:
        drop = {(r["hgb_name"], str(r["hgb_year_min"]), str(r["hgb_year_max"]))
                for r in bad}
        n = 0
        for p in persons:
            y = p.get("y") or []
            if y and (p["n"], str(y[0]), str(y[1])) in drop:
                for f in ("hls", "wd", "kin"):
                    p.pop(f, None)
                n += 1
        json.dump(persons, open(args.persons, "w", encoding="utf-8"),
                  separators=(",", ":"), ensure_ascii=False)
        print(f"\nstripped hls/wd/kin from {n} persons -> {args.persons}")


if __name__ == "__main__":
    main()
