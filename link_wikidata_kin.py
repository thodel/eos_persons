#!/usr/bin/env python3
"""
link_wikidata_kin.py — turn Wikidata kinship into navigable cross-references.

Where a person's Wikidata relative (father P22 / mother P25 / spouse P26 /
child P40) is *itself* one of our HLS-linked HGB persons (matched by QID), we
record a resolved cross-link so the person modal can point straight to that
relative's HGB entry — weaving the famous Basel dynasties (Platter, Bauhin,
Petri, Burckhardt …) together as real, clickable entities rather than name
strings. Verified pairs that are also family-tree nodes additionally get an
edge in families_graph.json (src="wd").
"""
import json
import urllib.parse
import urllib.request
import time

PERSONS = "persons_resolved.json"
GRAPH = "families_graph.json"
UA = "hgb-hls-linker/1.0 (https://github.com/thodel/eos_persons; tobiashodel@gmail.com)"

ROLE = {"P22": "Vater", "P25": "Mutter", "P26": "Ehepartner", "P40": "Kind"}
INVERSE = {"P22": "Kind", "P25": "Kind", "P26": "Ehepartner", "P40": "Elternteil"}


CACHE = "/tmp/wd_kin.json"


def fetch_kin(qids):
    import os
    if os.path.exists(CACHE):
        cached = json.load(open(CACHE))
        if cached and "p" in cached[0]:
            print("  using cached /tmp/wd_kin.json")
            return cached
    values = " ".join(f"wd:{q}" for q in qids)
    q = f"""SELECT ?a ?b ?p WHERE {{
      VALUES ?a {{ {values} }} VALUES ?b {{ {values} }}
      VALUES ?p {{ wdt:P22 wdt:P25 wdt:P26 wdt:P40 }}
      ?a ?p ?b. }}"""
    body = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(
                "https://query.wikidata.org/sparql", data=body,
                headers={"User-Agent": UA, "Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = json.load(r)["results"]["bindings"]
            return [{"a": x["a"]["value"].rsplit("/", 1)[-1],
                     "b": x["b"]["value"].rsplit("/", 1)[-1],
                     "p": x["p"]["value"].rsplit("/", 1)[-1]} for x in rows]
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                print("  429 — waiting 65s"); time.sleep(65); continue
            raise


def main():
    persons = json.load(open(PERSONS, encoding="utf-8"))

    # qid -> canonical person (the one with most mentions for that QID)
    qid_person = {}
    for p in persons:
        if p.get("wd"):
            q = p["wd"]["qid"]
            if q not in qid_person or p.get("c", 0) > qid_person[q].get("c", 0):
                qid_person[q] = p

    qids = sorted(qid_person)
    print(f"{len(qids)} linked QIDs — querying Wikidata kinship …")
    links = fetch_kin(qids)
    print(f"  {len(links)} raw kin statements among our persons")

    # build per-person resolved cross-links (deduped)
    addlink = {}   # id(person) -> list

    def add(pers, role, target):
        lst = addlink.setdefault(id(pers), [])
        key = (role, target["wd"]["qid"])
        if any((r, t) == key for r, t in [(x["role"], x["qid"]) for x in lst]):
            return
        lst.append({"role": role, "name": target["n"], "qid": target["wd"]["qid"]})

    for ln in links:
        pa, pb = qid_person.get(ln["a"]), qid_person.get(ln["b"])
        if not pa or not pb or pa is pb:
            continue
        add(pa, ROLE[ln["p"]], pb)        # a's <role> is b
        add(pb, INVERSE[ln["p"]], pa)     # reciprocal on b

    # collapse to the most specific role per relative QID
    PRIO = {"Vater": 0, "Mutter": 1, "Ehepartner": 2, "Kind": 3, "Elternteil": 4}
    n = 0
    for p in persons:
        lst = addlink.get(id(p))
        if not lst:
            continue
        best = {}
        for x in lst:
            q = x["qid"]
            if q not in best or PRIO[x["role"]] < PRIO[best[q]["role"]]:
                best[q] = x
        p.setdefault("wd", {})["kinlinks"] = list(best.values())
        n += 1
    json.dump(persons, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  wrote resolved kin cross-links to {n} persons")

    # ── add verified edges to the family graph where both are nodes ──
    graph = json.load(open(GRAPH, encoding="utf-8"))
    key_to_node = {}
    for nd in graph["nodes"]:
        if nd.get("y"):
            key_to_node[(nd["name"], nd["y"][0], nd["y"][1])] = nd["id"]

    def node_of(p):
        y = p.get("y")
        return key_to_node.get((p["n"], y[0], y[1])) if y else None

    existing = {(e["a"], e["b"]) for e in graph["edges"]}
    added = 0
    for ln in links:
        if ln["p"] in ("P40",):   # child is the reverse of parent — avoid dup edges
            continue
        pa, pb = qid_person.get(ln["a"]), qid_person.get(ln["b"])
        if not pa or not pb:
            continue
        na, nb = node_of(pa), node_of(pb)
        if not na or not nb or na == nb:
            continue
        etype = "spouse" if ln["p"] == "P26" else "parent"
        # parent edge a=parent,b=child: for P22/P25, b is parent of a
        a, b = (nb, na) if etype == "parent" else (na, nb)
        if (a, b) in existing or (b, a) in existing:
            continue
        graph["edges"].append({"a": a, "b": b, "type": etype, "dir": "wd",
                               "trigger": "wikidata", "year": None, "dossier": "",
                               "conf": 1.0, "b_dead": False, "src": "wd"})
        existing.add((a, b)); added += 1
    json.dump(graph, open(GRAPH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  family graph: +{added} Wikidata-verified edges (src=wd)")

    print("\nExamples:")
    shown = 0
    for p in persons:
        kl = p.get("wd", {}).get("kinlinks")
        if kl:
            print(f"  {p['n']}: " + "; ".join(f"{x['role']}→{x['name']}" for x in kl))
            shown += 1
            if shown >= 12:
                break


if __name__ == "__main__":
    main()
