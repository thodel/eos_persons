#!/usr/bin/env python3
"""
extract_genealogy.py — pull parents and spouses from the HLS articles of
linked HGB persons and write them into the site data.

HLS German biographies open with a stereotyped genealogical clause, e.g.
  "… Sohn des Friedrich (->), und der Salome Tschiffeli. 1606 Magdalena
   Platter, Tochter des Thomas Platter. …"
from which we read:
  • father  — name after "Sohn/Tochter des"   (bare given names inherit the
              subject's surname, since father shares it)
  • mother  — name after "und der"
  • spouses — "<Name>, Tochter des …" (a wife, described via her father),
              incl. numbered "1) <year> <Name>, 2) …", with the marriage year

Outputs:
  • persons_resolved.json — each linked person gains a `kin` field
        {"f": father, "m": mother, "sp": [{"n": name, "y": year}]}
  • families_graph.json   — for linked persons that are tree nodes, missing
        parent/spouse nodes+edges are added, flagged src="hls".
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

NM = r"[A-ZÄÖÜ][a-zäöüé]+(?:[-\s][A-ZÄÖÜ][a-zäöüé]+){0,2}"

RE_FATHER = re.compile(r"\b(?:Sohn|Tochter|Sön|fils|fille)\s+des?\s+(" + NM + r")")
RE_MOTHER = re.compile(r"\bund\s+der\s+(" + NM + r")")
# wives: "<Name>, Tochter des" (described by her father)  /  "<Name>, Witwe"
RE_SPOUSE_TD = re.compile(r"(?:(?:^|[.\s])(\d)\)\s*)?(?:(\d{4})\s+)?(" + NM +
                          r"),\s+(?:Tochter|Witwe|Tochter\s+des)")
# numbered marriages: "1) 1579 Anna Isengrin, 2) 1583 Dorothea Wasserhun"
RE_SPOUSE_NUM = re.compile(r"(?:^|[\s.])(\d)\)\s*(?:um\s+)?(\d{4})?\s*(" + NM +
                           r")(?=[,.])")
# strip author block / leading metadata so we parse the biography body
RE_AUTHOR = re.compile(r"Autorin/Autor:.*?\n.*?\n", re.S)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def subject_surname(name):
    toks = [t for t in re.split(r"[ .,]", name) if len(t) > 1]
    return toks[-1] if toks else ""


def with_surname(given_or_full, surname):
    """A bare given name inherits the subject's surname (shared family)."""
    toks = given_or_full.split()
    if len(toks) == 1 and surname and toks[0] != surname:
        return f"{given_or_full} {surname}"
    return given_or_full


def lead(text):
    """The biographical lead — first ~2 sentences after the metadata line."""
    text = RE_AUTHOR.sub("", text)
    # cut at the first career year-clause to limit false positives
    return text[:600]


def extract(text, subj_surname):
    body = lead(text)
    father = mother = None
    m = RE_FATHER.search(body)
    if m:
        father = with_surname(m.group(1).strip(), subj_surname)
    # mother must appear close to / after the father clause
    mm = RE_MOTHER.search(body, m.end() - 4 if m else 0)
    if mm:
        mother = mm.group(1).strip()
        if father and mother == m.group(1).strip():
            mother = None

    spouses = []
    seen = set()
    parents = {father, mother}
    for rx in (RE_SPOUSE_TD, RE_SPOUSE_NUM):
        for sm in rx.finditer(body):
            nm = sm.group(3).strip()
            yr = int(sm.group(2)) if sm.group(2) else None
            if nm in parents or nm == father:
                continue
            key = nm.lower()
            if key in seen:
                continue
            seen.add(key)
            spouses.append({"n": nm, "y": yr})
    return father, mother, spouses


