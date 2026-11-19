#!/usr/bin/env python3
"""
link_bli_hgb.py — connect the actor list of *Basler Liegenschaften 1400–1700
Interaktiv* (BLI) with the eos person lists, and use the comparison to find
errors on either side.

BLI (https://dhbern.github.io/basler-liegenschaften-interaktiv/, repository
DHBern/basler-liegenschaften-interaktiv, read-only here) shows the ownership
history of every property of the Historisches Grundbuch on a map. Its data sit
in three files:

    prepare_data/actors.json        179,982 actors, ids in dossier order
                                    {c: per|org|…, n, variants[], doc{owner: [doc…]},
                                     occ, d_yr, rel{wife: [actor…]}, …}
    prepare_data/documents.json     75,273 documents {y, txt, img[], dossier}
    prepare_data/geometries.geojson 4,338 properties {id, adrs, d[], h[{p, fc, lc, doc}]}

Both projects start from the same annotated register cards, but resolve
identity at different levels:

    BLI actor            one property (dossier) and its neighbours
    hgb_street_persons   one street                 (build_hgb_street_persons.py)
    persons_resolved     the whole city, deduplicated (build_data.py + dedupe_*.py)

So a BLI actor should sit inside one street person, and that inside one
city-wide person. Where the nesting breaks, one of the resolutions is wrong —
that is what this script looks for.

How the lists are joined
------------------------
1. documents — same id where the release did not change; the 1,864 documents
   that the corpus re-issued under a new id (page order corrected, release
   0.3.0) are matched by their page images.
2. actor → eos mentions — an owner actor carries its documents, so its name
   variants are looked up among the eos mentions of exactly those documents
   (level "doc"). Actors without documents (neighbours, relatives) are placed
   through the id order, which follows the dossiers, and matched by name inside
   the dossier (level "dossier").
3. mention → eos person — dossier + name + year identify the city-wide person
   (98.7 % uniquely) and the street person.

Outputs
-------
    link_bli_hgb.csv         one row per named BLI person actor: its dossier,
                             documents, the eos persons and street persons it
                             resolves to, and flags
    bli_doc_crosswalk.csv    BLI document id → current corpus id (re-issued only)
    bli_hgb_findings.csv     one row per discrepancy, typed and scored
    bli_hgb_report.md        counts and examples per finding type

    python3 link_bli_hgb.py                       # sibling checkout or .bli_cache/
    python3 link_bli_hgb.py --bli /path/to/basler-liegenschaften-interaktiv
    python3 link_bli_hgb.py --fetch               # download the three files first

Needs persons.csv + documents.csv (extract_persons.py), persons_resolved.json and,
optionally, hgb_street_persons.json (build_hgb_street_persons.py).
"""
import argparse
import collections
import csv
import json
import os
import re
import sys
import urllib.request
from difflib import SequenceMatcher

from dedupe_corpus import canon, koelner, name_tokens

csv.field_size_limit(10 ** 8)
HERE = os.path.dirname(os.path.abspath(__file__))
BLI_URL = "https://dhbern.github.io/basler-liegenschaften-interaktiv/"
BLI_FILES = ("prepare_data/actors.json", "prepare_data/documents.json",
             "prepare_data/geometries.geojson")
BLI_DIRS = (os.environ.get("BLI_DIR"),
            os.path.join(HERE, "..", "basler-liegenschaften-interaktiv"),
            os.path.join(HERE, "..", "dhbern", "basler-liegenschaften-interaktiv"),
            os.path.join(HERE, ".bli_cache"))

LIFESPAN = 80          # as in build_data / dedupe_corpus
DEAD_GRACE = 15        # a first live mention this long after a death = another person

# BLI builds placeholder actors for unnamed relatives ("widow of Hans Meyer").
SYNTHETIC = re.compile(
    r"^(?:widow|heir|children|husband|wife|mother|father|son|daughter|relative|"
    r"sibling|brother|sister|parent|in-law|decedent|late husband|none|null) of ",
    re.I)


def nkey(s):
    """Name key: lower-case, punctuation dropped, whitespace collapsed.

    'Joh . Grefin' (eos keeps tokens apart) == 'Joh. Grefin' (BLI glues them).
    """
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def num(actor_id):
    return int(actor_id.rsplit("_", 1)[1])


# ── inputs ───────────────────────────────────────────────────────────────────

