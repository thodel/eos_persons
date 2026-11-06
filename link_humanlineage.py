#!/usr/bin/env python3
"""
link_humanlineage.py — join the QID-linked persons to Human Lineage.

Human Lineage (humanlineage.org) is an open genealogical graph, published on
Zenodo under CC BY-SA 4.0 and served to the fleet as an MCP server
(thodel/humanlineage_mcp). This stage runs after `link_wikidata_kin.py`: for
every person with a Wikidata QID it asks the server `get_by_identifier
("wikidata", qid)` and, on a match, `get_person(pid)`, and writes

    p["hl"] = {id, url, n, b, d, parents, children, spouses, tree, snapshot,
               kinlinks}

to persons_resolved.json. Relatives are `{n, qid, id, g}` (name, QID, Human
Lineage id, gender); `kinlinks` are the relatives that are themselves persons of
the register (joined through their own Human Lineage id, never by name) — the
person modal renders them as clickable cross-references, like the Wikidata ones.
A second path joins persons that carry an HLS article number but no QID through
`get_by_identifier("hls", …)` (the server resolves it via Wikidata P902).

Where both ends of a parent–child or couple relation are register persons, the
pair gets an edge in families_graph.json (src="hl", conf 1.0, b_dead true — the
dump holds only the deceased). A joined person the kinship extraction never made
a tree node of gets one (id "p<index>", src="hl") and joins the relative's
family unit, or founds a new one with it. Siblings are not exported: the server
derives them from shared parents, the dump does not assert them.

Every answer is kept in `humanlineage_cache.json` (tracked: deploys are a `git
pull`), so a rebuild needs no network:

    python3 link_humanlineage.py              # cache first, server for the rest
    python3 link_humanlineage.py --offline    # cache only (fails on a miss)
    python3 link_humanlineage.py --refresh    # ignore the cache, ask again

The server is reachable inside the UniBE VPN; set $HUMANLINEAGE_MCP to use
another endpoint (inside the fleet: http://172.17.0.1:8025/mcp/humanlineage/mcp).
Only QID and HLS joins are made: the name resolver without years is weak (P@1
0.15 on this register), so the persons without an identifier stay out.

Licence: the data this stage writes is derived from Human Lineage, CC BY-SA 4.0 —
credit «Human Lineage» with the profile URL wherever it is shown.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONS = os.path.join(HERE, "persons_resolved.json")
GRAPH = os.path.join(HERE, "families_graph.json")
CACHE = os.path.join(HERE, "humanlineage_cache.json")
ENDPOINT = os.environ.get("HUMANLINEAGE_MCP",
                          "https://tei.dh.unibe.ch/mcp/humanlineage/mcp")
UA = "hgb-humanlineage-linker/1.0 (https://github.com/thodel/eos_persons; tobias.hodel@unibe.ch)"
PROFILE = "https://humanlineage.org/person/{}"

PARENT_ROLE = {"male": "Vater", "female": "Mutter"}
GENDER = {"male": "m", "female": "f"}


# ── a minimal MCP client (streamable HTTP, JSON-RPC over POST) ──────────────
class McpClient:
    """Enough of the MCP streamable-HTTP transport for `tools/call`.

    The server answers each POST either as JSON or as one SSE stream holding
    the JSON-RPC response; both are read here. Answers over 1 MB are not a
    concern for the two tools this stage uses.
    """

    def __init__(self, url=ENDPOINT, timeout=60):
        self.url, self.timeout = url, timeout
        self.session = None
        self._id = 0

    def _post(self, payload):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "User-Agent": UA}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            ctype = r.headers.get("Content-Type", "")
            body = r.read().decode("utf-8")
        if not body.strip():
            return None
        if "text/event-stream" not in ctype:
            return json.loads(body)
        want = payload.get("id")
        for event in body.split("\n\n"):
            data = "\n".join(ln[5:].lstrip() for ln in event.splitlines()
                             if ln.startswith("data:"))
            if not data:
                continue
            msg = json.loads(data)
            if want is None or msg.get("id") == want:
                return msg
        raise RuntimeError("no JSON-RPC response in the event stream")

    def _rpc(self, method, params=None):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method,
                   "params": params or {}}
        for attempt in range(5):
            try:
                msg = self._post(payload)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == 4:
                    raise
                wait = 5 * (attempt + 1)
                print(f"  {e} — retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
        if msg is None:
            raise RuntimeError(f"{method}: empty answer")
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    def connect(self):
        self._rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "eos_persons/link_humanlineage", "version": "1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def call(self, tool, **arguments):
        if self.session is None:
            self.connect()
        res = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        if res.get("isError"):
            raise RuntimeError(f"{tool}{arguments}: {res.get('content')}")
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        text = "".join(c.get("text", "") for c in res.get("content", [])
                       if c.get("type") == "text")
        return json.loads(text)


# ── the cache ────────────────────────────────────────────────────────────────
def load_cache(path=CACHE):
    if os.path.exists(path):
        c = json.load(open(path, encoding="utf-8"))
        c.setdefault("lookups", {})
        c.setdefault("persons", {})
        return c
    return {"endpoint": ENDPOINT, "snapshot": None, "fetched": None,
            "lookups": {}, "persons": {}}


def save_cache(cache, path=CACHE):
    json.dump(cache, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Lineage:
    """Cache-first access to the two tools; the client is opened lazily."""

    def __init__(self, cache, offline=False, refresh=False, client=None):
        self.cache, self.offline, self.refresh = cache, offline, refresh
        self._client = client
        self.calls = 0

    def _ask(self, tool, **args):
        if self.offline:
            raise SystemExit(f"--offline, but {tool}{args} is not in the cache "
                             f"— run once with network access")
        if self._client is None:
            self._client = McpClient().connect()
        self.calls += 1
        if self.calls % 25 == 0:
            print(f"  …{self.calls} calls", file=sys.stderr)
        out = self._client.call(tool, **args)
        snap = out.get("snapshot")
        if snap:
            if self.cache.get("snapshot") not in (None, snap):
                print(f"  note: snapshot changed {self.cache['snapshot']} → {snap}; "
                      f"use --refresh to re-ask everything", file=sys.stderr)
            self.cache["snapshot"] = snap
        self.cache["fetched"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.cache["endpoint"] = ENDPOINT
        return out

    def lookup(self, scheme, value):
        key = f"{scheme}:{value}"
        if not self.refresh and key in self.cache["lookups"]:
            return self.cache["lookups"][key]
        out = self._ask("get_by_identifier", scheme=scheme, value=value)
        self.cache["lookups"][key] = out
        return out

    def person(self, pid):
        if not self.refresh and pid in self.cache["persons"]:
            return self.cache["persons"][pid]
        out = self._ask("get_person", pid=pid)
        self.cache["persons"][pid] = out
        return out


# ── pure transforms (tested without the server) ──────────────────────────────
def relative(r):
    rec = {"n": r.get("name") or "", "qid": r.get("wikidata_id"), "id": r.get("id")}
    g = GENDER.get(r.get("gender"))
    if g:
        rec["g"] = g
    return rec


def hl_record(full, status="match"):
    """The compact `hl` block of a person from a full `get_person` answer."""
    rel = full.get("relatives") or {}
    rec = {
        "id": full["id"],
        "url": full.get("url") or PROFILE.format(full["id"]),
        "n": full.get("name") or "",
        "b": full.get("birth_year"),
        "d": full.get("death_year"),
        "parents": [relative(r) for r in rel.get("parents") or []],
        "children": [relative(r) for r in rel.get("children") or []],
        "spouses": [relative(r) for r in rel.get("spouses") or []],
        "tree": full.get("tree"),
        "snapshot": full.get("snapshot"),
    }
    if status != "match":
        rec["status"] = status
    return rec


def kinlinks(hl, by_hlid):
    """Relatives that are register persons: (role, name, qid) for the modal.

    `by_hlid` maps a Human Lineage id to the register person joined to it, so
    the cross-link is an identity join on both sides — never a name match.
    Siblings are left out on purpose (derived by the server, not asserted).
    """
    out, seen = [], set()
    for kind, role in (("parents", None), ("children", "Kind"), ("spouses", "Ehepartner")):
        for r in hl.get(kind) or []:
            tgt = by_hlid.get(r.get("id"))
            if tgt is None or tgt.get("hl", {}).get("id") == hl["id"]:
                continue
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            rr = role or {"m": "Vater", "f": "Mutter"}.get(r.get("g"), "Elternteil")
            out.append({"role": rr, "name": tgt["n"], "qid": r.get("qid"), "hlid": r["id"]})
    return out


def hl_edges(persons, by_hlid, node_of):
    """families_graph edges for parent–child and couple pairs of register persons.

    `node_of(person)` gives the tree node id or None. Returns (edges, pairs):
    the edge dicts and the set of unordered node pairs they connect.
    """
    edges, pairs = [], set()
    for p in persons:
        hl = p.get("hl")
        if not hl:
            continue
        me = node_of(p)
        if not me:
            continue
        for kind, etype in (("parents", "parent"), ("spouses", "spouse")):
            for r in hl.get(kind) or []:
                other = by_hlid.get(r.get("id"))
                if other is None:
                    continue
                on = node_of(other)
                if not on or on == me:
                    continue
                key = frozenset((me, on))
                if key in pairs:
                    continue
                pairs.add(key)
                a, b = (on, me) if etype == "parent" else (me, on)   # a = parent
                edges.append({"a": a, "b": b, "type": etype, "dir": "hl",
                              "trigger": "humanlineage", "year": None, "dossier": "",
                              "conf": 1.0, "b_dead": True, "src": "hl"})
    return edges, pairs


def _surname(name):
    toks = [t for t in name.replace(".", " ").split() if len(t) > 1 and t[0].isalpha()]
    return toks[-1].lower() if len(toks) >= 2 else None


def extend_graph(graph, persons, by_hlid, idx_of):
    """Add the Human Lineage edges (and the nodes they need) to a family graph.

    `persons` are the joined register persons, `idx_of` their index in
    persons_resolved.json (the tree's node id is "p<index>"). Nodes and edges
    this stage made earlier (src="hl") are dropped first, so a re-run is clean.
    Returns (edges added, nodes added, components added, pairs already linked).
    """
    graph["nodes"] = [n for n in graph["nodes"] if n.get("src") != "hl"]
    graph["edges"] = [e for e in graph["edges"] if e.get("src") != "hl"]
    graph["components"] = [c for c in graph["components"] if c.get("src") != "hl"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    by_key = {(n["name"], n["y"][0], n["y"][1]): n["id"]
              for n in graph["nodes"] if n.get("y")}

    def node_of(p):
        nid = f"p{idx_of[id(p)]}"
        if nid in nodes:
            return nid
        y = p.get("y")
        return (by_key.get((p["n"], y[0], y[1])) if y else None) or nid

    edges, _ = hl_edges(persons, by_hlid, node_of)
    existing = {frozenset((e["a"], e["b"])) for e in graph["edges"]}
    fresh = [e for e in edges if frozenset((e["a"], e["b"])) not in existing]

    by_nid = {node_of(p): p for p in persons}
    new_nodes = []
    for e in fresh:
        for nid in (e["a"], e["b"]):
            if nid in nodes:
                continue
            p = by_nid[nid]
            nd = {"id": nid, "name": p["n"], "linked": True,
                  "occ": (p.get("occ") or [])[:3], "y": p.get("y"),
                  "dead_year": p.get("dead_year"), "c": p.get("c", 0),
                  "cid": None, "src": "hl"}
            if p.get("hls"):
                nd["hls"] = p["hls"]
            nodes[nid] = nd
            new_nodes.append(nd)

    # family units: a new node joins the unit of the relative it is linked to;
    # a group of new nodes without one founds a unit of its own
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in fresh:
        if nodes[e["a"]]["cid"] is None or nodes[e["b"]]["cid"] is None:
            parent[find(e["a"])] = find(e["b"])
    groups = {}
    for nd in new_nodes:
        groups.setdefault(find(nd["id"]), []).append(nd["id"])
    comps = {c["cid"]: c for c in graph["components"]}
    next_cid = max(comps, default=-1) + 1
    added = 0
    for root, members in groups.items():
        cids = [nodes[n]["cid"] for n in parent if find(n) == root and nodes[n]["cid"] is not None]
        if cids:
            cid = max(cids, key=lambda c: comps[c]["size"])
        else:
            cid, next_cid = next_cid, next_cid + 1
            sur = [s for s in (_surname(nodes[n]["name"]) for n in members) if s]
            comps[cid] = {"root": members[0], "label": (sur[0] if sur else "?").title(),
                          "size": 0, "year_min": None, "year_max": None,
                          "surnames": sorted(set(sur))[:4], "cid": cid, "src": "hl"}
            graph["components"].append(comps[cid])
            added += 1
        for n in members:
            nodes[n]["cid"] = cid

    # size and year range of a unit are those of its nodes (as build_families
    # computes them); redo the units that gained nodes
    touched = {nodes[n]["cid"] for g in groups.values() for n in g}
    for cid in touched:
        members = [n for n in nodes.values() if n.get("cid") == cid]
        years = [y for n in members for y in (n.get("y") or [])]
        comps[cid].update({"size": len(members),
                           "year_min": min(years) if years else None,
                           "year_max": max(years) if years else None})
    graph["nodes"] = list(nodes.values())
    graph["edges"].extend(fresh)
    return len(fresh), len(new_nodes), added, len(edges) - len(fresh)


# ── the stage ────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="never touch the network")
    ap.add_argument("--refresh", action="store_true", help="ignore cached answers")
    args = ap.parse_args(argv)

    persons = json.load(open(PERSONS, encoding="utf-8"))
    cache = load_cache()
    hl = Lineage(cache, offline=args.offline, refresh=args.refresh)

    for p in persons:
        p.pop("hl", None)

    # canonical register person per QID (the one with most mentions), as in
    # link_wikidata_kin.py; every person sharing the QID gets the same block
    qid_person, qid_members = {}, {}
    for p in persons:
        q = (p.get("wd") or {}).get("qid")
        if not q:
            continue
        qid_members.setdefault(q, []).append(p)
        if q not in qid_person or p.get("c", 0) > qid_person[q].get("c", 0):
            qid_person[q] = p
    hls_only = [p for p in persons
                if (p.get("hls") or {}).get("id") and not (p.get("wd") or {}).get("qid")]
    print(f"{sum(len(v) for v in qid_members.values())} persons with a QID "
          f"({len(qid_person)} distinct), {len(hls_only)} with an HLS id but no QID")

    # 1 — the join
    stats = {"match": 0, "ambiguous": 0, "no_candidates": 0,
             "hls_match": 0, "hls_ambiguous": 0, "hls_no_candidates": 0}
    joined = {}            # pid -> list of register persons
    for q in sorted(qid_person):
        res = hl.lookup("wikidata", q)
        stats[res["status"]] += 1
        if res["status"] in ("match", "ambiguous") and res.get("persons"):
            pid = res["persons"][0]["id"]
            joined.setdefault(pid, []).extend((p, res["status"]) for p in qid_members[q])
    for p in hls_only:
        res = hl.lookup("hls", p["hls"]["id"])
        stats["hls_" + res["status"]] += 1
        if res["status"] in ("match", "ambiguous") and res.get("persons"):
            joined.setdefault(res["persons"][0]["id"], []).append((p, res["status"]))
    print(f"  wikidata: {stats['match']} match, {stats['ambiguous']} ambiguous, "
          f"{stats['no_candidates']} not in the snapshot")
    print(f"  hls:      {stats['hls_match']} match, {stats['hls_ambiguous']} ambiguous, "
          f"{stats['hls_no_candidates']} not in the snapshot")

    # 2 — the family
    by_hlid = {}           # HL id -> canonical register person
    for pid, members in joined.items():
        full = hl.person(pid)
        canon = max(members, key=lambda m: m[0].get("c", 0))[0]
        for p, status in members:
            p["hl"] = hl_record(full, status)
        by_hlid[pid] = canon
    save_cache(cache)
    print(f"  {hl.calls} server calls, cache {os.path.basename(CACHE)} "
          f"({len(cache['lookups'])} lookups, {len(cache['persons'])} persons, "
          f"snapshot {cache.get('snapshot')})")

    # 3 — cross-links among register persons
    n_rel = n_rel_in = n_kl = 0
    for p in persons:
        if not p.get("hl"):
            continue
        kl = kinlinks(p["hl"], by_hlid)
        if p is by_hlid.get(p["hl"]["id"]):
            n_rel += sum(len(p["hl"][k]) for k in ("parents", "children", "spouses"))
            n_rel_in += len(kl)
        if kl:
            p["hl"]["kinlinks"] = kl
            n_kl += 1
    n_linked = sum(1 for p in persons if p.get("hl"))
    json.dump(persons, open(PERSONS, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  wrote hl to {n_linked} persons ({len(joined)} Human Lineage profiles); "
          f"{n_rel} relatives of joined persons, {n_rel_in} of them register persons; "
          f"{n_kl} persons with cross-links")

    # 4 — the family graph
    graph = json.load(open(GRAPH, encoding="utf-8"))
    idx_of = {id(p): i for i, p in enumerate(persons)}
    n_edges, n_nodes, n_comps, n_dup = extend_graph(graph, list(by_hlid.values()),
                                                    by_hlid, idx_of)
    json.dump(graph, open(GRAPH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"  family graph: +{n_edges} edges (src=hl), +{n_nodes} nodes, "
          f"+{n_comps} family units; {n_dup} pairs already had an edge from the corpus or Wikidata")

    print("\nExamples:")
    shown = 0
    for p in by_hlid.values():
        kl = p["hl"].get("kinlinks")
        if kl:
            print(f"  {p['n']} ({p['hl']['id']}): " +
                  "; ".join(f"{x['role']}→{x['name']}" for x in kl))
            shown += 1
            if shown >= 12:
                break
    return {"linked_persons": n_linked, "profiles": len(joined), "edges": n_edges,
            "nodes": n_nodes, "components": n_comps,
            "relatives": n_rel, "relatives_in_corpus": n_rel_in, **stats}


if __name__ == "__main__":
    main()