def similar(a, b):
    ta = strip_accents(a.lower()).split()
    tb = strip_accents(b.lower()).split()
    if not ta or not tb:
        return 0.0
    return 0.5 * SequenceMatcher(None, ta[-1], tb[-1]).ratio() + \
        0.5 * SequenceMatcher(None, ta[0], tb[0]).ratio()


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))
    linked = {p["hls"]["id"]: p for p in persons if p.get("hls")}
    print(f"{len(linked)} linked persons")

    content = {}
    for row in csv.DictReader(open(HLS, encoding="utf-8")):
        if row["id"] in linked:
            content[row["id"]] = row.get("content_text", "") or ""

    n_father = n_mother = n_spouse = 0
    for hid, p in linked.items():
        surn = subject_surname(p["hls"]["t"]) or subject_surname(p["n"])
        father, mother, spouses = extract(content.get(hid, ""), surn)
        kin = {}
        if father:
            kin["f"] = father; n_father += 1
        if mother:
            kin["m"] = mother; n_mother += 1
        if spouses:
            kin["sp"] = spouses; n_spouse += len(spouses)
        if kin:
            p["kin"] = kin

    print(f"extracted  father:{n_father}  mother:{n_mother}  "
          f"spouse:{n_spouse} (over {len(linked)} persons)")

    json.dump(persons, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  wrote kin into {PERSONS}")

    # ── add edges/nodes to the family graph for tree-member persons ──
    graph = json.load(open(GRAPH, encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    key_to_node = {}
    for n in graph["nodes"]:
        if n.get("y"):
            key_to_node[(n["name"], n["y"][0], n["y"][1])] = n["id"]
    adj = {"spouse": {}, "parent": {}}
    for e in graph["edges"]:
        t = "spouse" if e["type"] == "spouse" else ("parent" if e["type"] in ("parent", "child") else None)
        if t:
            adj[t].setdefault(e["a"], []).append(e["b"])
            adj[t].setdefault(e["b"], []).append(e["a"])

    added_n = added_e = 0
    uid = 0

    def neighbours_names(node_id, kind):
        return [nodes[x]["name"] for x in adj[kind].get(node_id, []) if x in nodes]

    def add_kin(node_id, cid, name, kind, year=None):
        nonlocal added_n, added_e, uid
        existing = neighbours_names(node_id, kind)
        if any(similar(name, ex) >= 0.7 for ex in existing):
            return
        nid = f"hls-{kind}:{uid}"; uid += 1
        nodes[nid] = {"id": nid, "name": name, "linked": False, "src": "hls",
                      "occ": [], "y": None, "dead_year": None, "c": 0, "cid": cid}
        graph["nodes"].append(nodes[nid])
        etype = "spouse" if kind == "spouse" else "parent"
        # parent edge: a = parent, b = subject
        a, b = (nid, node_id) if kind == "parent" else (node_id, nid)
        graph["edges"].append({"a": a, "b": b, "type": etype,
                               "dir": "hls", "trigger": "hls", "year": year,
                               "dossier": "", "conf": 0.8, "b_dead": False,
                               "src": "hls"})
        adj[kind].setdefault(node_id, []).append(nid)
        added_n += 1; added_e += 1

    for hid, p in linked.items():
        kin = p.get("kin")
        y = p.get("y")
        if not kin or not y:
            continue
        node_id = key_to_node.get((p["n"], y[0], y[1]))
        if node_id is None:
            continue
        cid = nodes[node_id].get("cid")
        if kin.get("f"):
            add_kin(node_id, cid, kin["f"], "parent")
        if kin.get("m"):
            add_kin(node_id, cid, kin["m"], "parent")
        for sp in kin.get("sp", []):
            add_kin(node_id, cid, sp["n"], "spouse", sp.get("y"))

    # refresh component sizes
    csize = {}
    for n in graph["nodes"]:
        if n.get("cid") is not None:
            csize[n["cid"]] = csize.get(n["cid"], 0) + 1
    for c in graph.get("components", []):
        if c["cid"] in csize:
            c["size"] = csize[c["cid"]]

    json.dump(graph, open(GRAPH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  family graph: +{added_n} nodes / +{added_e} edges (src=hls)")

    print("\nExamples:")
    shown = 0
    for p in linked.values():
        k = p.get("kin")
        if k and ("f" in k or "sp" in k):
            sp = ", ".join(s["n"] for s in k.get("sp", []))
            print(f"  {p['n']}: Vater={k.get('f','–')} | Mutter={k.get('m','–')} | ⚭ {sp or '–'}")
            shown += 1
            if shown >= 12:
                break


if __name__ == "__main__":
    main()
