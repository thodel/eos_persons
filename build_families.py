#!/usr/bin/env python3
"""
build_families.py — extract family / genealogical structure from the HGB corpus.

Two complementary products:
  1. families_graph.json  — kinship edges between named persons, drawn from the
     <eventGroup class="family"> annotations (+ inheritance / bequest events).
  2. families_index.json  — surname-grouped overview of all persons, with the
     connected components of the kinship graph layered on as named family units.

Both link back to the canonical persons in persons_resolved.json.
"""
import re
import json
import collections
import unicodedata
from difflib import SequenceMatcher

import lxml.etree as ET

XML = "hgb_full_26_05_29_05.xml"
PERSONS = "persons_resolved.json"

# ── Relationship-type classification ─────────────────────────────────────────
# Map a (lower-cased, stripped) trigger word to a normalized relation type.
# Direction convention for asymmetric types: a is the *subject*, b the relative
# named in the apposition (e.g. trigger "Sohn", a = the son, b = the father).

SPOUSE = {
    "frau", "frow", "frowen", "frauw", "frauwen", "fraw",
    "ehefrau", "ehefrauw", "ehefrauen", "ehfrau", "ehefrauwen",
    "efrow", "efrowen", "eefrow", "eefrowen", "efruw", "eheliche frow",
    "elich frow", "eliche frow", "eliche frowe", "eeliche hus frauw",
    "ewirtin", "ewirt", "hausfrau", "husfrow", "husfrowen",
    "wittib", "witib", "witwe", "wittwe", "wittwen", "witwen", "witwer",
    "wwe", "wittfrau", "uxor", "gemahel", "gemahl", "eheman", "ehmann",
    "wirtin", "gattin",
}
WIDOW = {  # subset of spouse implying the *other* party is deceased
    "wittib", "witib", "witwe", "wittwe", "wittwen", "witwen", "wwe",
    "wittfrau", "witwer",
}
FATHER = {"vatter", "vatters", "vater", "vaters"}
MOTHER = {"mutter", "mütter", "muter"}
SON = {"sohn", "son", "sun", "sin", "sön", "söhn", "sohne", "sone"}
DAUGHTER = {"tochter", "dochter", "tochteren", "töchter"}
CHILDREN = {"kinder", "kinden", "kindern", "kind", "kinde"}
BROTHER = {"bruder", "bruders", "brüder", "gebrüder"}
SISTER = {"swester", "schwester", "swöster", "schwöster", "geschwister"}
SON_IN_LAW = {"tochterman", "dochterman", "eidam", "eydam", "tochtermann"}
DAUGHTER_IN_LAW = {"schnur", "sohnsfrau"}
GUARDIAN = {"vogt", "vögt", "vogts", "vogtt"}


def classify(trigger: str):
    """Return (type, dir) where dir describes a→b. type in:
    spouse, parent, child, sibling, in-law, guardian, kin."""
    t = trigger.strip().lower()
    t = re.sub(r"\s+", " ", t)
    if t in WIDOW:
        return ("spouse", "widow")     # a is widow/widower of b (b deceased)
    if t in SPOUSE:
        return ("spouse", "spouse")
    if t in FATHER or t in MOTHER:
        return ("parent", "b_is_child")  # a is parent of b
    if t in SON or t in DAUGHTER:
        return ("child", "a_is_child")   # a is child of b
    if t in CHILDREN:
        return ("child", "a_is_child")
    if t in BROTHER or t in SISTER:
        return ("sibling", "sibling")
    if t in SON_IN_LAW or t in DAUGHTER_IN_LAW:
        return ("in-law", "a_in_law_of_b")
    if t in GUARDIAN:
        return ("guardian", "a_guards_b")
    return (None, None)


