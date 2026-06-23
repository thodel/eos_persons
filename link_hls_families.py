#!/usr/bin/env python3
"""
link_hls_families.py — link HLS *family* articles (category "fam") to the HGB
surname-families in families_index.json, and write the links back.

HLS family articles are titled by surname (e.g. "Iselin", "Keller ZH"); they
carry no birth/death dates, so matching is by normalized surname with a Basel
constraint to avoid linking same-named families from other cantons:

  accept when the HGB surname matches the article's surname AND either
    • the article text mentions Basel, or
    • exactly one HLS family article carries that surname (unambiguous).

Links use the dated online HLS pattern
  https://hls-dhs-dss.ch/de/articles/<id>/<version>/
and are attached to families_index.json entries (field `hls`).
"""
import re
import csv
import json
import unicodedata
import collections

csv.field_size_limit(10_000_000)

HLS = "/Users/TH_1/Documents/HLS/hls_articles.csv"
FAM_INDEX = "families_index.json"
FAM_GRAPH = "families_graph.json"

CANTONS = {"zh", "be", "lu", "ur", "sz", "ow", "nw", "gl", "zg", "fr", "so",
           "bs", "bl", "sh", "ar", "ai", "sg", "gr", "ag", "tg", "ti", "vd",
           "vs", "ne", "ge", "ju"}
PARTICLES = {"von", "vom", "van", "de", "zur", "zum", "im"}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    return strip_accents(re.sub(r"[^\wäöü]", "", s.lower()))


def article_surname(title):
    """Extract the bare surname from an HLS family-article title."""
    t = title.split(",")[0]                       # "Keller ZH, vom Steinbock"
    t = re.sub(r"\b(Familie|Geschlecht|jüngeres|älteres|family)\b", "", t,
               flags=re.I)
    toks = [w for w in t.split() if w]
    # drop trailing canton codes
    toks = [w for w in toks if norm(w) not in CANTONS]
    # drop leading particles
    while toks and norm(toks[0]) in PARTICLES:
        toks = toks[1:]
    if not toks:
        return None
    return norm(toks[-1])


def main():
    # ── load HLS family articles ──
    fam_articles = collections.defaultdict(list)   # surname -> [article]
    for row in csv.DictReader(open(HLS, encoding="utf-8")):
        if row.get("category") != "fam":
            continue
        sn = article_surname(row.get("title", ""))
        if not sn:
            continue
        ct = row.get("content_text", "") or ""
        fam_articles[sn].append({
            "id": row["id"],
            "version": (row.get("version") or "").strip(),
            "title": row.get("title", "").strip(),
            "basel": bool(re.search(r"basel|basler", ct, re.I)),
        })
    print(f"HLS family articles indexed under {len(fam_articles)} surnames")

    # ── load HGB families ──
    data = json.load(open(FAM_INDEX, encoding="utf-8"))
    fams = data["families"]

    linked = 0
    for fam in fams:
        key = norm(fam["key"])
        arts = fam_articles.get(key)
        if not arts:
            continue
        # prefer Basel-tagged articles; accept if Basel-tagged or unique
        basel_arts = [a for a in arts if a["basel"]]
        chosen = None
        if basel_arts:
            chosen = basel_arts[0]
            conf = "basel"
        elif len(arts) == 1:
            chosen = arts[0]
            conf = "unique"
        if not chosen:
            continue
        ver = chosen["version"]
        fam["hls"] = {
            "id": chosen["id"],
            "url": (f"https://hls-dhs-dss.ch/de/articles/{chosen['id']}/{ver}/"
                    if ver else f"https://hls-dhs-dss.ch/de/articles/{chosen['id']}/"),
            "t": chosen["title"],
            "conf": conf,
        }
        linked += 1

    json.dump(data, open(FAM_INDEX, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"Linked {linked} HGB families to HLS family articles "
          f"→ {FAM_INDEX}")

    # ── also tag family-tree components so the Stammbaum can show the link ──
    by_surname = {norm(f["key"]): f["hls"] for f in fams if f.get("hls")}
    try:
        graph = json.load(open(FAM_GRAPH, encoding="utf-8"))
    except FileNotFoundError:
        graph = None
    if graph:
        tagged = 0
        for comp in graph.get("components", []):
            hls = by_surname.get(norm(comp.get("label", "")))
            if hls:
                comp["hls"] = hls
                tagged += 1
        json.dump(graph, open(FAM_GRAPH, "w", encoding="utf-8"),
                  separators=(",", ":"), ensure_ascii=False)
        print(f"Tagged {tagged} family-tree components → {FAM_GRAPH}")
    print("\nExamples:")
    shown = 0
    for fam in fams:
        if fam.get("hls"):
            print(f"  {fam['name']:16s} ({fam['n_persons']:4d} pers) "
                  f"[{fam['hls']['conf']}] → {fam['hls']['t']}  {fam['hls']['url']}")
            shown += 1
            if shown >= 18:
                break


if __name__ == "__main__":
    main()
