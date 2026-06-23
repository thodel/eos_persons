#!/usr/bin/env python3
"""
extract_spouses.py — mine spouses from the HLS articles of linked HGB persons
and add the ones missing from the family tree.

The HLS content_text export keeps little structured genealogy, so this is a
high-precision / low-recall pass: only clear marriage notations are taken
  • "∞ [n)] [um] [YYYY] <Name>"   (genealogical marriage symbol)
  • "heiratete [YYYY] <Name>"
  • "Ehe mit <Name>" / "vermählt mit <Name>" / "Gattin/Gemahlin <Name>"
Each extracted spouse is matched against the person's existing spouse edges in
families_graph.json; only genuinely missing spouses are added, as nodes/edges
flagged src="hls" so the tree can distinguish them.
"""
import re
import csv
import json
import unicodedata
from difflib import SequenceMatcher

csv.field_size_limit(10_000_000)

HLS = "/Users/TH_1/Documents/HLS/hls_articles.csv"
PERSONS = "persons_resolved.json"
GRAPH = "families_graph.json"

NAME = r"[A-ZÄÖÜ][a-zäöüß]+(?:\s+(?:von\s+|zu\s+|de\s+)?[A-ZÄÖÜ][a-zäöüß]+){0,2}"
PATTERNS = [
    re.compile(r"∞\s*(?:\d\)\s*)?(?:um\s*)?(?:\d{4}\s*)?(" + NAME + ")"),
    re.compile(r"heiratete?\s+(?:\d{4}\s+|im\s+\w+\s+|den\s+|die\s+)?(" + NAME + ")"),
    re.compile(r"(?:Ehe|vermählt)\s+mit\s+(" + NAME + ")"),
    re.compile(r"(?:Gattin|Gemahlin)\s+(?:war\s+)?(" + NAME + ")"),
]
# words that are not a spouse name even if capitalized after the cue
STOP = {"Buchdrucker", "Tochter", "Sohn", "Witwe", "Bürger", "Ratsherr",
        "Pfarrer", "Kaufmann", "Junker", "Herr", "Frau", "Doktor"}


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    return strip_accents(re.sub(r"[^\wäöü ]", " ", s.lower())).split()


def similar(a, b):
    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return 0.0
    # compare last tokens (surnames) and first tokens (given)
    sr = SequenceMatcher(None, ta[-1], tb[-1]).ratio()
    gr = SequenceMatcher(None, ta[0], tb[0]).ratio()
    return 0.5 * sr + 0.5 * gr


def extract_spouses(text):
    found = []
    for pat in PATTERNS:
        for m in pat.finditer(text):
            nm = m.group(1).strip()
            if nm.split()[0] in STOP:
                continue
            if nm not in found:
                found.append(nm)
    return found


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))
    linked = {p["hls"]["id"]: p for p in persons if p.get("hls")}
    print(f"{len(linked)} linked persons")

    # spouse names per linked HLS id
    spouses_by_person = {}
    for row in csv.DictReader(open(HLS, encoding="utf-8")):
        if row["id"] not in linked:
            continue
        sp = extract_spouses(row.get("content_text", "") or "")
        if sp:
            spouses_by_person[row["id"]] = sp
    n_extracted = sum(len(v) for v in spouses_by_person.values())
    print(f"extracted {n_extracted} spouse mentions for "
          f"{len(spouses_by_person)} persons")

    graph = json.load(open(GRAPH, encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    # key (name, y0, y1) -> node id
    key_to_node = {}
    for n in graph["nodes"]:
        if n.get("y"):
            key_to_node[(n["name"], n["y"][0], n["y"][1])] = n["id"]
    # adjacency of existing spouse edges
    spouse_adj = {}
    for e in graph["edges"]:
        if e["type"] == "spouse":
            spouse_adj.setdefault(e["a"], []).append(e["b"])
            spouse_adj.setdefault(e["b"], []).append(e["a"])

    added_nodes = 0
    added_edges = 0
    uid = 0
    for hls_id, sp_names in spouses_by_person.items():
        p = linked[hls_id]
        y = p.get("y")
        node_id = key_to_node.get((p["n"], y[0], y[1])) if y else None
        if node_id is None:
            continue                      # linked person not in a family tree
        cid = nodes[node_id].get("cid")
        existing = [nodes[x]["name"] for x in spouse_adj.get(node_id, [])
                    if x in nodes]
        for sp in sp_names:
            # already a spouse in the tree?
            if any(similar(sp, ex) >= 0.7 for ex in existing):
                continue
            new_id = f"hls-sp:{hls_id}:{uid}"
            uid += 1
            nodes[new_id] = {
                "id": new_id, "name": sp, "linked": False, "src": "hls",
                "occ": [], "y": None, "dead_year": None, "c": 0, "cid": cid,
            }
            graph["nodes"].append(nodes[new_id])
            graph["edges"].append({
                "a": node_id, "b": new_id, "type": "spouse", "dir": "spouse",
                "trigger": "hls", "year": None, "dossier": "", "conf": 0.8,
                "b_dead": False, "src": "hls",
            })
            spouse_adj.setdefault(node_id, []).append(new_id)
            added_nodes += 1
            added_edges += 1
            print(f"  + {p['n']} ⚭ {sp}  (HLS: {p['hls']['t']})")

    # bump component sizes for added members
    csize = {}
    for n in graph["nodes"]:
        if n.get("cid") is not None:
            csize[n["cid"]] = csize.get(n["cid"], 0) + 1
    for c in graph.get("components", []):
        if c["cid"] in csize:
            c["size"] = csize[c["cid"]]

    json.dump(graph, open(GRAPH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nadded {added_nodes} spouse nodes / {added_edges} spouse edges "
          f"→ {GRAPH}")


if __name__ == "__main__":
    main()