# ── Name / surname normalization ─────────────────────────────────────────────

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def clean_name(s: str) -> str:
    s = s.replace(" .", ".").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def safe_conf(v, default=1.0):
    """confidence attrs are sometimes model names ('gpt-5.5') not floats."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# OCR / spelling surname canonicalization. Map common variant stems together.
SURNAME_CANON = {
    "meiger": "meyer", "meyger": "meyer", "meier": "meyer", "meijer": "meyer",
    "müllers": "müller", "mullers": "müller", "muller": "müller", "miller": "müller",
    "kellers": "keller", "vischer": "fischer", "fyscher": "fischer",
    "fischers": "fischer", "schmidt": "schmid", "schmied": "schmid",
    "schmidts": "schmid", "beck": "beckh", "becker": "beckh",
    "jselin": "iselin", "yselin": "iselin", "yselin": "iselin",
    "burckhard": "burckhardt", "burkhardt": "burckhardt",
}


def surname_key(name: str) -> "str | None":
    """Normalized surname (family key) from a full name, or None."""
    toks = clean_name(name).replace(".", " ").split()
    toks = [t for t in toks if len(t) > 1]
    if len(toks) < 2:
        return None
    last = strip_accents(toks[-1].lower())
    last = re.sub(r"[^a-zäöü]", "", toks[-1].lower())
    last = strip_accents(last)
    if not last:
        return None
    # strip genitive -s if it yields a known stem
    cand = SURNAME_CANON.get(last, last)
    if cand.endswith("s") and len(cand) > 4:
        stem = cand[:-1]
        cand = SURNAME_CANON.get(stem, cand)
    return SURNAME_CANON.get(cand, cand)


# ── Identity resolution: merge OCR / spelling variants of one person ──────────

def name_tokens(name):
    toks = re.sub(r"[^\wäöü]", " ", strip_accents(name.lower())).split()
    return [t for t in toks if len(t) > 1]


def _ratio(a, b):
    if a == b:
        return 1.0
    if a and b and a[0] != b[0]:
        return 0.0          # first-char blocking (cheap reject)
    return SequenceMatcher(None, a, b).ratio()


def given_surname(name):
    toks = name_tokens(name)
    if len(toks) >= 2:
        return toks[0], toks[-1]
    if toks:
        return toks[0], None
    return None, None


def names_similar(a, b):
    """True if a and b are plausibly the same person's name (OCR/variant)."""
    ga, sa = given_surname(a)
    gb, sb = given_surname(b)
    if not ga or not gb:
        return False
    if sa and sb:
        gr, sr = _ratio(ga, gb), _ratio(sa, sb)
        return gr >= 0.80 and sr >= 0.82 and (gr + sr) / 2 >= 0.86
    # at least one is given-name only — require a strong given-name match
    return ga == gb or _ratio(ga, gb) >= 0.90


def years_align(wa, wb):
    """None if unknown; True if windows plausibly one lifespan; False if not."""
    if wa is None or wb is None:
        return None
    lo, hi = min(wa[0], wb[0]), max(wa[1], wb[1])
    if hi - lo > 80:
        return False
    gap = max(wa[0], wb[0]) - min(wa[1], wb[1])   # >0 ⇒ disjoint
    return gap <= 20


