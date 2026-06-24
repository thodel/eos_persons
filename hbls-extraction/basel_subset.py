#!/usr/bin/env python3
"""
basel_subset.py — isolate the HBLS person records connected to Basel.

A person is "Basel-connected" if the article they belong to mentions Basel (so
whole families are kept together) or their own bio text does. This is the first
evaluation slice for HBLS↔HGB linking, since the EOS/HGB corpus is the
Historisches Grundbuch *Basel*. See DEDUP_PLAN.md.

    python3 basel_subset.py   # -> hbls_persons_basel.csv / .json
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BASEL = re.compile(r"\bBasel\b|\bbasler\b|\bbaslerisch", re.I)

persons = json.load(open(os.path.join(HERE, "hbls_persons.json")))
articles = json.load(open(os.path.join(HERE, "hbls_articles.json")))

art_basel = set()
for a in articles:
    m = re.search(r"band_(\d+)", a["source_file"])
    vol = int(m.group(1)) if m else None
    if BASEL.search(a["content"]):
        art_basel.add((vol, a["page"], a["keyword"]))

hits = []
for p in persons:
    key = (p["volume"], p["page"], p["keyword"])
    if key in art_basel:
        src = "article"
    elif BASEL.search(p.get("bio", "")):
        src = "bio"
    else:
        continue
    r = dict(p)
    r["basel_source"] = src
    hits.append(r)

cols = ["id", "name", "given", "surname", "keyword", "birth_year", "death_year",
        "floruit_years", "volume", "page", "basel_source", "backlink"]
with open(os.path.join(HERE, "hbls_persons_basel.csv"), "w", newline="",
          encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for h in hits:
        r = dict(h)
        if r.get("floruit_years"):
            r["floruit_years"] = "-".join(map(str, r["floruit_years"]))
        w.writerow(r)
json.dump(hits, open(os.path.join(HERE, "hbls_persons_basel.json"), "w"),
          ensure_ascii=False, indent=1)

print(f"Basel-connected HBLS persons: {len(hits)}")
print(f"  via article mention: {sum(1 for h in hits if h['basel_source']=='article')}")
print(f"  via own bio only   : {sum(1 for h in hits if h['basel_source']=='bio')}")
print(f"  distinct surnames  : {len({h['surname'] for h in hits})}")
