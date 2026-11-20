#!/usr/bin/env python3
"""
fetch_wikidata_dates.py — birth and death dates of every HLS biography on
Wikidata, with their precision.

hls_bios_wikidata.csv keeps one date per person and no precision, so "15th
century" (stored as 1450-01-01 or 1500-01-01) looks like a year. For the
cross-check of life dates (lifedates.py) the precision matters: only a date
given to the year or better is a second opinion on the HLS.

    python3 fetch_wikidata_dates.py        # → hls_wikidata_dates.csv

One row per date statement: hls_id, qid, prop (b|d), year, precision (Wikidata's
scale: 7 century, 8 decade, 9 year, 10 month, 11 day), rank.
"""
import csv
import json
import sys
import urllib.parse
import urllib.request

OUT = "hls_wikidata_dates.csv"
QLEVER = "https://qlever.dev/api/wikidata"
QUERY = """
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?item ?hls ?prop ?t ?prec ?rank WHERE {
  ?item wdt:P902 ?hls . ?item wdt:P31 wd:Q5 .
  VALUES (?prop ?pp ?pv) { ("b" p:P569 psv:P569) ("d" p:P570 psv:P570) }
  ?item ?pp ?st . ?st ?pv ?v .
  ?v wikibase:timeValue ?t ; wikibase:timePrecision ?prec .
  ?st wikibase:rank ?rank .
}
"""


def main():
    req = urllib.request.Request(
        QLEVER, data=urllib.parse.urlencode({"query": QUERY}).encode(),
        headers={"Accept": "application/sparql-results+json",
                 "User-Agent": "hls-life-dates/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.load(r)["results"]["bindings"]
    rows = set()
    for b in res:
        t = b["t"]["value"]
        neg = t.startswith("-")
        year = int(t.lstrip("-")[:4]) * (-1 if neg else 1)
        rank = b["rank"]["value"].rsplit("#", 1)[-1].replace("Rank", "").lower()
        if rank == "deprecated":
            continue
        rows.add((b["hls"]["value"].zfill(6), b["item"]["value"].rsplit("/", 1)[-1],
                  b["prop"]["value"], year, int(b["prec"]["value"]), rank))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hls_id", "qid", "prop", "year", "precision", "rank"])
        w.writerows(sorted(rows))
    n = len({r[0] for r in rows})
    print(f"→ {OUT}: {len(rows):,} date statements for {n:,} HLS biographies",
          file=sys.stderr)


if __name__ == "__main__":
    main()
