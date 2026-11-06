#!/usr/bin/env python3
"""
make_persons_web.py — compact web payload for the Identitäten tab.

`merged_persons.json` (Stage 4) is ~7 MB: full HBLS bio prose, every dossier id,
every name variant. The site only needs enough to search and display, so this
trims it to the fields `personen.html` actually renders and caps the long lists.

    python3 make_persons_web.py        # -> persons_web.json (tracked)

Short keys keep the payload small; see `personen.html` for the reader.

Persons the register joined to Human Lineage (`link_humanlineage.py`, the `hl`
block on `persons_resolved.json`) carry it here as `hl`: profile id and URL, life
dates, parents/children/spouses as names, the in-corpus cross-links and the
snapshot date. Credit «Human Lineage» with the profile URL where it is shown
(CC BY-SA 4.0).
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


def compact_hl(hl):
    """The `hl` block of a register person, reduced to what a card shows."""
    names = lambda key: [r["n"] for r in hl.get(key) or [] if r.get("n")]
    out = {"id": hl["id"], "u": hl["url"], "b": hl.get("b"), "d": hl.get("d"),
           "p": names("parents"), "ch": names("children"), "sp": names("spouses"),
           "snap": hl.get("snapshot")}
    if hl.get("kinlinks"):
        out["k"] = [{"role": k["role"], "name": k["name"]} for k in hl["kinlinks"]]
    return out


def load_hl_by_qid(path):
    """QID -> `hl` block from persons_resolved.json (empty when the file is absent)."""
    if not os.path.exists(path):
        return {}
    out = {}
    for p in json.load(open(path, encoding="utf-8")):
        hl, qid = p.get("hl"), (p.get("wd") or {}).get("qid")
        if hl and qid and qid not in out:
            out[qid] = hl
    return out


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


def compact(p, hl_by_qid=None):
    auth, qid = {}, None
    for key, short, _label, tmpl in AUTHORITY:
        v = p["authority"].get(key)
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            auth[short] = tmpl.format(v) if tmpl else v
            if key == "wikidata":
                qid = v
    places = []
    for kind in ("birth", "death", "activity"):
        for pl in (p["places"].get(kind) or [])[:MAX_PLACE]:
            if pl not in places:
                places.append(pl)
    out = {
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
    hl = (hl_by_qid or {}).get(qid)
    if hl:
        out["hl"] = compact_hl(hl)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", default="merged_persons.json")
    ap.add_argument("--out", default="persons_web.json")
    ap.add_argument("--persons", default="persons_resolved.json",
                    help="register index carrying the Human Lineage `hl` blocks")
    ap.add_argument("--include-review", action="store_true",
                    help="also emit clusters Stage 3/4 flagged for review")
    args = ap.parse_args()

    people = json.load(open(os.path.join(HERE, args.merged), encoding="utf-8"))
    if not args.include_review:
        people = [p for p in people if p["status"] == "merged"]
    hl_by_qid = load_hl_by_qid(os.path.join(HERE, args.persons))
    out = [compact(p, hl_by_qid) for p in people]
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
    print(f"  Human Lineage   : {sum(1 for r in out if 'hl' in r)}")


if __name__ == "__main__":
    main()