def resolve_identities(nodes, edges):
    """Collapse nodes that are very likely the same person.

    Two passes, both conservative to avoid re-forming spurious hubs:
      • global  — surnamed nodes anywhere, requiring aligned year windows;
      • local   — any nodes inside the same relationship component (already
                  time-bounded), allowing merges when year info is missing.
    Returns (new_nodes_dict, new_edges_list).
    """
    # year window per node: own span + years seen on incident edges
    edge_years = collections.defaultdict(list)
    for e in edges:
        if e.get("year"):
            edge_years[e["a"]].append(e["year"])
            edge_years[e["b"]].append(e["year"])

    def window(nid):
        n = nodes[nid]
        yrs = list(edge_years.get(nid, []))
        if n.get("y"):
            yrs += [n["y"][0], n["y"][1]]
        yrs = [y for y in yrs if y]
        return (min(yrs), max(yrs)) if yrs else None

    win = {nid: window(nid) for nid in nodes}

    # union-find over identities, tracking each group's merged year window so a
    # chain of pairwise-close merges can never span more than one lifespan.
    parent = {nid: nid for nid in nodes}
    grp_win = {nid: win[nid] for nid in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def merged_window(wa, wb):
        if wa is None:
            return wb
        if wb is None:
            return wa
        return (min(wa[0], wb[0]), max(wa[1], wb[1]))
    def union(a, b, cap=True):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        mw = merged_window(grp_win[ra], grp_win[rb])
        if cap and mw is not None and mw[1] - mw[0] > 80:
            return False                 # would exceed a lifespan — refuse
        parent[ra] = rb
        grp_win[rb] = mw
        return True

    def surnamed(nid):
        g, s = given_surname(nodes[nid]["name"])
        return g is not None and s is not None

    # Same-person variants that share family context are merged by the local
    # pass below. The global pass only fuses same-named nodes from *different*
    # contexts — safe for distinctive names, but for very common surnames
    # (Meyer, Müller, Keller…) it risks merging unrelated families. So restrict
    # global merges to surnames that are not corpus-common.
    sur_freq = collections.Counter()
    for nid in nodes:
        sk = surname_key(nodes[nid]["name"])
        if sk:
            sur_freq[sk] += 1
    COMMON = 40   # nodes sharing a surname above this ⇒ too ambiguous to merge globally

    # ── Pass 1: global merge of surnamed nodes, blocked by initials ──
    # Strict: names similar, windows actually overlap, group stays ≤ 80 yr.
    blocks = collections.defaultdict(list)
    for nid in nodes:
        if not surnamed(nid):
            continue
        g, s = given_surname(nodes[nid]["name"])
        blocks[(g[0], s[0])].append(nid)
    merged_global = 0
    for key, members in blocks.items():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if find(a) == find(b):
                    continue
                wa, wb = win[a], win[b]
                if wa is None or wb is None:
                    continue             # global merge needs dated overlap
                gap = max(wa[0], wb[0]) - min(wa[1], wb[1])
                if gap > 5:              # require (near-)overlap, not just ≤20
                    continue
                ska, skb = surname_key(nodes[a]["name"]), surname_key(nodes[b]["name"])
                if (sur_freq.get(ska, 0) > COMMON) or (sur_freq.get(skb, 0) > COMMON):
                    continue             # too common to disambiguate by name alone
                if not names_similar(nodes[a]["name"], nodes[b]["name"]):
                    continue
                if union(a, b):
                    merged_global += 1

    # ── Pass 2: local merge within relationship components ──
    cparent = {nid: nid for nid in nodes}
    def cfind(x):
        while cparent[x] != x:
            cparent[x] = cparent[cparent[x]]
            x = cparent[x]
        return x
    for e in edges:
        ra, rb = cfind(e["a"]), cfind(e["b"])
        if ra != rb:
            cparent[ra] = rb
    comp_members = collections.defaultdict(list)
    for nid in nodes:
        comp_members[cfind(nid)].append(nid)
    merged_local = 0
    for members in comp_members.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if find(a) == find(b):
                    continue
                if not names_similar(nodes[a]["name"], nodes[b]["name"]):
                    continue
                if years_align(win[a], win[b]) is not False:   # True or None
                    if union(a, b):
                        merged_local += 1

    # ── Collapse: pick representative per identity group ──
    groups = collections.defaultdict(list)
    for nid in nodes:
        groups[find(nid)].append(nid)

    def rep_rank(nid):
        n = nodes[nid]
        return (1 if n.get("linked") else 0, n.get("c", 0), len(n["name"]))

    remap = {}
    new_nodes = {}
    for members in groups.values():
        rep = max(members, key=rep_rank)
        base = dict(nodes[rep])
        variants = set(base.get("v", []))
        occ = list(base.get("occ", []))
        cc = 0
        ymins, ymaxs, deads = [], [], []
        for nid in members:
            remap[nid] = rep
            n = nodes[nid]
            if n["name"] != base["name"]:
                variants.add(n["name"])
            for o in n.get("occ", []):
                if o not in occ:
                    occ.append(o)
            cc += n.get("c", 0)
            if n.get("y"):
                ymins.append(n["y"][0]); ymaxs.append(n["y"][1])
            if n.get("dead_year"):
                deads.append(n["dead_year"])
        base["v"] = sorted(variants)
        base["occ"] = occ[:4]
        base["c"] = cc
        base["linked"] = any(nodes[m].get("linked") for m in members)
        if ymins:
            base["y"] = [min(ymins), max(ymaxs)]
        if deads:
            base["dead_year"] = min(deads)
        base["id"] = rep
        new_nodes[rep] = base

    # ── Remap + dedup edges ──
    seen = set()
    new_edges = []
    for e in edges:
        a, b = remap[e["a"]], remap[e["b"]]
        if a == b:
            continue
        key = (a, b, e["type"])
        if key in seen:
            continue
        seen.add(key)
        e2 = dict(e); e2["a"], e2["b"] = a, b
        new_edges.append(e2)

    print(f"  identity merge: {len(nodes)}→{len(new_nodes)} nodes "
          f"(global {merged_global}, local {merged_local}); "
          f"{len(edges)}→{len(new_edges)} edges")
    return new_nodes, new_edges, remap


# ── Resolve a <span> subtree to its head name ────────────────────────────────

def head_name(span):
    """Find the head 'nam' descendant within a per-reference span; return name."""
    # direct head nam child
    for el in span.iter():
        if el is span:
            continue
        if el.get("element") == "head" and el.get("class") == "nam":
            return clean_name(el.get("text", ""))
    # fallback: any nam
    for el in span.iter():
        if el.get("class") == "nam":
            return clean_name(el.get("text", ""))
    return None


def span_is_dead(span):
    for el in span.iter():
        if el.get("class") == "dead":
            return True
    return False


# ── Pass 1: stream documents, collect raw kinship edges ──────────────────────

def extract_edges():
    raw_edges = []   # dicts: a_name, b_name, type, dir, year, dossier, conf, b_dead
    context = ET.iterparse(XML, events=("end",), tag="document", recover=True)
    n_docs = 0
    for _, doc in context:
        n_docs += 1
        meta = doc.find("metadata")
        if meta is None:
            doc.clear(); continue
        dossier = meta.get("dossierid", "")
        yr_raw = meta.get("year", "")
        year = int(yr_raw) if yr_raw.isdigit() else None

        # build span-id -> element index
        spans = {}
        for sp in doc.iter("span"):
            sid = sp.get("id")
            if sid is not None:
                spans[sid] = sp

        # coref map: pronoun/reference span -> antecedent span id
        coref = {}
        for rel in doc.iter("relation"):
            if rel.get("class") == "coref":
                frm, to = rel.get("from"), rel.get("to")
                if frm and to:
                    coref[frm] = to

        def resolve(ref, _depth=0):
            sp = spans.get(ref)
            if sp is None:
                return None, False
            nm = head_name(sp)
            if not nm and ref in coref and _depth < 4:
                # pronoun / bare reference — follow coref to antecedent
                return resolve(coref[ref], _depth + 1)
            return nm, span_is_dead(sp)

        for eg in doc.iter("eventGroup"):
            cls = eg.get("class")
            if cls not in ("family", "inheritance", "bequest", "testament"):
                continue

            if cls == "family":
                trig = eg.find("trigger")
                trig_text = trig.get("text", "") if trig is not None else ""
                rtype, rdir = classify(trig_text)
                if rtype is None:
                    continue
                for ev in eg.iter("event"):
                    roles = {r.get("role"): r for r in ev.iter("role")}
                    ra = roles.get("family-a")
                    rb = roles.get("family-b")
                    if ra is None or rb is None:
                        continue
                    a_name, _ = resolve(ra.get("ref"))
                    b_name, b_dead = resolve(rb.get("ref"))
                    if not a_name or not b_name:
                        continue
                    if a_name == b_name:
                        continue
                    conf = min(safe_conf(ra.get("confidence")),
                               safe_conf(rb.get("confidence")))
                    raw_edges.append({
                        "a": a_name, "b": b_name,
                        "type": rtype, "dir": rdir,
                        "trigger": trig_text.strip().lower(),
                        "year": year, "dossier": dossier,
                        "conf": round(conf, 2),
                        "b_dead": b_dead or (rdir == "widow"),
                    })
            else:
                # inheritance / bequest / testament -> heir edge testator->heir
                for ev in eg.iter("event"):
                    roles = {r.get("role"): r for r in ev.iter("role")}
                    # role names vary; try common ones
                    giver = next((roles[k] for k in
                                  ("testator", "benefactor", "deceased", "owner")
                                  if k in roles), None)
                    taker = next((roles[k] for k in
                                  ("heir", "beneficiary", "recipient")
                                  if k in roles), None)
                    if giver is None or taker is None:
                        continue
                    g_name, g_dead = resolve(giver.get("ref"))
                    t_name, _ = resolve(taker.get("ref"))
                    if not g_name or not t_name or g_name == t_name:
                        continue
                    raw_edges.append({
                        "a": t_name, "b": g_name,   # a inherits from b
                        "type": "heir", "dir": "a_heir_of_b",
                        "trigger": cls,
                        "year": year, "dossier": dossier,
                        "conf": 0.9,
                        "b_dead": True,
                    })
        doc.clear()
        if n_docs % 10000 == 0:
            print(f"  …{n_docs} docs, {len(raw_edges)} edges")
    print(f"Parsed {n_docs} docs → {len(raw_edges)} raw kinship edges")
    return raw_edges


# ── Pass 2: link edge endpoints to canonical persons ─────────────────────────

def load_persons():
    with open(PERSONS) as f:
        persons = json.load(f)
    # index: exact canonical name + variants -> person idx
    name_to_idx = {}
    for i, p in enumerate(persons):
        for nm in [p["n"]] + p.get("v", []):
            name_to_idx.setdefault(clean_name(nm), i)
    # also dossier-scoped name -> idx for disambiguation
    dos_name_to_idx = collections.defaultdict(list)
    for i, p in enumerate(persons):
        for entry in p.get("dos", []):
            did = entry[0] if isinstance(entry, list) else entry
            nm = entry[1] if isinstance(entry, list) and len(entry) > 1 else p["n"]
            dos_name_to_idx[(did, clean_name(nm))].append(i)
    return persons, name_to_idx, dos_name_to_idx


def link_person(name, dossier, persons, name_to_idx, dos_name_to_idx):
    """Resolve a raw name (in a dossier) to a canonical person index, or None."""
    cn = clean_name(name)
    # 1. dossier-scoped exact
    hit = dos_name_to_idx.get((dossier, cn))
    if hit:
        return hit[0]
    # 2. global exact on name or variant
    if cn in name_to_idx:
        return name_to_idx[cn]
    # 3. fuzzy: same surname + given-initial within dossier members
    return None


# ── Cross-family bridges ─────────────────────────────────────────────────────

def build_bridges(nodes, components, comp_of):
    """Link nodes in *different* families that are plausibly the same person
    (same name, overlapping dates). These are the marriage/kin ties between
    families that connected-component splitting hides. We keep only bridges
    between components with *different* dominant surnames — same-surname links
    are either the same lineage or risky look-alikes, not cross-family ties."""
    comp_label = {c["cid"]: c["label"] for c in components}

    # node year window from own span (edges already folded into nodes via merge)
    def win(n):
        return tuple(n["y"]) if n.get("y") else None

    # only surnamed, dated, in a real (multi-person) component
    cand = []
    for nid, n in nodes.items():
        if comp_of.get(nid) is None:
            continue
        g, s = given_surname(n["name"])
        if not g or not s or not n.get("y"):
            continue
        cand.append(nid)

    # block by (given-initial, surname-initial) to keep comparisons cheap
    blocks = collections.defaultdict(list)
    for nid in cand:
        g, s = given_surname(nodes[nid]["name"])
        blocks[(g[0], s[0])].append(nid)

    bridges = []
    seen_pairs = set()
    for members in blocks.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            a = members[i]
            ca = comp_of[a]
            for j in range(i + 1, len(members)):
                b = members[j]
                cb = comp_of[b]
                if ca == cb:
                    continue                     # same family — already shown
                if comp_label.get(ca) == comp_label.get(cb):
                    continue                     # same surname — not cross-family
                if years_align(win(nodes[a]), win(nodes[b])) is not True:
                    continue
                if not names_similar(nodes[a]["name"], nodes[b]["name"]):
                    continue
                key = (a, b)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                bridges.append({
                    "a": a, "b": b, "ca": ca, "cb": cb,
                    "name": nodes[a]["name"],
                })
    return bridges


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Pass 1: extracting kinship edges from XML…")
    raw_edges = extract_edges()

    print("Pass 2: loading canonical persons…")
    persons, name_to_idx, dos_name_to_idx = load_persons()

    # Resolve endpoints to person indices; keep node registry.
    # Node id = canonical person idx ("p123") or a dangling name node ("n:Name").
    nodes = {}           # node_id -> node dict
    edges = []
    CONF_MIN = 0.0       # keep all for counts; UI can filter

    def has_surname(name):
        # ≥2 alphabetic tokens (given + family); the "-in" feminine forms count
        toks = [t for t in clean_name(name).replace(".", " ").split() if len(t) > 1]
        return len(toks) >= 2

    def node_for(name, dossier):
        # Bare given names ("Margretha", "Anna") are not stable identities — many
        # different women share them. Resolving them to one canonical person turns
        # them into spurious hubs that chain unrelated families together. Scope
        # such endpoints to their dossier so they stay document-local.
        if not has_surname(name):
            nid = f"g:{dossier}:{clean_name(name)}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "name": clean_name(name),
                              "linked": False, "ambiguous": True, "occ": [],
                              "y": None, "dead_year": None, "c": 0}
            return nid
        idx = link_person(name, dossier, persons, name_to_idx, dos_name_to_idx)
        if idx is not None:
            nid = f"p{idx}"
            if nid not in nodes:
                p = persons[idx]
                nodes[nid] = {
                    "id": nid, "name": p["n"], "linked": True,
                    "occ": p.get("occ", [])[:3],
                    "y": p.get("y"), "dead_year": p.get("dead_year"),
                    "c": p.get("c", 0),
                }
            return nid
        # dangling (has surname but no canonical match) — scope to dossier to be safe
        nid = f"n:{dossier}:{clean_name(name)}"
        if nid not in nodes:
            nodes[nid] = {"id": nid, "name": clean_name(name),
                          "linked": False, "occ": [], "y": None,
                          "dead_year": None, "c": 0}
        return nid

    seen = set()
    for e in raw_edges:
        an = node_for(e["a"], e["dossier"])
        bn = node_for(e["b"], e["dossier"])
        if an == bn:
            continue
        # dedup identical typed edges between same pair
        key = (an, bn, e["type"])
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "a": an, "b": bn, "type": e["type"], "dir": e["dir"],
            "trigger": e["trigger"], "year": e["year"],
            "dossier": e["dossier"], "conf": e["conf"],
            "b_dead": e["b_dead"],
        })

    print(f"  {len(nodes)} nodes ({sum(1 for n in nodes.values() if n['linked'])} linked), "
          f"{len(edges)} unique edges")

    # ── Merge OCR / spelling variants of the same person ──
    nodes, edges, id_remap = resolve_identities(nodes, edges)

    # ── Connected components (family units) ──
    parent = {nid: nid for nid in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for e in edges:
        union(e["a"], e["b"])

    comp = collections.defaultdict(list)
    for nid in nodes:
        comp[find(nid)].append(nid)

    # name each component by its dominant surname
    components = []
    for root, members in comp.items():
        if len(members) < 2:
            continue
        sur = collections.Counter()
        years = []
        for nid in members:
            nm = nodes[nid]["name"]
            sk = surname_key(nm)
            if sk:
                sur[sk] += 1
            y = nodes[nid].get("y")
            if y:
                years += [y[0], y[1]]
        label = sur.most_common(1)[0][0].title() if sur else "?"
        components.append({
            "root": root,
            "label": label,
            "size": len(members),
            "members": members,
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "surnames": [s for s, _ in sur.most_common(4)],
        })
    components.sort(key=lambda c: -c["size"])
    # assign component id back onto nodes
    comp_of = {}
    for i, c in enumerate(components):
        c["cid"] = i
        for nid in c["members"]:
            comp_of[nid] = i
    for nid, n in nodes.items():
        n["cid"] = comp_of.get(nid)

    # ── Cross-family bridges ──
    # The same individual often appears in two different family trees — e.g. a
    # woman who married into one lineage is a leaf there but a full member of
    # her birth family's tree. Such pairs were deliberately NOT merged (that
    # would fuse whole families into one giant component); instead we expose
    # them as on-demand bridges so the tree can be expanded across families.
    bridges = build_bridges(nodes, components, comp_of)
    # tag nodes with how many cross-family bridges they carry
    bridge_deg = collections.Counter()
    for br in bridges:
        bridge_deg[br["a"]] += 1
        bridge_deg[br["b"]] += 1
    for nid, n in nodes.items():
        if bridge_deg.get(nid):
            n["xf"] = bridge_deg[nid]   # cross-family link count

    graph = {
        "nodes": list(nodes.values()),
        "edges": edges,
        "bridges": bridges,
        "components": [{k: v for k, v in c.items() if k != "members"}
                       for c in components],
    }
    print(f"  {len(bridges)} cross-family bridges over "
          f"{sum(1 for n in nodes.values() if n.get('xf'))} bridge nodes")
    with open("families_graph.json", "w") as f:
        json.dump(graph, f, separators=(",", ":"))
    import os
    print(f"families_graph.json: {os.path.getsize('families_graph.json')/1024:.0f} KB, "
          f"{len(components)} multi-person family units")

    # ── Surname index (overview) over ALL persons ──
    fam_index = collections.defaultdict(lambda: {
        "n_persons": 0, "n_mentions": 0, "years": [], "occ": collections.Counter(),
        "given": collections.Counter(), "dossiers": set(), "cids": set(),
    })
    # map person idx -> its node id for cid lookup
    idx_to_node = {nid: nid for nid in nodes}
    for i, p in enumerate(persons):
        sk = surname_key(p["n"])
        if not sk:
            continue
        rec = fam_index[sk]
        rec["n_persons"] += 1
        rec["n_mentions"] += p.get("c", 0)
        if p.get("y"):
            rec["years"] += [p["y"][0], p["y"][1]]
        for o in p.get("occ", []):
            rec["occ"][o] += 1
        toks = clean_name(p["n"]).replace(".", " ").split()
        if toks:
            rec["given"][toks[0]] += 1
        for entry in p.get("dos", []):
            did = entry[0] if isinstance(entry, list) else entry
            rec["dossiers"].add(did)
        nid = id_remap.get(f"p{i}", f"p{i}")   # follow identity merges
        if nid in nodes and nodes[nid].get("cid") is not None:
            rec["cids"].add(nodes[nid]["cid"])

    fam_list = []
    for sk, rec in fam_index.items():
        if rec["n_persons"] < 2:
            continue
        fam_list.append({
            "key": sk,
            "name": sk.title(),
            "n_persons": rec["n_persons"],
            "n_mentions": rec["n_mentions"],
            "year_min": min(rec["years"]) if rec["years"] else None,
            "year_max": max(rec["years"]) if rec["years"] else None,
            "occ": [o for o, _ in rec["occ"].most_common(4)],
            "given": [g for g, _ in rec["given"].most_common(5)],
            "n_dossiers": len(rec["dossiers"]),
            "cids": sorted(rec["cids"]),
        })
    fam_list.sort(key=lambda f: -f["n_persons"])
    with open("families_index.json", "w") as f:
        json.dump({"families": fam_list}, f, separators=(",", ":"))
    print(f"families_index.json: {os.path.getsize('families_index.json')/1024:.0f} KB, "
          f"{len(fam_list)} surname-families")

    # quick sanity print
    print("\nTop 12 surname-families:")
    for fam in fam_list[:12]:
        print(f"  {fam['name']:16s} {fam['n_persons']:5d} persons  "
              f"{fam['year_min']}–{fam['year_max']}  occ={fam['occ'][:2]}")
    print("\nLargest kinship components:")
    for c in components[:8]:
        print(f"  {c['label']:16s} {c['size']:4d} members  "
              f"{c['year_min']}–{c['year_max']}")
    et = collections.Counter(e["type"] for e in edges)
    print(f"\nEdge types: {dict(et)}")


if __name__ == "__main__":
    main()
