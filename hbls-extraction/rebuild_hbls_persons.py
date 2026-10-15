#!/usr/bin/env python3
"""
rebuild_hbls_persons.py — recover hbls_persons.json from the tracked web data.

`build_persons.py` derives the HBLS person records from the lexicon PDFs, which
live only on the maintainer's machine; its output `hbls_persons.json` is
gitignored. The static HBLS tab, however, ships `../hbls_web.json`, which keeps
for every article its headword (= surname), volume, page, scan URL, a text
snippet and the list of parsed members (given name, birth/death year, member
number). That is exactly the join key the linkers need (surname + given +
life years + provenance), so this script rebuilds a link-ready
`hbls_persons.json` (and the Basel slice) from it.

Record ids
----------
`build_persons.py` numbered persons `hbls:<volume>:<running n>`; those ids are
cited by merged_persons.json / authority_edges.csv. The running counter cannot
be reproduced from the web data, so each rebuilt record gets a deterministic id
    hbls:<volume>:<page>:<HEADWORD>:<member_n or 0>[:<k>]
and, where an old id can be matched to a member (same volume & page, same
surname, same given name or life years), the old → new mapping is written to
`hbls_id_map.csv` so freeze_authority_edges.py can carry the authority clusters
over to the new ids.

    python3 rebuild_hbls_persons.py            # → hbls_persons.json, hbls_persons_basel.json, hbls_id_map.csv
"""
import csv
import json
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from link_hls import given_key, given_ratio, norm_token  # noqa: E402

BASEL = re.compile(r"\bBasel\b|\bbasler\b|\bbaslerisch", re.I)


def title_case_headword(k):
    """'ABEGG' → 'Abegg', 'VON DER MÜHLL' → 'von der Mühll', 'ST. GALLEN' → 'St. Gallen'."""
    out = []
    for i, tok in enumerate(k.split()):
        low = tok.lower()
        if low in ("von", "de", "der", "du", "des", "zu", "zur", "zum", "vom", "la", "le", "di", "da", "van") and i > 0:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def split_camel(g):
    """OCR often glues given names: 'FriedrichGottlieb' → 'Friedrich Gottlieb'."""
    return re.sub(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", " ", g or "").strip()


def main():
    web = json.load(open(os.path.join(ROOT, "hbls_web.json"), encoding="utf-8"))
    persons = []
    by_vp = {}
    for a in web:
        surname = title_case_headword(a["k"])
        seen = {}
        for m in a["m"]:
            given = split_camel(m.get("g") or "")
            if not given:
                continue
            n = m.get("n") or 0
            base = f"hbls:{a['v']}:{a['p']}:{a['k']}:{n}"
            k = seen.get(base, 0)
            seen[base] = k + 1
            pid = base if k == 0 else f"{base}:{k}"
            rec = {
                "id": pid,
                "name": f"{given} {surname}".strip(),
                "given": given,
                "surname": surname,
                "keyword": a["k"],
                "member_n": m.get("n"),
                "birth_year": m.get("b"),
                "death_year": m.get("d"),
                "floruit_years": None,
                "bio": a.get("s") or "",
                "volume": a["v"],
                "page": a["p"],
                "backlink": a["url"],
            }
            persons.append(rec)
            by_vp.setdefault((a["v"], a["p"]), []).append(rec)

    # ── map the old running ids cited by merged_persons.json ──
    id_map = {}
    merged_path = os.path.join(ROOT, "merged_persons.json")
    if os.path.exists(merged_path):
        for p in json.load(open(merged_path, encoding="utf-8")):
            srcs = [s for s in p.get("sources", []) if s["corpus"] == "hbls"]
            if not srcs:
                continue
            sur_src = p.get("surname") or (p.get("name") or "")
            sur = norm_token(sur_src.split()[-1]) if sur_src.split() else ""
            giv = given_key(p.get("given") or " ".join((p.get("name") or "").split()[:-1]))
            b, d = p.get("birth_year"), p.get("death_year")
            for s in srcs:
                cands = by_vp.get((s.get("volume"), s.get("page")), [])
                best, best_score = None, 0.0
                for c in cands:
                    sr = SequenceMatcher(None, sur, norm_token(c["surname"].split()[-1])).ratio() if sur else 0.5
                    if sr < 0.7:
                        continue
                    gr = given_ratio(giv, given_key(c["given"])) if giv else 0.0
                    date = 0.0
                    if b and c["birth_year"] and abs(b - c["birth_year"]) <= 3:
                        date += 0.5
                    if d and c["death_year"] and abs(d - c["death_year"]) <= 3:
                        date += 0.5
                    score = 0.3 * sr + 0.4 * gr + 0.3 * date
                    if score > best_score:
                        best, best_score = c, score
                if best is not None and best_score >= 0.55 and best["id"] not in id_map.values():
                    id_map[s["id"]] = best["id"]

    out = os.path.join(HERE, "hbls_persons.json")
    json.dump(persons, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    with open(os.path.join(HERE, "hbls_persons.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["id", "name", "given", "surname", "keyword", "member_n", "birth_year",
                "death_year", "volume", "page", "backlink"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(persons)

    basel = [p for p in persons if BASEL.search(p["bio"] or "")]
    json.dump(basel, open(os.path.join(HERE, "hbls_persons_basel.json"), "w",
                          encoding="utf-8"), ensure_ascii=False)

    with open(os.path.join(HERE, "hbls_id_map.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["old_id", "new_id"])
        for k in sorted(id_map):
            w.writerow([k, id_map[k]])

    dated = sum(1 for p in persons if p["birth_year"] or p["death_year"])
    print(f"→ {out}: {len(persons)} HBLS persons from {len(web)} articles "
          f"({dated} with life years); Basel slice {len(basel)}; "
          f"{len(id_map)} old ids mapped → hbls_id_map.csv")


if __name__ == "__main__":
    main()
