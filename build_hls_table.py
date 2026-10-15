#!/usr/bin/env python3
"""
build_hls_table.py — an HLS biography table from Wikidata, in the layout of the
HLS metadata export that the linking scripts were written against.

The linkers (link_hls.py, link_hbls_hls.py, apply_hls_links.py,
build_merged_persons.py, audit_authority_edges.py) read `hls_articles.csv`, a
metadata export of the Historisches Lexikon der Schweiz that is not
redistributable and lives only on the maintainer's machine. To make the link
stage reproducible from public data, this script rebuilds the columns those
scripts use from Wikidata, where every HLS biography is keyed by property P902
(HLS id):

    id, version, title, category, bio.family_name, bio.first_name,
    bio.birth_date, bio.death_date, bio.gender, lexical_class, content_text,
    wikidata_qid, gnd

`category` is always "bio" (only humans are pulled), `version` and
`content_text` are empty (the dated article URL is resolved by the HLS site's
redirect, and the article text is not on Wikidata — the text-mining passes
extract_genealogy.py / extract_spouses.py need the real export).

Source: QLever's public Wikidata SPARQL mirror (fast, no auth); the official
WDQS endpoint is tried if QLever fails.

    python3 build_hls_table.py                       # → hls_bios_wikidata.csv
    python3 build_hls_table.py --tsv cached.tsv      # from a saved QLever TSV
"""
import argparse
import collections
import csv
import re
import sys
import time
import urllib.parse
import urllib.request

OUT = "hls_bios_wikidata.csv"
UA = ("eos-persons-linker/1.0 "
      "(https://github.com/thodel/eos_persons; tobias.hodel@unibe.ch)")
QLEVER = "https://qlever.dev/api/wikidata"
WDQS = "https://query.wikidata.org/sparql"

QUERY = """
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
SELECT ?item ?hls ?label ?b ?d ?gender ?given ?family ?gnd ?desc WHERE {
  ?item wdt:P902 ?hls . ?item wdt:P31 wd:Q5 .
  OPTIONAL { ?item rdfs:label ?label . FILTER(LANG(?label)="de") }
  OPTIONAL { ?item wdt:P569 ?b } OPTIONAL { ?item wdt:P570 ?d }
  OPTIONAL { ?item wdt:P21 ?gender }
  OPTIONAL { ?item wdt:P735 ?g . ?g rdfs:label ?given . FILTER(LANG(?given)="de") }
  OPTIONAL { ?item wdt:P734 ?f . ?f rdfs:label ?family . FILTER(LANG(?family)="de") }
  OPTIONAL { ?item wdt:P227 ?gnd }
  OPTIONAL { ?item schema:description ?desc . FILTER(LANG(?desc)="de") }
}
"""
GENDER = {"Q6581097": "m", "Q6581072": "f"}
COLS = ["id", "version", "title", "category", "bio.family_name", "bio.first_name",
        "bio.birth_date", "bio.death_date", "bio.gender", "lexical_class",
        "content_text", "wikidata_qid", "gnd", "description"]


