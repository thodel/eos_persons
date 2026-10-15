#!/usr/bin/env python3
"""
extract_persons.py — the person *name list* of the HGB corpus, one row per mention.

Reads the street-split BeNASch XML published in
DHBern/economies-of-space-automatically-annotated-data (via hgb_corpus.py) and
writes two tables:

  persons.csv    one row per named person reference — the raw input of
                 build_data.py (→ persons_resolved.json), build_movements.py …
  dossiers.csv   one row per dossier (property) with LV95 point, address, type,
                 street, document count and year range — the geo backbone for
                 dossiers_geo.json, movements and the Preiskarte.

A *named person reference* is a span with element="reference" class="per"
whose own subtree (not descending into nested references) carries a
head/class="nam". Everything else attached to that reference is collected
without crossing into nested references, so "Hans, Sohn des Peter Müller"
yields Hans with family_relation=Sohn, and Peter Müller as his own row:

  name              head nam text (tokens space-joined, as in the XML)
  alias             appo nam text ("genannt …"), if any
  occupation_text   occ head/appo text(s), "|"-joined
  occupation_norm   normalised occupation(s) (norm attr, lower-case), "|"-joined
  occupation_ohdab  OhdAB concept URI(s)
  title             title head text(s)        ("Mr .", "Jkr", "Ritter" …)
  family_relation   fam head text(s)          ("Frau", "Sohn", "Wittwen" …)
  location          loc attr text(s)          ("von Liestal", "zu Basel" …)
  org_affiliation   org-aff text(s)           ("Burger", "des Rats" …)
  is_deceased       1 if a class="dead" marker ("sel.", "selig") is attached
  numerus / specificity / confidence   of the reference span
  roles             event roles the reference fills, "|"-joined (buyer, owner …)

Document columns: doc_id, dossierid, street_id, year, source, checked_by_gpt,
page_url (first page image), span_id.

    python3 extract_persons.py                      # sibling data checkout
    python3 extract_persons.py --street-dir /path/to/street_data
    python3 extract_persons.py --limit-files 3      # quick test
"""
import argparse
import collections
import csv
import sys

import hgb_corpus

PERSONS_OUT = "persons.csv"
DOSSIERS_OUT = "dossiers.csv"

PERSON_COLS = [
    "doc_id", "dossierid", "street_id", "year", "source", "checked_by_gpt",
    "span_id", "name", "alias", "numerus", "specificity", "confidence",
    "occupation_text", "occupation_norm", "occupation_ohdab",
    "title", "family_relation", "location", "org_affiliation",
    "is_deceased", "roles", "page_url",
]
DOSSIER_COLS = [
    "dossierid", "street_id", "street_name", "address", "dossiertype",
    "location", "variant_names", "valid_from", "valid_to",
    "predecessors", "successors", "n_docs", "year_min", "year_max", "sources",
]


def clean(s):
    return " ".join((s or "").split())


def own_subtree(ref):
    """Descendant spans of a reference, not entering nested *reference* spans."""
    stack = list(ref)
    while stack:
        el = stack.pop(0)
        if el.tag != "span":
            continue
        yield el
        if el.get("element") == "reference":
            continue            # a nested entity: its content is not ours
        stack = list(el) + stack


def describe(ref):
    """Collect the person attributes of one per-reference span."""
    name = alias = None
    occ_t, occ_n, occ_o, tit, fam, loc, org = [], [], [], [], [], [], []
    dead = False
    appo_occ_pending = []
    for el in own_subtree(ref):
        cls, elem, text = el.get("class"), el.get("element"), clean(el.get("text"))
        if cls == "nam":
            if elem == "head" and name is None:
                name = text
            elif elem in ("appo", "unk") and alias is None and text:
                alias = text
        elif cls == "occ":
            if elem == "head":
                if text:
                    occ_t.append(text)
                occ_n.append((el.get("norm") or "unk").strip().lower())
                if el.get("OhdAB"):
                    occ_o.append(el.get("OhdAB").strip())
            elif elem in ("appo", "unk") and text:
                appo_occ_pending.append(text)
        elif cls == "title":
            if elem == "head" and text:
                tit.append(text)
        elif cls == "fam":
            if elem == "head" and text:
                fam.append(text)
        elif cls == "loc":
            if elem == "attr" and text:
                loc.append(text)
        elif cls == "org-aff":
            if elem in ("attr", "appo") and text:
                org.append(text)
            elif elem == "head" and text and not org:
                org.append(text)
        elif cls == "dead":
            dead = True
    if not occ_t and appo_occ_pending:         # apposition without a head
        occ_t = appo_occ_pending
        occ_n = ["unk"] * len(appo_occ_pending)
    return {
        "name": name, "alias": alias,
        "occupation_text": "|".join(occ_t), "occupation_norm": "|".join(occ_n),
        "occupation_ohdab": "|".join(dict.fromkeys(occ_o)),
        "title": "|".join(tit), "family_relation": "|".join(fam),
        "location": "|".join(loc), "org_affiliation": "|".join(org),
        "is_deceased": 1 if dead else 0,
    }