def bli_dir(explicit=None, fetch=False):
    if fetch:
        d = os.path.join(HERE, ".bli_cache")
        for rel in BLI_FILES:
            dst = os.path.join(d, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            print(f"  fetching {rel} …", file=sys.stderr)
            urllib.request.urlretrieve(BLI_URL + rel, dst)
        return d
    for d in (explicit,) + BLI_DIRS:
        if d and os.path.exists(os.path.join(d, BLI_FILES[0])):
            return os.path.abspath(d)
    sys.exit("link_bli_hgb: BLI data not found — clone DHBern/basler-liegenschaften-"
             "interaktiv next to this repo, set $BLI_DIR, or pass --fetch")


def load_bli(d):
    def j(rel):
        return json.load(open(os.path.join(d, rel), encoding="utf-8"))
    actors, docs, geo = (j(r) for r in BLI_FILES)
    props = {}
    for f in geo["features"]:
        p = f["properties"]
        h = p.get("h")
        p["h"] = json.loads(h) if isinstance(h, str) else (h or [])
        props[p["id"]] = p
    return actors, docs, props


def load_eos_documents(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["doc_id"]] = {
                "dossier": r["dossierid"],
                "year": int(r["year"]) if r["year"] else None,
                "pages": [u for u in r["page_urls"].split("|") if u],
            }
    return out


def load_mentions(path):
    by_doc = collections.defaultdict(list)
    by_dossier = collections.defaultdict(lambda: collections.defaultdict(list))
    n = 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = {
                "doc": r["doc_id"], "dossier": r["dossierid"], "name": r["name"],
                "key": nkey(r["name"]),
                "year": int(r["year"]) if r["year"] else None,
                "dead": r["is_deceased"] == "1",
                "occ": [o for o in (r["occupation_norm"] or "").split("|")
                        if o and o != "unk"],
                "roles": [x for x in (r["roles"] or "").split("|") if x],
            }
            by_doc[m["doc"]].append(m)
            by_dossier[m["dossier"]][m["key"]].append(m)
            n += 1
    return by_doc, by_dossier, n


# ── document crosswalk ───────────────────────────────────────────────────────

def doc_crosswalk(bli_docs, eos_docs):
    """BLI doc id → eos doc id. Identity where the id survived; otherwise the
    eos document made of the same page images."""
    xw, reissued = {}, {}
    by_pages = {}
    for did, d in eos_docs.items():
        if did not in bli_docs and d["pages"]:
            by_pages[frozenset(d["pages"])] = did
    for did, d in bli_docs.items():
        if did in eos_docs:
            xw[did] = did
            continue
        hit = by_pages.get(frozenset(d.get("img") or []))
        if hit:
            xw[did] = hit
            reissued[did] = hit
    return xw, reissued


# ── eos person lookups ───────────────────────────────────────────────────────

def pkey(p):
    y = p.get("y") or [0, 0]
    return f"{p['n']}#{y[0]}-{y[1]}"


class CorpusIndex:
    """mention (dossier, name key, year) → city-wide person."""

    def __init__(self, persons):
        self.P = persons
        self.DS, self.pairs = [], collections.defaultdict(list)
        self.by_key = collections.defaultdict(list)
        for i, p in enumerate(persons):
            ds = set()
            for e in p.get("dos", []):
                if isinstance(e, list):
                    ds.add(e[0])
                    if len(e) > 1:
                        self.pairs[(e[0], nkey(e[1]))].append(i)
                else:
                    ds.add(e)
            self.DS.append(ds)
            for k in {nkey(p["n"])} | {nkey(v) for v in p.get("v", [])}:
                self.by_key[k].append(i)
        self.cache = {}

    def _in(self, i, year):
        y = self.P[i].get("y")
        return year is None or not y or y[0] <= year <= y[1]

    def resolve(self, dossier, key, year):
        ck = (dossier, key, year)
        if ck in self.cache:
            return self.cache[ck]
        named = self.by_key.get(key, [])
        here = [i for i in named if dossier in self.DS[i]]
        ok = [i for i in here if self._in(i, year)]
        if len(ok) == 1:
            r = (ok[0], "unique", ok)
        elif len(ok) > 1:
            # two persons carry this very name in this dossier at this time
            exact = [i for i in ok if i in self.pairs.get((dossier, key), [])]
            pick = exact[0] if len(exact) == 1 else max(ok, key=lambda i: self.P[i].get("c", 0))
            r = (pick, "ambiguous", ok)
        elif here:
            def dist(i):
                y = self.P[i]["y"]
                return min(abs(year - y[0]), abs(year - y[1]))
            r = (min(here, key=dist), "year_outside", here)
        else:
            trunc = [i for i in named if self._in(i, year)
                     and self.P[i].get("d", 0) > len(self.DS[i])]
            anyy = [i for i in named if self._in(i, year)]
            if len(trunc) == 1:
                r = (trunc[0], "dossier_list_truncated", trunc)
            elif len(anyy) == 1:
                r = (anyy[0], "name_year_only", anyy)
            else:
                r = (None, "unmapped", [])
        self.cache[ck] = r
        return r


class StreetIndex:
    """mention (dossier, name key, year) → street-level person."""

    def __init__(self, records):
        self.R = records
        self.idx = collections.defaultdict(list)
        for i, r in enumerate(records):
            keys = {nkey(r["name"])} | {nkey(v) for v in r.get("variants", [])}
            for d in r.get("dossiers", []):
                for k in keys:
                    self.idx[(d, k)].append(i)

    def resolve(self, dossier, key, year):
        c = self.idx.get((dossier, key), [])
        if year is not None:
            ok = [i for i in c if self.R[i]["years"][0] <= year <= self.R[i]["years"][1]]
            c = ok or c
        return c[0] if len(c) == 1 else (max(c, key=lambda i: self.R[i]["n"]) if c else None)


# ── name comparison ──────────────────────────────────────────────────────────

REL_ORDER = ["spelling", "bare_name", "given_name_count", "surname_differs",
             "given_differs", "different"]


def _ratio(a, b):
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def name_relation(a, b):
    """How two person names relate, tolerant of HTR noise.

    spelling          same number of given names, each ≥0.75 similar after
                      canonicalisation (Hanns=Hans=Johann), surnames phonetically
                      equal, ≥0.6 similar or equal up to a genitive/dative ending
    bare_name         one side is a single token found in the other
    given_name_count  surnames agree, one side has a given name more
                      (Hans / Hans Heinrich — often two different men)
    surname_differs   given names agree, surnames do not
    given_differs     surnames agree, given names do not
    different         nothing in common
    """
    ta = [canon(t) for t in name_tokens(a)]
    tb = [canon(t) for t in name_tokens(b)]
    if not ta or not tb:
        return "different"
    if len(ta) == 1 or len(tb) == 1:
        s, l = (ta, tb) if len(ta) == 1 else (tb, ta)
        return "bare_name" if any(_ratio(s[0], t) >= 0.75 for t in l) else "different"
    ga, gb, sa, sb = ta[:-1], tb[:-1], ta[-1], tb[-1]
    sur_ok = (_ratio(sa, sb) >= 0.6 or koelner(sa) == koelner(sb)
              or sa.rstrip("sn") == sb.rstrip("sn"))
    giv_same = len(ga) == len(gb) and all(_ratio(x, y) >= 0.75 for x, y in zip(ga, gb))
    if giv_same and sur_ok:
        return "spelling"
    if giv_same:
        return "surname_differs"
    if sur_ok:
        short, long_ = (ga, gb) if len(ga) <= len(gb) else (gb, ga)
        if len(ga) != len(gb) and all(any(_ratio(x, y) >= 0.75 for y in long_) for x in short):
            return "given_name_count"
        return "given_differs"
    return "different"


def group_relation(groups):
    """Worst relation between name groups, each pair of groups judged by its
    best-matching pair of names (a person is known by all its spellings)."""
    worst = 0
    for i, ga in enumerate(groups):
        for gb in groups[i + 1:]:
            best = min(REL_ORDER.index(name_relation(x, y)) for x in ga for y in gb)
            worst = max(worst, best)
    return REL_ORDER[worst]


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bli", default=None, help="checkout of basler-liegenschaften-interaktiv")
    ap.add_argument("--fetch", action="store_true", help="download the BLI data files first")
    ap.add_argument("--persons", default=os.path.join(HERE, "persons_resolved.json"))
    ap.add_argument("--mentions", default=os.path.join(HERE, "persons.csv"))
    ap.add_argument("--documents", default=os.path.join(HERE, "documents.csv"))
    ap.add_argument("--street", default=os.path.join(HERE, "hgb_street_persons.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "link_bli_hgb.csv"))
    ap.add_argument("--findings", default=os.path.join(HERE, "bli_hgb_findings.csv"))
    ap.add_argument("--report", default=os.path.join(HERE, "bli_hgb_report.md"))
    ap.add_argument("--docxw", default=os.path.join(HERE, "bli_doc_crosswalk.csv"))
    args = ap.parse_args(argv)

    S = collections.OrderedDict()          # numbers for the report
    F = []                                 # findings
    EX = collections.defaultdict(list)     # examples per finding type

    def finding(kind, side, severity, dossier, bli, eos, evidence):
        F.append({"type": kind, "likely_side": side, "severity": severity,
                  "dossier": dossier, "bli": bli, "eos": eos, "evidence": evidence})
        if len(EX[kind]) < 8:
            EX[kind].append(F[-1])

    d = bli_dir(args.bli, args.fetch)
    print(f"BLI data: {d}", file=sys.stderr)
    actors, bli_docs, props = load_bli(d)
    eos_docs = load_eos_documents(args.documents)
    by_doc, by_dossier, n_mentions = load_mentions(args.mentions)
    persons = json.load(open(args.persons, encoding="utf-8"))
    CI = CorpusIndex(persons)
    SI = None
    if os.path.exists(args.street):
        SI = StreetIndex(json.load(open(args.street, encoding="utf-8")))

    # ── 1. documents and dossiers ──
    xw, reissued = doc_crosswalk(bli_docs, eos_docs)
    bli_unmatched = [x for x in bli_docs if x not in xw]
    matched_eos = set(xw.values())
    reissued_eos = set(reissued.values())
    eos_new = [x for x in eos_docs if x not in matched_eos]
    S["BLI documents"] = len(bli_docs)
    S["eos documents (street corpus)"] = len(eos_docs)
    S["documents with the same id"] = len(xw) - len(reissued)
    S["documents re-issued under a new id, matched by page images"] = len(reissued)
    S["BLI documents with no counterpart"] = len(bli_unmatched)
    S["eos documents BLI does not have"] = len(eos_new)
    with open(args.docxw, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bli_doc_id", "eos_doc_id", "dossier", "year"])
        for b in sorted(reissued, key=lambda x: (bli_docs[x]["dossier"], x)):
            w.writerow([b, reissued[b], bli_docs[b]["dossier"], bli_docs[b]["y"]])
    n_drift = 0
    for b, e in xw.items():
        if bli_docs[b]["dossier"] != eos_docs[e]["dossier"] or bli_docs[b]["y"] != eos_docs[e]["year"]:
            n_drift += 1
            finding("document_metadata_differs", "bli", 2, eos_docs[e]["dossier"], b, e,
                    f"BLI {bli_docs[b]['dossier']}/{bli_docs[b]['y']} vs corpus "
                    f"{eos_docs[e]['dossier']}/{eos_docs[e]['year']}")
    S["matched documents whose dossier or year differs"] = n_drift
    new_by_street = collections.Counter(eos_docs[x]["dossier"][:9] for x in eos_new)
    for st, c in new_by_street.most_common():
        finding("documents_missing_in_bli", "bli", 1, st, "", f"{c} documents",
                "added to the corpus after the release BLI was built from")
    eos_dossiers = {v["dossier"] for v in eos_docs.values()}
    bli_dossiers = {v["dossier"] for v in bli_docs.values()}
    S["dossiers in the corpus / in BLI documents / BLI map features"] = \
        f"{len(eos_dossiers)} / {len(bli_dossiers)} / {len(props)}"
    S["corpus dossiers without a BLI map feature"] = len(eos_dossiers - set(props))

    # ── 2. place every actor in a dossier ──
    order = sorted(actors, key=num)
    rank = {}
    for v in bli_docs.values():
        rank.setdefault(v["dossier"], len(rank))
    by_rank = sorted(rank, key=rank.get)

    def owner_docs(a):
        out = []
        for ds in (a.get("doc") or {}).values():
            out.extend(as_list(ds))
        return out

    own_dos = {}
    for aid in order:
        ds = {bli_docs[x]["dossier"] for x in owner_docs(actors[aid]) if x in bli_docs}
        if ds:
            own_dos[aid] = ds
    prev_anchor, nxt_anchor = {}, {}
    last = None
    for aid in order:
        if aid in own_dos and len(own_dos[aid]) == 1:
            last = next(iter(own_dos[aid]))
        prev_anchor[aid] = last
    last = None
    for aid in reversed(order):
        if aid in own_dos and len(own_dos[aid]) == 1:
            last = next(iter(own_dos[aid]))
        nxt_anchor[aid] = last

    def candidate_dossiers(aid):
        if aid in own_dos:
            return own_dos[aid], "documents"
        lo, hi = prev_anchor[aid], nxt_anchor[aid]
        if lo and lo == hi:
            return {lo}, "id_block"
        cands = {x for x in (lo, hi) if x}
        if lo and hi:
            a, b = sorted((rank[lo], rank[hi]))
            if b - a <= 12:
                cands |= set(by_rank[a:b + 1])
        return cands, "id_range"

    # ── 3. actors → mentions → persons ──
    cls = collections.Counter(a.get("c") for a in actors.values())
    S["BLI actors"] = len(actors)
    S["  of class per"] = cls["per"]
    rows, claims = [], collections.defaultdict(set)
    link = {}                      # aid → dict
    n_named = n_syn = n_unnamed = 0
    map_status = collections.Counter()
    for aid in order:
        a = actors[aid]
        if a.get("c") != "per":
            continue
        # only actors with name variants are named persons; the rest are
        # placeholders ("widow of …") or unnamed references ("der Schaffner
        # zu Klingental", "Mitverkäufer"), which eos does not list by design
        names = list(a.get("variants") or [])
        if not names:
            if SYNTHETIC.match(a.get("n") or ""):
                n_syn += 1
            else:
                n_unnamed += 1
            continue
        n_named += 1
        keys = {nkey(x) for x in names} | {nkey(a["n"])}
        keys.discard("")
        cands, src = candidate_dossiers(aid)
        odocs = [xw[x] for x in owner_docs(a) if x in xw]
        doc_m = [m for x in odocs for m in by_doc.get(x, []) if m["key"] in keys]
        dos_m = [m for dd in cands for k in keys for m in by_dossier.get(dd, {}).get(k, [])]
        hit_dos = sorted({m["dossier"] for m in dos_m})
        for dd in hit_dos:
            for k in keys:
                if k in by_dossier[dd]:
                    claims[(dd, k)].add(aid)
        level = "doc" if doc_m else ("dossier" if dos_m else "none")
        used = doc_m if doc_m else dos_m
        pc, sc = collections.Counter(), collections.Counter()
        for m in used:
            i, st, _ = CI.resolve(m["dossier"], m["key"], m["year"])
            map_status[st] += 1
            if i is not None:
                pc[i] += 1
            if SI is not None:
                s = SI.resolve(m["dossier"], m["key"], m["year"])
                if s is not None:
                    sc[s] += 1
        link[aid] = {"a": a, "names": names, "keys": keys, "cands": cands, "src": src,
                     "odocs": odocs, "level": level, "used": used, "pc": pc, "sc": sc,
                     "hit_dos": hit_dos}

    S["  named person actors"] = n_named
    S["  placeholder actors (widow of …, heir of …), not linked"] = n_syn
    S["  unnamed references (role or occupation only), not linked"] = n_unnamed
    lv = collections.Counter(v["level"] for v in link.values())
    S["named actors linked through their owner documents"] = lv["doc"]
    S["named actors linked by name inside their dossier"] = lv["dossier"]
    S["named actors without any eos mention"] = lv["none"]
    S["linked mentions → city-wide person"] = dict(map_status)

    # a name key claimed by several actors of one dossier cannot tell them apart
    for aid, L in link.items():
        L["shared"] = L["level"] == "dossier" and any(
            len(claims[(dd, k)]) > 1 for dd in L["hit_dos"] for k in L["keys"])

    # ── 4. findings ──
    # 4a. owner names eos does not have in that document
    n_refs = n_hit = 0
    gap = collections.Counter()
    for aid, L in link.items():
        if not L["odocs"]:
            continue
        for x in L["odocs"]:
            n_refs += 1
            ms = by_doc.get(x, [])
            if any(m["key"] in L["keys"] for m in ms):
                n_hit += 1
                continue
            dd = eos_docs[x]["dossier"]
            elsewhere = any(k in by_dossier.get(dd, {}) for k in L["keys"])
            if elsewhere:
                gap["named elsewhere in the dossier (BLI carried the owner over by coreference)"] += 1
            elif not ms:
                gap["document has no eos person mention at all"] += 1
                finding("owner_document_without_eos_mention", "eos", 2, dd, aid, x,
                        f"BLI owner {L['a']['n']!r}; eos extracted no named person here")
            else:
                re_ = x in reissued_eos
                gap["name absent from the dossier in eos"
                    + (" (document re-issued with corrected text)" if re_ else "")] += 1
                finding("owner_name_not_in_eos", "bli" if re_ else "either", 1, dd, aid, x,
                        f"BLI owner {L['a']['n']!r}; eos names here: "
                        + "; ".join(sorted({m['name'] for m in ms})[:6]))
    S["owner references (actor × document)"] = n_refs
    S["  with the same name among the eos mentions of that document"] = n_hit
    S["  without"] = dict(gap)

    # 4b. one BLI owner actor, judged by the eos mentions of its documents
    P = persons

    def where(L):
        return "|".join(sorted({m["dossier"] for m in L["used"]}))

    n_act = collections.Counter()
    merge_pairs = collections.Counter()
    for aid, L in link.items():
        if L["level"] != "doc":
            continue
        ms = L["used"]
        years = [m["year"] for m in ms if m["year"]]
        idx = sorted(L["pc"], key=lambda i: -L["pc"][i])
        who = " | ".join(f"{pkey(P[i])} ×{L['pc'][i]}" for i in idx)
        both = "both" if len(idx) == 1 else "bli"
        dead_at = min((m["year"] for m in ms if m["dead"] and m["year"]), default=None)
        alive_late = [m["year"] for m in ms
                      if dead_at and not m["dead"] and m["year"] and m["year"] > dead_at + DEAD_GRACE]
        hard = False
        if years and max(years) - min(years) > LIFESPAN:
            hard = True
            n_act["bli_actor_spans_more_than_a_lifespan"] += 1
            finding("bli_actor_spans_more_than_a_lifespan", both, 3, where(L),
                    f"{aid} {L['a']['n']}", who,
                    f"its own owner documents run {min(years)}–{max(years)}")
        elif alive_late:
            hard = True
            n_act["bli_actor_alive_after_death"] += 1
            finding("bli_actor_alive_after_death", both, 3, where(L),
                    f"{aid} {L['a']['n']}", who,
                    f"named as deceased in {dead_at}, as living in {min(alive_late)}")
        if len(idx) < 2 or hard:
            continue
        # names by which each eos person appears in this actor's documents
        groups = collections.defaultdict(set)
        for m in ms:
            i, _, _ = CI.resolve(m["dossier"], m["key"], m["year"])
            if i is not None:
                groups[i].add(m["name"])
        rel = group_relation([sorted(groups[i]) for i in idx])
        kind, side, sev = {
            "spelling": ("eos_split_spelling_variants", "eos", 3),
            "bare_name": ("eos_split_bare_name", "either", 1),
            "given_name_count": ("eos_split_given_name_count", "either", 2),
            "surname_differs": ("merged_despite_different_surname", "either", 2),
            "given_differs": ("merged_despite_different_given_name", "either", 2),
            "different": ("merged_despite_different_names", "bli", 2),
        }[rel]
        n_act[kind] += 1
        if rel == "spelling":
            for i in idx[1:]:
                merge_pairs[tuple(sorted((idx[0], i)))] += 1
        finding(kind, side, sev, where(L), f"{aid} {L['a']['n']}", who,
                f"owner documents {min(years)}–{max(years)}; BLI variants: "
                + "; ".join(L["names"][:8]))
    S["BLI owner actors checked against eos (document level)"] = dict(n_act)
    S["  distinct eos person pairs that one BLI owner unites as spelling variants"] = len(merge_pairs)

    # 4c. one eos person, several BLI owner actors of the same dossier
    per_person = collections.defaultdict(lambda: collections.defaultdict(set))
    for aid, L in link.items():
        if L["level"] != "doc":
            continue
        for m in L["used"]:
            i, _, _ = CI.resolve(m["dossier"], m["key"], m["year"])
            if i is not None:
                per_person[i][m["dossier"]].add(aid)
    certain = collections.defaultdict(dict)        # dossier → actor → (fc, lc)
    for pid, p in props.items():
        for h in p["h"]:
            for a_ in as_list(h.get("p")):
                fc, lc = h.get("fc") or h.get("s"), h.get("lc") or h.get("e")
                if fc is None:
                    continue
                o = certain[pid].get(a_)
                certain[pid][a_] = (min(fc, o[0]), max(lc, o[1])) if o else (fc, lc)
    n_split = collections.Counter()
    for i, dd in per_person.items():
        bare = len(name_tokens(P[i]["n"])) < 2
        for dossier, aids in dd.items():
            if len(aids) < 2:
                continue
            aids = sorted(aids, key=num)
            dy = {x: actors[x].get("d_yr") for x in aids}
            per = {x: certain.get(dossier, {}).get(x) for x in aids}
            dead_conf = [(x, y) for x in aids for y in aids
                         if x != y and dy[x] and per[y] and per[y][0] > dy[x] + DEAD_GRACE]
            ys = [v for v in per.values() if v]
            gap_ = (max(v[0] for v in ys) - min(v[1] for v in ys)) if len(ys) > 1 else 0
            rel = group_relation([link[x]["names"] for x in aids])
            who = " | ".join((f"{x} {actors[x]['n']} {per[x][0]}–{per[x][1]}" if per[x]
                              else f"{x} {actors[x]['n']}") for x in aids)
            tag = " (bare given name)" if bare else ""
            if dead_conf:
                kind, side, sev = "eos_merges_across_a_death", "eos", 3
                ev = "; ".join(f"{actors[x]['n']} dead by {dy[x]}, "
                               f"{actors[y]['n']} owns from {per[y][0]}" for x, y in dead_conf[:3])
            elif gap_ > 40:
                kind, side, sev = "eos_merges_owners_decades_apart", "eos", 3 if bare else 2
                ev = f"{gap_} years between the certain ownership periods"
            elif rel == "spelling":
                kind, side, sev = "bli_split_same_name", "bli", 2
                ev = "same name in the same dossier, periods adjacent or overlapping"
            elif rel == "bare_name":
                kind, side, sev = "bare_name_attached_to_full_name", "either", 1
                ev = "eos attaches the bare name to the one fuller name in the dossier"
            else:
                kind, side, sev = "eos_merges_different_bli_names", "either", 2
                ev = f"name relation between the BLI actors: {rel}"
            n_split[kind] += 1
            finding(kind, side, sev, dossier, who, pkey(P[i]) + tag, ev)
    S["eos person ↔ several BLI owner actors of one dossier"] = dict(n_split)

    # 4d. attributes of 1:1 links
    one = [(aid, next(iter(L["pc"]))) for aid, L in link.items()
           if L["level"] == "doc" and len(L["pc"]) == 1]
    S["actors linked 1:1 at document level"] = len(one)
    n_d = collections.Counter()
    for aid, i in one:
        a, p = actors[aid], P[i]
        if a.get("d_yr") and p.get("dead_year"):
            diff = a["d_yr"] - p["dead_year"]
            n_d["both give a death year"] += 1
            if diff == 0:
                n_d["  identical"] += 1
            elif diff > 0:
                n_d["  eos earlier"] += 1
            else:
                n_d["  BLI earlier"] += 1
            if abs(diff) > LIFESPAN // 2:
                finding("death_year_far_apart", "either", 2,
                        "|".join(sorted({m["dossier"] for m in link[aid]["used"]})),
                        f"{aid} {a['n']} d_yr={a['d_yr']}", f"{pkey(p)} dead_year={p['dead_year']}",
                        f"{abs(diff)} years apart")
        ao = {o.lower() for o in a.get("occ") or []}
        po = {o.lower() for o in p.get("occ") or []}
        if ao and po:
            n_d["both give an occupation"] += 1
            if ao & po:
                n_d["  share one"] += 1
            else:
                n_d["  none in common"] += 1
                if len(link[aid]["used"]) >= 2:
                    finding("occupation_disjoint", "either", 1,
                            "|".join(sorted({m["dossier"] for m in link[aid]["used"]})),
                            f"{aid} {a['n']} occ={sorted(ao)}", f"{pkey(p)} occ={sorted(po)[:6]}",
                            "no normalised occupation in common")
    S["attribute comparison on 1:1 links"] = dict(n_d)

    # 4e. nesting: actor ⊆ street person ⊆ city-wide person
    if SI is not None:
        n_n = collections.Counter()
        for aid, L in link.items():
            if L["level"] != "doc":
                continue
            n_n["owner actor inside one street person" if len(L["sc"]) == 1 else
                "owner actor spanning several street persons" if len(L["sc"]) > 1 else
                "owner actor without street person"] += 1
            n_n["owner actor inside one city-wide person" if len(L["pc"]) == 1 else
                "owner actor spanning several city-wide persons"] += 1
        # street person vs city-wide person, over every eos mention (no BLI needed)
        street_to_city = collections.defaultdict(lambda: collections.defaultdict(set))
        street_pairs = set()
        for dd, keys_ in by_dossier.items():
            for k, ms in keys_.items():
                for m in ms:
                    s_ = SI.resolve(dd, k, m["year"])
                    i, st, _ = CI.resolve(dd, k, m["year"])
                    if s_ is not None and i is not None and st == "unique":
                        street_to_city[s_][i].add(m["name"])
        for s_, cs in street_to_city.items():
            if len(cs) < 2:
                continue
            r = SI.R[s_]
            idx = sorted(cs)
            rel = group_relation([sorted(cs[i]) for i in idx])
            ys = [y for i in idx for y in P[i]["y"]]
            fits = max(ys) - min(ys) <= LIFESPAN
            if rel == "spelling" and fits:
                kind, sev = "eos_city_index_splits_a_street_person", 3
                for x in idx[1:]:
                    street_pairs.add(tuple(sorted((idx[0], x))))
            else:
                kind, sev = "eos_street_and_city_index_disagree", 1
            n_n[kind] += 1
            finding(kind, "eos", sev, r["street_id"], "", f"{r['id']} {r['name']}",
                    f"city-wide ({rel}, {min(ys)}–{max(ys)}): "
                    + " | ".join(pkey(P[i]) for i in idx))
        S["nesting"] = dict(n_n)
        # how far the two independent signals agree, and what merging would do
        in_street = collections.defaultdict(set)      # city person → street persons
        for s_, cs in street_to_city.items():
            for i in cs:
                in_street[i].add(s_)
        both_ = {pr for pr in merge_pairs if in_street[pr[0]] & in_street[pr[1]]}
        uf = {}

        def find(x):
            while uf.setdefault(x, x) != x:
                uf[x] = uf[uf[x]]
                x = uf[x]
            return x
        for a_, b_ in set(merge_pairs) | street_pairs:
            uf[find(a_)] = find(b_)
        comps = collections.Counter(find(x) for x in list(uf))
        S["spelling-variant pairs of city-wide persons"] = {
            "united by a BLI owner actor": len(merge_pairs),
            "united by a street-level person": len(street_pairs),
            "BLI pairs that a street-level person unites as well": len(both_),
            "persons involved": len(uf),
            "persons the index would shrink by if all were merged": len(uf) - len(comps),
        }

    # 4f. eos-internal consistency the join brought up
    c_sum = sum(p.get("c", 0) for p in persons)
    S["eos: Σ mentions over persons vs rows in persons.csv"] = f"{c_sum} vs {n_mentions}"
    trunc = [p for p in persons if p.get("d", 0) > len({e[0] if isinstance(e, list) else e
                                                         for e in p.get("dos", [])})]
    S["eos: persons whose dossier list is shorter than their dossier count"] = len(trunc)
    n_long = 0
    for i, p in enumerate(persons):
        y = p.get("y") or [0, 0]
        if y[1] - y[0] <= LIFESPAN:
            continue
        n_long += 1
        acts = {x for dd in per_person.get(i, {}).values() for x in dd}
        hls = p.get("hls") or {}
        wd = p.get("wd") or {}
        finding("eos_person_spans_more_than_a_lifespan", "eos", 3, "", 
                f"{len(acts)} BLI owner actors in {len(per_person.get(i, {}))} dossiers",
                pkey(p),
                f"{y[1] - y[0]} years, {p.get('c')} mentions; HLS: {hls.get('t', '–')} "
                f"({wd.get('b', '?')}–{wd.get('d', '?')})")
    S["eos: persons whose mentions span more than 80 years"] = n_long
    amb = collections.defaultdict(set)
    for (dossier, key, year), (i, st, cands) in CI.cache.items():
        if st == "ambiguous":
            amb[tuple(sorted(cands))].add(dossier)
    for cands, ds in amb.items():
        rel = group_relation([[P[i]["n"]] for i in cands])
        finding("eos_same_name_same_dossier_two_persons", "eos", 3 if rel == "spelling" else 2,
                "|".join(sorted(ds)[:4]), "", " | ".join(pkey(P[i]) for i in cands),
                f"both carry the same name variant in the dossier in the same years ({rel})")
    S["eos: person groups sharing a name variant in one dossier at the same time"] = len(amb)

    # 4g. BLI-internal oddities (reported, never changed here)
    b = collections.Counter()
    for aid, a in actors.items():
        n = a.get("n") or ""
        if n.lower().startswith(("none of ", "null of ")):
            b["placeholder actors named 'None of …' (unlabelled relation)"] += 1
        if len({x[:9] for x in own_dos.get(aid, ())}) > 1:
            b["owner actors with documents on more than one street"] += 1
            finding("bli_actor_on_several_streets", "bli", 1, "|".join(sorted(own_dos[aid])),
                    f"{aid} {n}", "", "identity is meant to be property/neighbour level")
        if "null" in (a.get("rel") or {}):
            b["actors with a relation of type 'null'"] += 1
    in_h = {x for p in props.values() for h in p["h"] for x in as_list(h.get("p"))}
    b["owner actors (with documents) missing from every ownership history"] = \
        sum(1 for x in own_dos if x not in in_h)
    b["owner actors of a class other than per/org"] = dict(collections.Counter(
        actors[x]["c"] for x in own_dos if actors[x]["c"] not in ("per", "org")))
    # 'Ghost Record' = a map feature without address, documents or owners
    ghosts = [pid for pid, p in props.items() if p.get("adrs") == "Ghost Record"]
    g_in = [pid for pid in ghosts if pid in eos_dossiers]
    b["map features shown as 'Ghost Record' (no address, documents or owners)"] = len(ghosts)
    b["  of which are corpus dossiers with documents"] = \
        f"{len(g_in)} dossiers, {sum(1 for v in eos_docs.values() if v['dossier'] in set(g_in))} documents"
    for dd in sorted(eos_dossiers - set(props)):
        nd = sum(1 for v in eos_docs.values() if v["dossier"] == dd)
        finding("dossier_missing_on_bli_map", "bli", 2 if dd in bli_dossiers else 1, dd, "",
                f"{nd} documents", "in BLI's documents but without a map feature"
                if dd in bli_dossiers else "not in the release BLI was built from")
    S["BLI-internal"] = dict(b)

    # ── 5. write ──
    cols = ["actor_id", "name", "n_variants", "dossiers", "dossier_source", "n_owner_docs",
            "link_level", "n_mentions", "shared_name_in_dossier", "n_persons", "persons",
            "n_street_persons", "street_persons", "bli_death_year", "bli_occ"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for aid in order:
            L = link.get(aid)
            if not L:
                continue
            a = L["a"]
            ds = L["hit_dos"] or sorted(L["cands"]) if L["src"] != "id_range" or L["hit_dos"] else []
            w.writerow({
                "actor_id": aid, "name": a.get("n"), "n_variants": len(L["names"]),
                "dossiers": "|".join(ds), "dossier_source": L["src"],
                "n_owner_docs": len(L["odocs"]), "link_level": L["level"],
                "n_mentions": len(L["used"]), "shared_name_in_dossier": int(L["shared"]),
                "n_persons": len(L["pc"]),
                "persons": " | ".join(pkey(P[i]) for i in sorted(L["pc"], key=lambda i: -L["pc"][i])),
                "n_street_persons": len(L["sc"]),
                "street_persons": "|".join(SI.R[s]["id"] for s in sorted(L["sc"], key=lambda s: -L["sc"][s])) if SI else "",
                "bli_death_year": a.get("d_yr") or "",
                "bli_occ": "|".join(a.get("occ") or []),
            })

    F.sort(key=lambda r: (-r["severity"], r["type"], r["dossier"]))
    with open(args.findings, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["type", "likely_side", "severity", "dossier",
                                          "bli", "eos", "evidence"])
        w.writeheader()
        w.writerows(F)

    write_report(args.report, S, F, EX)
    kinds = collections.Counter(r["type"] for r in F)
    print(f"→ {args.out}: {len(link)} named person actors "
          f"({lv['doc']} doc-level, {lv['dossier']} dossier-level, {lv['none']} unlinked)",
          file=sys.stderr)
    print(f"→ {args.findings}: {len(F)} findings", file=sys.stderr)
    for k, c in kinds.most_common():
        print(f"    {c:6d}  {k}", file=sys.stderr)
    return S, F


DESCR = {
    "eos_split_spelling_variants":
        "One BLI owner (same property, same years) is two or more eos persons whose names "
        "differ only in spelling or HTR noise. eos kept them apart because its dedupe needs "
        "the same canonical given names and a phonetically equal surname.",
    "eos_city_index_splits_a_street_person":
        "The street-level index holds these as one person; the city-wide index as several, "
        "although the names are spelling variants and all mentions fit one lifespan.",
    "eos_same_name_same_dossier_two_persons":
        "Two eos persons carry the very same name variant in the same dossier in the same years.",
    "eos_person_spans_more_than_a_lifespan":
        "An eos person whose mentions run over more than 80 years. All are HLS-linked: "
        "dedupe_persons.py merges every same-named entry whose span overlaps the Wikidata "
        "life envelope, however far that entry reaches beyond it.",
    "eos_merges_across_a_death":
        "eos has one person where BLI has an owner recorded as dead and, more than 15 years "
        "later, another owner of the same name on the same property.",
    "eos_merges_owners_decades_apart":
        "One eos person, but BLI's owners of that name on the property are more than 40 years "
        "apart. Typical for bare given names (Elsin, Ennelin), which eos merges inside a dossier.",
    "bli_actor_spans_more_than_a_lifespan":
        "The documents in which one BLI actor is owner run over more than 80 years.",
    "bli_actor_alive_after_death":
        "One BLI actor is named as deceased and, more than 15 years later, as living.",
    "merged_despite_different_given_name":
        "BLI unites eos persons with the same surname but different given names. Often HTR "
        "noise (Heyni/Heym, Ulrich/Uly), sometimes two relatives.",
    "merged_despite_different_surname":
        "BLI unites eos persons with the same given name but dissimilar surnames: HTR noise, "
        "an alias or house name — or a wrong merge.",
    "merged_despite_different_names":
        "BLI unites eos persons whose names have nothing in common (alias, byname, coreference "
        "error).",
    "eos_split_given_name_count":
        "BLI unites eos persons that differ by one given name (Hans / Hans Heinrich). eos keeps "
        "these apart on purpose; on one property in the same years they are often one man.",
    "eos_split_bare_name":
        "BLI unites a bare name with a fuller one that eos lists separately.",
    "bli_split_same_name":
        "eos has one person; BLI has several owner actors with the same name on the property, "
        "with adjacent or overlapping periods.",
    "bare_name_attached_to_full_name":
        "eos attached a bare name to the only fuller name in the dossier; BLI keeps them apart.",
    "eos_merges_different_bli_names":
        "eos has one person where BLI has differently named owners.",
    "eos_street_and_city_index_disagree":
        "Street-level and city-wide index cut these mentions differently, without a clear "
        "spelling relation or within one lifespan.",
    "death_year_far_apart":
        "Linked 1:1, but the first 'deceased' mention differs by more than 40 years.",
    "occupation_disjoint":
        "Linked 1:1 on at least two mentions, but no normalised occupation in common.",
    "owner_document_without_eos_mention":
        "BLI names an owner in a document where eos extracted no named person.",
    "owner_name_not_in_eos":
        "BLI names an owner whose name eos has nowhere in the dossier.",
    "documents_missing_in_bli":
        "Documents the corpus added after the release BLI was built from, per street.",
    "document_metadata_differs":
        "Same register card, different dossier or year in the two releases.",
    "dossier_missing_on_bli_map":
        "A dossier with documents in the corpus but no feature on the BLI map.",
    "bli_actor_on_several_streets":
        "A BLI owner actor with documents on more than one street.",
}


def write_report(path, S, F, EX):
    kinds = collections.Counter(r["type"] for r in F)
    side = {r["type"]: r["likely_side"] for r in F}
    sev = {}
    for r in F:
        sev[r["type"]] = max(sev.get(r["type"], 0), r["severity"])
    L = ["# BLI ↔ eos person lists: join and discrepancy report", "",
         "Generated by `link_bli_hgb.py`; do not edit by hand. BLI = *Basler Liegenschaften "
         "1400–1700 Interaktiv* (DHBern/basler-liegenschaften-interaktiv), read-only.", "",
         "## Numbers", ""]
    for k, v in S.items():
        if isinstance(v, dict):
            L.append(f"- {k.strip()}:")
            for kk, vv in v.items():
                L.append(f"    - {str(kk).strip()}: {vv}")
        else:
            L.append(f"{'    ' if k.startswith('  ') else ''}- {k.strip()}: {v}")
    L += ["", "## Findings by type", "",
          "| type | likely side | highest severity | count |", "|---|---|---|---|"]
    for k, c in sorted(kinds.items(), key=lambda kv: (-sev[kv[0]], -kv[1])):
        L.append(f"| `{k}` | {side[k]} | {sev[k]} | {c} |")
    L += ["", "Severity 3 = the two resolutions contradict each other on hard evidence "
          "(a death, a lifespan, an exact spelling relation); 2 = structural disagreement "
          "worth a look; 1 = context. `likely side` names where the error most probably "
          "sits, not a verdict.", "", "## Examples", ""]
    for k in sorted(EX, key=lambda k: (-sev[k], -kinds[k])):
        L += [f"### `{k}` ({kinds[k]})", "", DESCR.get(k, ""), ""]
        for r in EX[k][:6]:
            L.append(f"- **{r['dossier']}** — BLI: {r['bli'] or '–'} — eos: {r['eos'] or '–'} — {r['evidence']}")
        L.append("")
    open(path, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    main()