def fetch_tsv():
    params = urllib.parse.urlencode({"query": QUERY})
    for attempt in range(6):
        try:
            req = urllib.request.Request(f"{QLEVER}?{params}",
                                         headers={"User-Agent": UA,
                                                  "Accept": "text/tab-separated-values"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.read().decode("utf-8")
        except Exception as e:                      # 429 while QLever is busy
            print(f"  QLever attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    print("  falling back to WDQS (1 request)", file=sys.stderr)
    req = urllib.request.Request(f"{WDQS}?{params}",
                                 headers={"User-Agent": UA,
                                          "Accept": "text/tab-separated-values"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read().decode("utf-8")


def strip_lit(v):
    """'"Charles Baud"@de' → 'Charles Baud'; '<…/entity/Q5>' → 'Q5'."""
    v = (v or "").strip()
    if v.startswith("<") and v.endswith(">"):
        return v[1:-1].rsplit("/", 1)[-1]
    m = re.match(r'^"(.*)"(?:@[\w-]+|\^\^<[^>]+>)?$', v, re.S)
    if m:
        return m.group(1).replace('\\"', '"')
    return re.sub(r"@[a-z-]+$", "", v)


def date_of(v):
    """Wikidata xsd:dateTime → 'YYYY-MM-DD' / 'YYYY' (negative years kept)."""
    v = strip_lit(v)
    m = re.match(r"^(-?\d{1,4})-(\d{2})-(\d{2})", v)
    if not m:
        return ""
    y, mo, d = m.groups()
    if mo == "00" or d == "00":
        return y
    return f"{y}-{mo}-{d}"


def first_name_from(label, family, givens):
    """Given-name part: label minus the family name, else the P735 labels."""
    if label and family:
        lab = label
        if lab.endswith(" " + family):
            return lab[: -len(family) - 1].strip()
        i = lab.find(" " + family + " ")
        if i > 0:                        # 'Hans Rudolf Wettstein der Ältere'
            return lab[:i].strip()
    if givens:
        return " ".join(givens)
    if label and not family:
        toks = label.split()
        return " ".join(toks[:-1]) if len(toks) > 1 else ""
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", help="use a saved QLever TSV instead of querying")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if args.tsv:
        txt = open(args.tsv, encoding="utf-8").read()
    else:
        print("Querying Wikidata for every human with an HLS id (P902) …", file=sys.stderr)
        txt = fetch_tsv()
    rows = list(csv.DictReader(txt.splitlines(), delimiter="\t"))
    print(f"  {len(rows):,} result rows", file=sys.stderr)

    by_hls = collections.defaultdict(lambda: {
        "qids": [], "labels": [], "b": [], "d": [], "gender": [],
        "given": [], "family": [], "gnd": [], "desc": []})
    for r in rows:
        hid = strip_lit(r["?hls"])
        if not hid:
            continue
        hid = hid.zfill(6)
        g = by_hls[hid]
        for key, col, fn in (("qids", "?item", strip_lit), ("labels", "?label", strip_lit),
                             ("b", "?b", date_of), ("d", "?d", date_of),
                             ("gender", "?gender", strip_lit), ("given", "?given", strip_lit),
                             ("family", "?family", strip_lit), ("gnd", "?gnd", strip_lit),
                             ("desc", "?desc", strip_lit)):
            v = fn(r.get(col))
            if v and v not in g[key]:
                g[key].append(v)

    out = []
    for hid in sorted(by_hls):
        g = by_hls[hid]
        label = g["labels"][0] if g["labels"] else ""
        family = g["family"][0] if g["family"] else ""
        if not family and label:
            family = label.split()[-1] if len(label.split()) > 1 else ""
        first = first_name_from(label, family, g["given"])
        # prefer the most precise date; several values → earliest full date
        b = sorted(g["b"], key=lambda s: (-len(s), s))[0] if g["b"] else ""
        d = sorted(g["d"], key=lambda s: (-len(s), s))[0] if g["d"] else ""
        out.append({
            "id": hid, "version": "", "title": label, "category": "bio",
            "bio.family_name": family, "bio.first_name": first,
            "bio.birth_date": b, "bio.death_date": d,
            "bio.gender": GENDER.get(g["gender"][0], "") if g["gender"] else "",
            "lexical_class": "", "content_text": "",
            "wikidata_qid": g["qids"][0] if g["qids"] else "",
            "gnd": g["gnd"][0] if g["gnd"] else "",
            "description": g["desc"][0] if g["desc"] else "",
        })

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    dated = sum(1 for r in out if r["bio.birth_date"] or r["bio.death_date"])
    era = sum(1 for r in out
              if any(1300 <= int(y) <= 1720 for y in
                     re.findall(r"^-?\d{3,4}", r["bio.birth_date"] + "\n" + r["bio.death_date"],
                                re.M)))
    print(f"→ {args.out}: {len(out):,} HLS biographies ({dated:,} with life dates, "
          f"{era:,} born/died 1300–1720, {sum(1 for r in out if r['gnd']):,} with GND)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
