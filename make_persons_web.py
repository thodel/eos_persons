#!/usr/bin/env python3
"""
make_persons_web.py — compact web payload for the Identitäten tab.

`merged_persons.json` (Stage 4) is ~7 MB: full HBLS bio prose, every dossier id,
every name variant. The site only needs enough to search and display, so this
trims it to the fields `personen.html` actually renders and caps the long lists.

    python3 make_persons_web.py        # -> persons_web.json (tracked)

Short keys keep the payload small; see `personen.html` for the reader.
"""
import os
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))

SNIPPET = 260
MAX_OCC = 10
MAX_PUB = 5
MAX_PLACE = 2

# authority key -> (short key, display label, url template)
AUTHORITY = [
    ("gnd", "gnd", "GND", "https://d-nb.info/gnd/{}"),
    ("wikidata", "wd", "Wikidata", "https://www.wikidata.org/wiki/{}"),
    ("viaf", "viaf", "VIAF", None),
    ("deutsche_biographie", "db", "Deutsche Biographie", None),
    ("isni", "isni", "ISNI", None),
]


def snippet(bio):
    if not bio:
        return ""
    s = " ".join(bio.split())
    return s[:SNIPPET] + ("…" if len(s) > SNIPPET else "")


def source_label(s):
    if s["corpus"] == "hbls":
        return f"HBLS Bd. {s.get('volume')}, S. {s.get('page')}"
    if s["corpus"] == "hls":
        return "HLS-Artikel"
    if s["corpus"] == "hgb":
        n = s.get("n_mentions", 0)
        d = s.get("n_dossiers", 0)
        return f"HGB · {n} Erwähnung(en) in {d} Dossier(s)"
    if s["corpus"] == "gnd":
        return f"GND {s['id']}"
    if s["corpus"] == "wikidata":
        return f"Wikidata {s['id']}"
    return s["corpus"]


def compact(p):
    auth = {}
    for key, short, _label, tmpl in AUTHORITY:
        v = p["authority"].get(key)
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            auth[short] = tmpl.format(v) if tmpl else v
    places = []
    for kind in ("birth", "death", "activity"):
        for pl in (p["places"].get(kind) or [])[:MAX_PLACE]:
            if pl not in places:
                places.append(pl)
    return {
        "i": p["id"],
        "n": p["name"] or "",
        "b": p["birth_year"],
        "d": p["death_year"],
        "c": p["corpora"],
        "st": p["status"],
        "o": p["occupations"][:MAX_OCC],
        "pl": places[:3],
        "np": len(p["publications"]),
        "pt": [f"{x['title'][:90]}{' (' + x['year'] + ')' if x.get('year') else ''}"
               for x in p["publications"][:MAX_PUB]],
        "nd": len(p["dossiers"]),
        "a": auth,
        "sn": snippet(p["bio"]),
        "s": [{"c": s["corpus"], "u": s.get("url", ""), "l": source_label(s)}
              for s in p["sources"]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", default="merged_persons.json")
    ap.add_argument("--out", default="persons_web.json")
    ap.add_argument("--include-review", action="store_true",
                    help="also emit clusters Stage 3/4 flagged for review")
    args = ap.parse_args()

    people = json.load(open(os.path.join(HERE, args.merged), encoding="utf-8"))
    if not args.include_review:
        people = [p for p in people if p["status"] == "merged"]
    out = [compact(p) for p in people]
    out.sort(key=lambda r: (r["n"] or "￿").lower())

    path = os.path.join(HERE, args.out)
    json.dump(out, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    mb = os.path.getsize(path) / 1e6
    print(f"{len(out)} persons -> {args.out}  ({mb:.1f} MB)")
    print(f"  with life dates : {sum(1 for r in out if r['b'] or r['d'])}")
    print(f"  with occupations: {sum(1 for r in out if r['o'])}")
    print(f"  with a GND id   : {sum(1 for r in out if 'gnd' in r['a'])}")
    print(f"  with publications: {sum(1 for r in out if r['np'])}")
    print(f"  3-corpus        : {sum(1 for r in out if len(r['c']) == 3)}")


if __name__ == "__main__":
    main()
