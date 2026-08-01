#!/usr/bin/env python3
"""
build_review_worksheet.py — triage the Stage-4 review queue into actions.

Stage 4 (build_merged_persons.py) auto-merges confident clusters and marks the
rest `status == "review"` with a `conflicts` list. This script turns that queue
into an actionable worksheet: for each review record it inspects the per-source
evidence (HGB mention-year keys, HBLS life dates) against the cluster's life span
and recommends a concrete action, so a human can work the backlog quickly.

It does NOT modify merged_persons.json — the review gate is deliberate (see
DEDUP_PLAN.md). Output: review_worksheet.csv, ranked with the auto-resolvable
cases first.

    python3 build_review_worksheet.py
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TOL_BEFORE = 5     # a mention this many years before birth still counts as in-span
GRACE_AFTER = 15   # post-mortem references within this window are plausible

merged = json.load(open(os.path.join(HERE, "merged_persons.json"), encoding="utf-8"))
hbls_dates = {}
hp = os.path.join(HERE, "hbls-extraction", "hbls_persons.json")
if os.path.exists(hp):
    for p in json.load(open(hp, encoding="utf-8")):
        hbls_dates[p["id"]] = (p.get("birth_year"), p.get("death_year"))


def hgb_year(src_id):
    m = re.search(r"#(\d{3,4})$", src_id)
    return int(m.group(1)) if m else None


def span(rec):
    b, d = rec.get("birth_year"), rec.get("death_year")
    lo = (b or (d - 80 if d else None))
    hi = (d or (b + 80 if b else None))
    return (lo - TOL_BEFORE if lo else None), (hi + GRACE_AFTER if hi else None)


def triage(r):
    """Return (recommendation, auto_resolvable, evidence)."""
    conf = set(r["conflicts"])
    lo, hi = span(r)
    hgb = [s for s in r["sources"] if s["corpus"] == "hgb"]
    hbls = [s for s in r["sources"] if s["corpus"] == "hbls"]

    # 1) two distinct authority records merged -> almost always a bad bridge
    if conf & {"multi_gnd", "multi_hls", "multi_wd"}:
        gnds = [s["id"] for s in r["sources"] if s["corpus"] == "gnd"]
        return ("INSPECT_AUTHORITY", False,
                f"{len(gnds)} GND ids merged in one cluster: {', '.join(gnds)}")

    # 2) multiple HGB records — split into in-span vs outliers by mention year
    if "multi_hgb" in conf and lo and hi:
        ins, out = [], []
        for s in hgb:
            y = hgb_year(s["id"])
            (ins if (y and lo <= y <= hi) else out).append((s["id"], y))
        if ins and out:
            return ("TRIM_HGB", True,
                    f"keep {[i for i,_ in ins]}; detach as homonyms "
                    f"{[i for i,_ in out]} (life span {r['birth_year']}–{r['death_year']})")
        if ins and not out:
            return ("HGB_UNDERRESOLVED", True,
                    f"all {len(ins)} HGB records fall in the life span — same "
                    f"person split across HGB mention-clusters; safe to merge")
        return ("HGB_NONE_IN_SPAN", False,
                f"no HGB mention year fits {r['birth_year']}–{r['death_year']}: "
                f"{[hgb_year(s['id']) for s in hgb]}")

    # 3) multiple HBLS records — compatible variants vs distinct persons
    if "multi_hbls" in conf:
        dated = [(s["id"], *hbls_dates.get(s["id"], (None, None))) for s in hbls]
        yrs = [b for _, b, _ in dated if b] + [d for _, _, d in dated if d]
        if yrs and max(yrs) - min(yrs) <= 15:
            return ("HBLS_VARIANT", True,
                    f"HBLS records date-compatible ({[i for i,_,_ in dated]}); "
                    f"likely the same person / family entry — keep as sources")
        return ("SPLIT_HBLS", False,
                f"HBLS records disagree on dates {dated}; pick the one matching "
                f"the HLS/GND life span")

    # 4) life-date spread — flag the outlier source
    if "birth_spread" in conf:
        return ("DATE_OUTLIER", False,
                f"life dates span >15y across sources; verify which source is "
                f"wrong (identity {r['birth_year']}–{r['death_year']})")

    # 5) name disagreement only — usually an OCR/accent variant
    if conf == {"name_disagreement"} or conf == {"hgb_key_ambiguous"}:
        return ("NAME_VARIANT", True,
                f"only a name-form disagreement ({r['name']}); likely the same "
                f"person under spelling variants")

    return ("REVIEW", False, "+".join(sorted(conf)))


rows = []
for r in merged:
    if r["status"] != "review":
        continue
    rec, auto, evidence = triage(r)
    rows.append({
        "id": r["id"], "cluster_id": r["cluster_id"], "name": r["name"],
        "birth_year": r.get("birth_year") or "", "death_year": r.get("death_year") or "",
        "corpora": "+".join(r["corpora"]), "conflicts": "+".join(r["conflicts"]),
        "recommendation": rec, "auto_resolvable": "yes" if auto else "no",
        "evidence": evidence,
        "hbls_ids": ";".join(s["id"] for s in r["sources"] if s["corpus"] == "hbls"),
        "hgb_ids": ";".join(s["id"] for s in r["sources"] if s["corpus"] == "hgb"),
        "gnd": ";".join(s["id"] for s in r["sources"] if s["corpus"] == "gnd"),
    })

order = {"HGB_UNDERRESOLVED": 0, "HBLS_VARIANT": 1, "NAME_VARIANT": 2,
         "TRIM_HGB": 3, "SPLIT_HBLS": 4, "DATE_OUTLIER": 5,
         "HGB_NONE_IN_SPAN": 6, "INSPECT_AUTHORITY": 7, "REVIEW": 8}
rows.sort(key=lambda r: order.get(r["recommendation"], 9))

cols = ["id", "cluster_id", "name", "birth_year", "death_year", "corpora",
        "conflicts", "recommendation", "auto_resolvable", "evidence",
        "hbls_ids", "hgb_ids", "gnd"]
with open(os.path.join(HERE, "review_worksheet.csv"), "w",
          encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

from collections import Counter
c = Counter(r["recommendation"] for r in rows)
auto = sum(1 for r in rows if r["auto_resolvable"] == "yes")
print(f"{len(rows)} review records triaged -> review_worksheet.csv")
print(f"  auto-resolvable (safe): {auto}   needs human judgement: {len(rows) - auto}")
for rec, n in sorted(c.items(), key=lambda kv: order.get(kv[0], 9)):
    print(f"    {n:3d}  {rec}")
