#!/usr/bin/env python3
"""
enrich_wikidata.py — enrich HLS-linked HGB persons with Wikidata statements.

Wikidata carries the HLS article id as property P902, so our existing HLS links
give a direct bridge to Wikidata QIDs. For every linked person this script
batches a SPARQL query (HLS id → item) and pulls structured, identifier-backed
facts:

  QID, birth/death dates, image, father/mother/spouse(s)/child(ren) (as labels),
  occupations, and the GND authority id.

These are written as a `wd` field on persons_resolved.json. Unlike the prose
extraction in extract_genealogy.py, the kin here come from Wikidata's typed
statements — a verification/complement to the HLS-text parse.

Runs locally against the public WDQS endpoint with a descriptive User-Agent
(required, else 403). No MCP needed.
"""
import re
import json
import time
import urllib.parse
import urllib.request

PERSONS = "persons_resolved.json"
WDQS = "https://query.wikidata.org/sparql"
UA = "hgb-hls-linker/1.0 (https://github.com/thodel/eos_persons; tobiashodel@gmail.com)"
CHUNK = 515   # WDQS is rate-limiting (1 req/min) — keep request count minimal

QUERY = """
SELECT ?hls ?item ?birth ?death ?img
  (GROUP_CONCAT(DISTINCT ?fatherL; separator="|") AS ?fathers)
  (GROUP_CONCAT(DISTINCT ?motherL; separator="|") AS ?mothers)
  (GROUP_CONCAT(DISTINCT ?spouseL; separator="|") AS ?spouses)
  (GROUP_CONCAT(DISTINCT ?childL;  separator="|") AS ?children)
  (GROUP_CONCAT(DISTINCT ?occL;    separator="|") AS ?occs)
  (GROUP_CONCAT(DISTINCT ?gnd;     separator="|") AS ?gnds)
WHERE {
  VALUES ?hls { %s }
  ?item wdt:P902 ?hls.
  OPTIONAL { ?item wdt:P569 ?birth. }
  OPTIONAL { ?item wdt:P570 ?death. }
  OPTIONAL { ?item wdt:P18  ?img. }
  OPTIONAL { ?item wdt:P227 ?gnd. }
  OPTIONAL { ?item wdt:P22 ?father. ?father rdfs:label ?fatherL. FILTER(lang(?fatherL) IN ("de","en")) }
  OPTIONAL { ?item wdt:P25 ?mother. ?mother rdfs:label ?motherL. FILTER(lang(?motherL) IN ("de","en")) }
  OPTIONAL { ?item wdt:P26 ?spouse. ?spouse rdfs:label ?spouseL. FILTER(lang(?spouseL) IN ("de","en")) }
  OPTIONAL { ?item wdt:P40 ?child.  ?child  rdfs:label ?childL.  FILTER(lang(?childL)  IN ("de","en")) }
  OPTIONAL { ?item wdt:P106 ?occ.   ?occ    rdfs:label ?occL.    FILTER(lang(?occL)    = "de") }
}
GROUP BY ?hls ?item ?birth ?death ?img
"""


def run_sparql(query, retries=6):
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            WDQS, data=body,
            headers={"User-Agent": UA, "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 65
                print(f"    429 rate-limited; waiting {wait}s "
                      f"(attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                continue
            if attempt == retries - 1:
                raise
            time.sleep(5)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5)


def year(s):
    m = re.match(r"(-?\d{1,4})", s or "")
    return int(m.group(1)) if m else None


def split_names(s):
    """Dedup a '|'-joined label list, dropping QID-looking leftovers."""
    out, seen = [], set()
    for x in (s or "").split("|"):
        x = x.strip()
        if not x or re.fullmatch(r"Q\d+", x):
            continue
        k = x.lower()
        if k not in seen:
            seen.add(k); out.append(x)
    return out


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))
    hls_ids = sorted({p["hls"]["id"] for p in persons if p.get("hls")})
    print(f"{len(hls_ids)} distinct HLS ids to look up on Wikidata")

    facts = {}
    for i in range(0, len(hls_ids), CHUNK):
        chunk = hls_ids[i:i + CHUNK]
        values = " ".join(f'"{h}"' for h in chunk)
        rows = run_sparql(QUERY % values)
        for r in rows:
            hid = r["hls"]["value"]
            qid = r["item"]["value"].rsplit("/", 1)[-1]
            wd = {"qid": qid}
            if r.get("birth"):
                wd["b"] = year(r["birth"]["value"])
            if r.get("death"):
                wd["d"] = year(r["death"]["value"])
            if r.get("img"):
                wd["img"] = r["img"]["value"]
            for src, dst in (("fathers", "father"), ("mothers", "mother"),
                             ("spouses", "sp"), ("children", "child"),
                             ("occs", "occ")):
                vals = split_names(r.get(src, {}).get("value", ""))
                if vals:
                    wd[dst] = vals
            if r.get("gnds", {}).get("value"):
                g = r["gnds"]["value"].split("|")[0].strip()
                if g:
                    wd["gnd"] = g
            facts[hid] = wd
        print(f"  …{min(i + CHUNK, len(hls_ids))}/{len(hls_ids)} ids, "
              f"{len(facts)} items resolved")

    # attach to every linked person sharing that HLS id
    n = nf = ns = 0
    for p in persons:
        if p.get("hls") and p["hls"]["id"] in facts:
            p["wd"] = facts[p["hls"]["id"]]
            n += 1
            if "father" in p["wd"] or "mother" in p["wd"]:
                nf += 1
            if "sp" in p["wd"]:
                ns += 1

    json.dump(persons, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

    print(f"\n→ {len(facts)}/{len(hls_ids)} HLS ids resolved to Wikidata items")
    print(f"   wrote `wd` to {n} persons  (parents: {nf}, spouses: {ns})")
    print("\nExamples:")
    shown = 0
    for p in persons:
        wd = p.get("wd")
        if wd and ("father" in wd or "sp" in wd):
            print(f"  {p['n']} = {wd['qid']} ({wd.get('b','?')}–{wd.get('d','?')}) "
                  f"Vater={wd.get('father',['–'])[0]} ⚭ {','.join(wd.get('sp',['–']))}")
            shown += 1
            if shown >= 12:
                break


if __name__ == "__main__":
    main()
