#!/usr/bin/env python3
"""
build_hgb_street_persons.py — street-level person index from the DHBern
*Economies of Space: Full Annotated Dataset*.

The DHBern release (github.com/DHBern/economies-of-space-automatically-annotated-data,
read-only here) ships one XML per street (street_data/street_HGB_1_NNN.xml):
series = street, collection = dossier (with LV95 point), document = entry
with nested spans. Person references are <span element="reference"
class="per"> with a <span element="head" class="nam"> child; occupations,
titles and kin sit in appositions; event roles point at span ids.

This script aggregates every singular, specific person mention per
(street, name key) so an external name (here: the Basel Jahrrechnungen) can be
matched against a *located* person — street, dossiers, coordinates, years,
occupations and roles — instead of against the corpus-wide name list in
persons_resolved.json, which conflates homonyms across the whole city.

    python3 build_hgb_street_persons.py [--src ../economies-of-space-automatically-annotated-data/street_data]
        -> hgb_street_persons.json (gitignored: regenerable, ~tens of MB)

Record:
  {"key": "johann jacob|rudin", "name": "Hans Jacob Rudin", "variants": [...],
   "street_id": "HGB_1_028", "street": "Freie Strasse", "n": 7,
   "years": [1540, 1552], "dossiers": ["HGB_1_028_012", ...],
   "location": "POINT(2611... 1267...)", "occ": ["schneider"], "roles": {"owner": 3}}
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from link_hls import split_name

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "..", "economies-of-space-automatically-annotated-data", "street_data")
OUT = os.path.join(HERE, "hgb_street_persons.json")
MIN_CONF = 0.5


def person_mentions(doc):
    """Yield (span_id, name, occupations) for each singular specific person."""
    spans = doc.find("spans")
    if spans is None:
        return
    for ref in spans.iter("span"):
        if ref.get("element") != "reference" or ref.get("class") != "per":
            continue
        if ref.get("numerus") != "sgl" or ref.get("specificity") != "spc":
            continue
        try:
            if float(ref.get("confidence", "1")) < MIN_CONF:
                continue
        except ValueError:
            pass
        head = next((c for c in ref if c.get("element") == "head" and c.get("class") == "nam"), None)
        if head is None:
            continue
        name = re.sub(r"\s*\(\s*sic\s*\)\s*|\s*[.,;:]+$", "", head.get("text", "")).strip()
        if not name:
            continue
        occ = []
        for ap in ref:
            if ap.get("element") == "appo" and ap.get("class") == "occ":
                for h in ap.iter("span"):
                    if h.get("element") == "head" and h.get("class") == "occ":
                        n = h.get("norm", "")
                        occ.append(n if n and n != "unk" else h.get("text", ""))
        yield ref.get("id"), name, occ


def roles_by_span(doc):
    out = collections.defaultdict(collections.Counter)
    egs = doc.find("eventGroups")
    if egs is None:
        return out
    for role in egs.iter("role"):
        out[role.get("ref")][role.get("role")] += 1
    return out


def process_file(path, index):
    # the street files are up to 30 MB: iterparse and drop each document
    street_id = street = None
    coll_meta = {}
    for ev, el in ET.iterparse(path, events=("start", "end")):
        if ev == "start" and el.tag == "series":
            street_id, street = el.get("id"), el.get("name")
        elif ev == "end" and el.tag == "metadata" and el.find("location") is not None:
            coll_meta = {"location": (el.findtext("location") or "").strip(),
                         "address": (el.findtext("address") or "").strip()}
        elif ev == "end" and el.tag == "document":
            meta = el.find("metadata")
            try:
                year = int(meta.findtext("year"))
            except (TypeError, ValueError):
                year = None
            dossier = meta.findtext("dossier_id") or ""
            source = meta.findtext("source") or ""
            roles = roles_by_span(el)
            for sid, name, occ in person_mentions(el):
                given, surname = split_name(name)
                if not surname:
                    continue
                key = f"{given}|{surname}"
                rec = index.get((street_id, key))
                if rec is None:
                    rec = index[(street_id, key)] = {
                        "key": key, "name": name, "variants": collections.Counter(),
                        "street_id": street_id, "street": street, "n": 0,
                        "years": [], "dossiers": set(), "location": coll_meta.get("location", ""),
                        "occ": collections.Counter(), "roles": collections.Counter(),
                        "sources": collections.Counter(),
                    }
                rec["n"] += 1
                rec["variants"][name] += 1
                if year:
                    rec["years"].append(year)
                if dossier:
                    rec["dossiers"].add(dossier)
                rec["occ"].update(o.lower() for o in occ if o)
                rec["roles"].update(roles.get(sid, {}))
                rec["sources"][source] += 1
            el.clear()
        elif ev == "end" and el.tag == "collection":
            el.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.src, "street_HGB_*.xml")))
    if not files:
        sys.exit(f"no street_HGB_*.xml under {a.src}")
    index = {}
    for i, f in enumerate(files, 1):
        process_file(f, index)
        print(f"[{i}/{len(files)}] {os.path.basename(f)}: {len(index)} persons so far", file=sys.stderr)
    out = []
    for rec in index.values():
        ys = sorted(rec["years"])
        rec["name"] = rec["variants"].most_common(1)[0][0]
        rec["variants"] = [v for v, _ in rec["variants"].most_common(8)]
        rec["years"] = [ys[0], ys[-1]] if ys else None
        rec["dossiers"] = sorted(rec["dossiers"])
        rec["occ"] = [o for o, _ in rec["occ"].most_common(6)]
        rec["roles"] = dict(rec["roles"].most_common())
        rec["sources"] = dict(rec["sources"].most_common(4))
        out.append(rec)
    out.sort(key=lambda r: (r["street_id"], r["key"]))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"{len(out)} street-level persons from {len(files)} streets -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