def person_rows(doc, meta):
    spans_el = doc.find("spans")
    if spans_el is None:
        return []
    # event roles per span id
    roles = collections.defaultdict(list)
    eg_el = doc.find("eventGroups")
    if eg_el is not None:
        for r in eg_el.iter("role"):
            if r.get("ref") and r.get("role"):
                roles[r.get("ref")].append(r.get("role"))
    page_url = meta["pages"][0][1] if meta.get("pages") else ""
    rows = []
    for sp in spans_el.iter("span"):
        if sp.get("class") != "per" or sp.get("element") != "reference":
            continue
        d = describe(sp)
        if not d["name"]:
            continue
        rows.append({
            "doc_id": meta["doc_id"], "dossierid": meta["dossier_id"],
            "street_id": meta["street_id"], "year": meta["year"],
            "source": meta["source"],
            "checked_by_gpt": 1 if meta["checked_by_gpt"] else 0,
            "span_id": sp.get("id"),
            "numerus": sp.get("numerus"), "specificity": sp.get("specificity"),
            "confidence": sp.get("confidence"),
            "roles": "|".join(dict.fromkeys(roles.get(sp.get("id"), []))),
            "page_url": page_url,
            **d,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--street-dir", default=None)
    ap.add_argument("--out", default=PERSONS_OUT)
    ap.add_argument("--dossiers", default=DOSSIERS_OUT)
    ap.add_argument("--limit-files", type=int, default=0)
    args = ap.parse_args()

    files = hgb_corpus.corpus_files(args.street_dir)
    if args.limit_files:
        files = files[:args.limit_files]
    print(f"{len(files)} street files", file=sys.stderr)

    n_docs = n_rows = 0
    doss = {}                     # dossier → running doc stats
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PERSON_COLS)
        w.writeheader()
        for doc, meta in hgb_corpus.iter_documents(files=files):
            n_docs += 1
            rows = person_rows(doc, meta)
            w.writerows(rows)
            n_rows += len(rows)
            did = meta["dossier_id"]
            if did:
                ds = doss.setdefault(did, {
                    "dossierid": did, "street_id": meta["street_id"],
                    "street_name": meta["street_name"], "address": meta["address"],
                    "dossiertype": meta["dossiertype"], "location": meta["location"],
                    "variant_names": None, "valid_from": None, "valid_to": None,
                    "predecessors": "", "successors": "",
                    "n_docs": 0, "years": [], "sources": set(),
                })
                ds["n_docs"] += 1
                if meta["year"]:
                    ds["years"].append(meta["year"])
                if meta["source"]:
                    ds["sources"].add(meta["source"])

    # dossier-level fields that only the <collection> element carries
    for cd in hgb_corpus.iter_dossiers(files=files):
        ds = doss.setdefault(cd["dossier_id"], {
            "dossierid": cd["dossier_id"], "street_id": cd["street_id"],
            "street_name": cd["street_name"], "address": cd["address"],
            "dossiertype": cd["dossiertype"], "location": cd["location"],
            "n_docs": 0, "years": [], "sources": set(),
        })
        ds["variant_names"] = cd["variant_names"]
        ds["valid_from"], ds["valid_to"] = cd["valid_from"], cd["valid_to"]
        ds["predecessors"] = "|".join(cd["predecessors"])
        ds["successors"] = "|".join(cd["successors"])

    with open(args.dossiers, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DOSSIER_COLS)
        w.writeheader()
        for did in sorted(doss):
            ds = doss[did]
            ys = ds.pop("years")
            w.writerow({**{k: ds.get(k) for k in DOSSIER_COLS},
                        "year_min": min(ys) if ys else None,
                        "year_max": max(ys) if ys else None,
                        "sources": ";".join(sorted(ds["sources"]))})

    n_loc = sum(1 for d in doss.values() if d.get("location"))
    print(f"→ {args.out}: {n_rows:,} person mentions from {n_docs:,} documents",
          file=sys.stderr)
    print(f"→ {args.dossiers}: {len(doss):,} dossiers ({n_loc:,} with coordinates)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
