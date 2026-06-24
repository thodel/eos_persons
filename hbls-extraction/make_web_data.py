#!/usr/bin/env python3
"""
make_web_data.py — build a compact JSON for the static HBLS browser tab.

The full article text (hbls_articles.json, 67 MB) is too large to ship to a
static page, so we emit a trimmed index: one entry per article with a short
snippet, plus the clean person records (name + life years) parsed for that
article. Output: ../hbls_web.json (placed in the repo root next to hbls.html).
"""
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNIPPET = 320

articles = json.load(open(os.path.join(HERE, "hbls_articles.json")))
persons = json.load(open(os.path.join(HERE, "hbls_persons.json")))

# index persons by (volume, page, keyword)
by_art = defaultdict(list)
for p in persons:
    by_art[(p["volume"], p["page"], p["keyword"])].append(p)

out = []
for a in articles:
    vol = None
    mvol = re.search(r"band_(\d+)", a["source_file"])
    if mvol:
        vol = int(mvol.group(1))
    members = []
    for p in by_art.get((vol, a["page"], a["keyword"]), []):
        members.append({
            "g": p["given"],
            "b": p["birth_year"],
            "d": p["death_year"],
            "n": p["member_n"],
        })
    members.sort(key=lambda m: (m["n"] is None, m["n"] or 0))
    snip = re.sub(r"\s+", " ", a["content"])[:SNIPPET]
    out.append({
        "k": a["keyword"],
        "v": vol,
        "p": a["page"],
        "s": snip,
        "m": members,
        "url": a["backlink"],
    })

out.sort(key=lambda r: (r["k"], r["v"] or 0, r["p"]))
with open(os.path.join(ROOT, "hbls_web.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

sz = os.path.getsize(os.path.join(ROOT, "hbls_web.json")) / 1e6
npers = sum(len(r["m"]) for r in out)
print(f"wrote ../hbls_web.json : {len(out)} articles, {npers} persons, {sz:.1f} MB")
