"""
build_data.py
Generates two JSON files for the GitHub Pages site:
  - persons_resolved.json  (approach 4: dossier-scoped identity resolution)
  - guild_data.json        (approach 5: guild/occupation trajectory)
"""

import pandas as pd
import re
import json
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache

from lifedates import PAST_ROLES, STRONG_ROLES

# ── Config ─────────────────────────────────────────────────────────────────────
INPUT_CSV   = "persons.csv"
OUT_PERSONS = "persons_resolved.json"
OUT_GUILD   = "guild_data.json"

# ── Basel guild mapping (historical Zünfte, ca. 1400-1700) ────────────────────
GUILD_MAP = {
    # Rebleute / Weinleute
    "rebmann": "Rebleute", "weinmann": "Rebleute", "küfer": "Rebleute",
    "büttner": "Rebleute", "weinschenk": "Rebleute",
    "wirt": "Weinleute", "tavernenwirt": "Weinleute",
    # Safran (merchants & traders)
    "handelsmann": "Safran", "krämer": "Safran", "gremper": "Safran",
    "apotheker": "Safran", "goldschmied": "Safran", "juwelier": "Safran",
    "wechsler": "Safran", "seidenhändler": "Safran", "tuchhändler": "Safran",
    "silberschmied": "Safran", "pfisterer": "Safran",
    # Metzger
    "metzger": "Metzger", "fleischhauer": "Metzger", "schlächter": "Metzger",
    # Brotbäcker
    "brotbäcker": "Brotbäcker", "müller": "Brotbäcker",
    "mehlhändler": "Brotbäcker", "kornmesser": "Brotbäcker",
    # Schuhmacher
    "schuhmacher": "Schuhmacher", "gerber": "Schuhmacher",
    "kürschner": "Schuhmacher", "sattler": "Schuhmacher",
    "riemer": "Schuhmacher", "schuster": "Schuhmacher",
    "weißgerber": "Schuhmacher", "rotgerber": "Schuhmacher",
    # Schneider
    "schneider": "Schneider",
    # Schmied
    "schmied": "Schmied", "messerschmied": "Schmied", "schlosser": "Schmied",
    "nagelschmied": "Schmied", "wagner": "Schmied", "hufschmied": "Schmied",
    "zinngießer": "Schmied", "glockengießer": "Schmied", "sporer": "Schmied",
    "büchsenschmied": "Schmied", "plattner": "Schmied",
    # Weber / Spinnwettern
    "weber": "Weber", "wollweber": "Weber", "leinenweber": "Weber",
    "scherer": "Weber", "tuchmacher": "Weber", "wollschläger": "Weber",
    # Hausleute (Zimmermann etc.)
    "zimmermann": "Hausleute", "maurer": "Hausleute", "steinmetz": "Hausleute",
    "dachdecker": "Hausleute", "tischmacher": "Hausleute", "schreiner": "Hausleute",
    "glaser": "Hausleute", "hafner": "Hausleute", "ziegler": "Hausleute",
    "seiler": "Hausleute", "korbmacher": "Hausleute",
    # Fischer
    "fischer": "Fischer",
    # Schiffleutezunft
    "schiffmann": "Schiffleutezunft", "fährmann": "Schiffleutezunft",
    "flößer": "Schiffleutezunft", "schiffer": "Schiffleutezunft",
    # Diverse Handwerke (unguilded or smaller guilds)
    "hutmacher": "Handwerke", "bader": "Handwerke", "barbier": "Handwerke",
    "maler": "Handwerke", "buchdrucker": "Handwerke", "buchbinder": "Handwerke",
    "spengler": "Handwerke", "drechsler": "Handwerke", "böttcher": "Handwerke",
    "kessler": "Handwerke", "locher": "Handwerke", "vogler": "Handwerke",
    "karrer": "Handwerke", "säger": "Handwerke", "amtmann": "Handwerke",
    # Klerus / Freie Berufe
    "kaplan": "Klerus & Freie Berufe", "pfarrer": "Klerus & Freie Berufe",
    "priester": "Klerus & Freie Berufe", "arzt": "Klerus & Freie Berufe",
    "doktor": "Klerus & Freie Berufe", "notar": "Klerus & Freie Berufe",
    "leutpriester": "Klerus & Freie Berufe",
    # Verwaltung
    "schaffner": "Verwaltung", "zinsmeister": "Verwaltung",
    "hauptmann": "Verwaltung", "vogt": "Verwaltung",
    "kornschreiber": "Verwaltung", "schreiber": "Verwaltung",
    "hausfeurer": "Verwaltung", "spitalmeister": "Verwaltung",
    "lohnherr": "Verwaltung", "stadtknecht": "Verwaltung",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

ABBREVS = {
    "hs": "hans", "grg": "georg", "jac": "jacob", "joh": "johannes",
    "heint": "heinrich", "heinr": "heinrich", "conr": "konrad",
    "pet": "peter", "anth": "anthoni", "kath": "katharina",
    "barb": "barbara", "marg": "margaretha", "ursl": "ursula",
    "eliz": "elizabetha", "mich": "michael", "nie": "nikolaus",
    "nic": "nikolaus", "balt": "balthasar", "ulr": "ulrich",
    "ruod": "rudolf", "ruodolff": "rudolf", "rudolff": "rudolf",
    "clas": "nikolaus", "claus": "nikolaus",
}


def clean_tokens(name: str) -> list[str]:
    """Lowercase, remove punctuation, split, drop single chars and 'unk'."""
    toks = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return [t for t in toks if len(t) > 1 and t != "unk"]


def expand(tok: str) -> str:
    t = tok.rstrip(".")
    return ABBREVS.get(t, t)


def canonical_key(name: str) -> str:
    """Stable sort key for cross-dossier matching.
    Each token is normalized via abbreviation expansion; the key is sorted
    so 'Hans Müller' and 'Müller Hans' produce the same key.
    Fuzzy spelling variants (e.g. 'Gisler'/'Gysler') are handled at the
    within-dossier step; cross-dossier uses the exact expanded key to avoid
    over-merging unrelated persons with similar names.
    """
    return " ".join(sorted(expand(t) for t in clean_tokens(name)))


def token_sim(t1: str, t2: str) -> bool:
    """Fast fuzzy similarity: same 2-char prefix + SequenceMatcher ≥ 0.82.
    The prefix guard avoids SequenceMatcher on clearly different tokens.
    """
    if t1 == t2:
        return True
    if t1[0] != t2[0]:             # quick rejection: must share first character
        return False
    if abs(len(t1) - len(t2)) > 3: # length difference guard
        return False
    return SequenceMatcher(None, t1, t2).ratio() >= 0.82


@lru_cache(maxsize=None)
def _expanded(name: str) -> tuple:
    return tuple(expand(t) for t in clean_tokens(name))


def tokens_subset(a: str, b: str) -> bool:
    """True if every expanded token of a has a fuzzy match in expanded tokens of b."""
    ta, tb = _expanded(a), _expanded(b)
    return len(ta) >= 1 and all(any(token_sim(t, p) for p in tb) for t in ta)


# ── Time: who can be one person ───────────────────────────────────────────────
LIFESPAN = 80     # mentions of one person span at most this many years
# A bare given name ("Elsin", "Ennelin") says little. Measured against the owner
# actors of Basler Liegenschaften Interaktiv, which resolves such names through
# husbands and heirs: two consecutive mentions of the same bare name in one
# dossier are the same owner in 86 % of cases when 0–4 years apart, 65 % at
# 10–14, 46 % at 15–19, 21 % at 30–34 and never from 50 years on. From 15 years
# of silence on a new person is the better guess. Full names stay one owner
# (97 % or more) up to 40 years of silence, so they only obey the lifespan.
BARE_GAP = 15


def time_runs(rows, cap=LIFESPAN, gap=None, year=lambda r: r["year"]):
    """Cut rows (any order) into chronological runs that can be one person.

    A new run starts when a mention lies more than `cap` years after the run's
    first, or — if `gap` is given — `gap` or more years after the previous one.
    Undated rows (year 0/None) form a run of their own.

    This replaces fixed bins (year // 80), which tore a person apart at 1440,
    1520, 1600 and 1680 and kept two namesakes 79 years apart together.
    """
    dated = sorted((r for r in rows if year(r)), key=year)
    runs = [[r for r in rows if not year(r)]] if any(not year(r) for r in rows) else []
    cur, start, prev = [], None, None
    for r in dated:
        y = year(r)
        if cur and (y - start > cap or (gap is not None and y - prev >= gap)):
            runs.append(cur)
            cur = []
        if not cur:
            start = y
        cur.append(r)
        prev = y
    if cur:
        runs.append(cur)
    return runs


def person_runs(rows, year=lambda r: r["year"], name=lambda r: r["name"]):
    """Cut the mentions of one merged name of a dossier into persons in time.

    Mentions under a full name (two tokens or more) form runs of at most one
    lifespan. A mention under a bare given name — the cluster's own name, or
    one attached to the single fuller name of the dossier ('Anna' to 'Clor
    Anna') — only belongs to a run if it lies less than BARE_GAP years from one
    of that run's full-name mentions and keeps the run within a lifespan;
    otherwise the bare mentions form runs of their own, cut at every silence of
    BARE_GAP years.
    """
    def bare(r):
        return len(canonical_key(name(r)).split()) < 2
    full = [r for r in rows if not bare(r)]
    loose = [r for r in rows if bare(r)]
    if not full:
        return time_runs(loose, LIFESPAN, BARE_GAP, year)
    runs = time_runs(full, LIFESPAN, None, year)
    if not loose:
        return runs
    anchors = [[year(x) for x in run if year(x)] for run in runs]
    span = [[min(a), max(a)] if a else None for a in anchors]
    rest = []
    for r in sorted(loose, key=lambda r: year(r) or 0):
        y, best = year(r), None
        if y:
            for k, a in enumerate(anchors):
                if not a:
                    continue
                dist = min(abs(y - v) for v in a)
                if dist < BARE_GAP and max(span[k][1], y) - min(span[k][0], y) <= LIFESPAN \
                        and (best is None or dist < best[0]):
                    best = (dist, k)
        if best is None:
            rest.append(r)
        else:
            k = best[1]
            runs[k].append(r)
            span[k] = [min(span[k][0], y), max(span[k][1], y)]
    return runs + time_runs(rest, LIFESPAN, BARE_GAP, year)


def death_split(rows, year=lambda r: r["year"], dead=lambda r: r["dead"]):
    """Split a run where living mentions follow the first 'deceased' mention.

    Returns [rows] or [early, late]: `late` holds the living mentions after the
    earliest deceased one — a later bearer of the name; every deceased mention
    stays with `early`. Each row lands in exactly one part.
    """
    dead_years = [year(r) for r in rows if dead(r) and year(r)]
    if not dead_years:
        return [rows]
    d = min(dead_years)
    late = [r for r in rows if not dead(r) and year(r) and year(r) > d]
    if not late:
        return [rows]
    late_ids = {id(r) for r in late}
    return [[r for r in rows if id(r) not in late_ids], late]


# ── Union-Find ────────────────────────────────────────────────────────────────
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        if self.p[x] != x:
            self.p[x] = self.find(self.p[x])
        return self.p[x]

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


# ═══════════════════════════════════════════════════════════════════════════════
# APPROACH 4 — Dossier-scoped identity resolution
# ═══════════════════════════════════════════════════════════════════════════════

def build_persons_resolved(df: pd.DataFrame) -> list[dict]:
    print("Approach 4: dossier-scoped disambiguation …")

    uf = UF()

    # Step 1: within each dossier, merge names where one is an unambiguous token-subset
    # Guards: (a) exactly one superset in the dossier, (b) year ranges within 80 years
    for dossier, grp in df.groupby("dossierid"):
        # Build name → year-range map for this dossier
        name_years: dict[str, list[int]] = {}
        for nm, yr in zip(grp["name"], grp["year"]):
            if pd.notna(nm) and pd.notna(yr):
                name_years.setdefault(nm, []).append(int(yr))

        names = [n for n in grp["name"].dropna().unique()]
        names.sort(key=lambda n: -len(clean_tokens(n)))
        for a in names:
            supersets = [b for b in names if b != a and tokens_subset(a, b)]
            if len(supersets) == 1:
                b = supersets[0]
                # Also enforce 80-year cap within a dossier
                ay = name_years.get(a, [])
                by = name_years.get(b, [])
                all_y = ay + by
                if all_y and max(all_y) - min(all_y) > LIFESPAN:
                    continue
                uf.union((dossier, a), (dossier, b))

    # Step 2: collect the mentions of each merged name per dossier
    by_root: dict[tuple, list[dict]] = defaultdict(list)
    for r in prepare_rows(df):
        by_root[uf.find((r["dossierid"], r["name"]))].append(r)

    # Steps 2b/3b: cut each cluster into runs that can be one person — one
    # lifespan; a bare given name only near the fuller name it is attached to,
    # or without a generation of silence (person_runs) — and split a run where
    # living mentions follow the first deceased one. Every mention ends up in
    # exactly one entry.
    per_dossier: list[dict] = []
    for root, rows in by_root.items():
        for run in person_runs(rows, year=lambda r: r["_year"]):
            for part in death_split(run, year=lambda r: r["_year"],
                                    dead=lambda r: r["_dead"]):
                per_dossier.append(summarise(root, part))

    # Sort per_dossier chronologically so that deceased entries (which mark the
    # death year upper bound) are always processed AFTER earlier live entries.
    # This makes the cross-dossier constraint order-independent.
    per_dossier.sort(key=lambda p: (p["years"][0], p["dead_year"] or 9999))

    # Step 4: cross-dossier grouping by canonical key
    # Only merge across dossiers when the canonical name has ≥2 tokens
    # (single first-names like "Hans" or "Anna" are too ambiguous to link globally)
    cross: dict[str, list[dict]] = defaultdict(list)
    _uid = 0
    for p in per_dossier:
        key_tokens = p["ckey"].split()
        if len(key_tokens) >= 2:
            existing = cross[p["ckey"]]
            if existing:
                # Guard 1 — 80-year lifespan cap
                all_years = [y for e in existing for y in e["years"] if y > 0] + \
                            [y for y in p["years"] if y > 0]
                if all_years and max(all_years) - min(all_years) > 80:
                    cross[f"__time_{_uid}"].append(p)
                    _uid += 1
                    continue

                # Guard 2 — deceased constraint
                # cluster's earliest deceased mention = death_year_ub for that person
                cluster_dead = min(
                    (e["dead_year"] for e in existing if e["dead_year"] is not None),
                    default=None
                )
                # new entry's earliest deceased mention
                p_dead = p["dead_year"]

                # If the cluster already has someone marked dead, no live mention
                # from after that year can belong to the same person.
                if cluster_dead and p["live_years"]:
                    if any(y > cluster_dead for y in p["live_years"]):
                        cross[f"__dead_{_uid}"].append(p)
                        _uid += 1
                        continue

                # Symmetrically: if this entry marks the person dead, the cluster
                # must not contain live mentions from after that death year.
                if p_dead:
                    cluster_live = [y for e in existing for y in e["live_years"]]
                    if any(y > p_dead for y in cluster_live):
                        cross[f"__dead_{_uid}"].append(p)
                        _uid += 1
                        continue

            cross[p["ckey"]].append(p)
        else:
            # keep as isolated entry with a unique key
            cross[f"__single_{_uid}"].append(p)
            _uid += 1

    # Step 5: build final person entities
    persons = [assemble(entries) for entries in cross.values()]
    persons.sort(key=lambda p: -p["c"])
    print(f"  → {len(persons):,} resolved persons from {len(df):,} mentions")
    return persons


# ── from mentions to a person ────────────────────────────────────────────────
#
# A person is assembled from *entries*: the mentions one name has in one
# dossier within one run (`summarise`). `assemble` adds the entries up. Both are
# module-level because a person can be taken apart again: when an HLS link shows
# that part of the mentions lie outside the life of the person linked
# (lifedates.partition), apply_hls_links.py re-summarises the two halves from
# the mentions. For that every person carries `_rows` — per entry the dossier
# root and the row numbers of its mentions in persons.csv — which main() moves
# into the sidecar file persons_rows.json before the index is written.

def prepare_rows(df):
    """The mentions of persons.csv as dicts with the flags the resolution and
    the life check read: _i (row number), _year, _dead (marked "selig"),
    _strong (a party to the transaction, see lifedates.STRONG_ROLES, and not
    marked deceased) and _past (named in a role of the past, PAST_ROLES)."""
    rows = df.to_dict("records")
    for i, r in enumerate(rows):
        r["_i"] = i
        r["_year"] = int(r["year"]) if pd.notna(r.get("year")) else 0
        v = r.get("is_deceased")
        r["_dead"] = v == 1 or v == 1.0 or str(v) == "1.0"
        roles = r.get("roles")
        roles = set(roles.split("|")) if isinstance(roles, str) else set()
        r["_strong"] = not r["_dead"] and not STRONG_ROLES.isdisjoint(roles)
        r["_past"] = not PAST_ROLES.isdisjoint(roles)
    return rows


def pick_canonical(names: list[str]) -> str:
    """The fullest name: most tokens, fewest abbreviations."""
    def score(n):
        toks = clean_tokens(n)
        abbr = sum(1 for t in toks if t.endswith(".") or len(t) <= 2)
        return (len(toks) - abbr, len(n))
    return max(names, key=score)


def collect(rows, col, drop=()):
    out = set()
    for r in rows:
        if isinstance(r.get(col), str):
            for x in r[col].split("|"):
                x = x.strip()
                if x and x not in drop:
                    out.add(x)
    return sorted(out)


def summarise(root, rows):
    """One entry: the mentions of one (dossier, merged name) in one run."""
    names = sorted({r["name"] for r in rows})
    canon = pick_canonical(names)
    years = [r["_year"] for r in rows if r["_year"]]
    dead_years = [r["_year"] for r in rows if r["_year"] and r["_dead"]]
    act_years = [r["_year"] for r in rows if r["_year"] and r["_strong"]]
    return {
        "canonical": canon,
        "variants": names,
        "dossier": root,              # (dossier id, merged name)
        "mentions": len(rows),
        "years": [min(years), max(years)] if years else [0, 0],
        "occ": collect(rows, "occupation_norm", drop=("unk",)),
        "title": collect(rows, "title"),
        "fam": collect(rows, "family_relation"),
        "loc": collect(rows, "location"),
        "org": collect(rows, "org_affiliation"),
        # earliest year a deceased marker appears = upper bound on death year
        "dead_year": min(dead_years) if dead_years else None,
        "live_years": [r["_year"] for r in rows if r["_year"] and not r["_dead"]],
        # first and last year as a party to a transaction
        "act": [min(act_years), max(act_years)] if act_years else None,
        # last year named as living: not "selig", not in a role of the past
        "last_live": max((r["_year"] for r in rows
                          if r["_year"] and not r["_dead"] and not r["_past"]), default=None),
        "ckey": canonical_key(canon),
        "rows": [r["_i"] for r in rows],
    }


def assemble(entries):
    """One person from its entries."""
    dossiers = sorted({e["dossier"] for e in entries})
    all_years = [y for e in entries for y in e["years"] if y > 0]
    dead_years_all = [e["dead_year"] for e in entries if e["dead_year"] is not None]
    acts = [y for e in entries if e["act"] for y in e["act"]]
    person = {
        "n": pick_canonical([e["canonical"] for e in entries]),
        "v": sorted({n for e in entries for n in e["variants"]}),
        "c": sum(e["mentions"] for e in entries),
        "d": len({d[0] for d in dossiers}),   # distinct dossier ids
        "y": [min(all_years), max(all_years)] if all_years else [0, 0],
        "dead_year": min(dead_years_all) if dead_years_all else None,  # earliest "deceased"
        "occ": sorted({o for e in entries for o in e["occ"]}),
        "tit": sorted({t for e in entries for t in e["title"]}),
        "fam": sorted({f for e in entries for f in e["fam"]}),
        "loc": sorted({l for e in entries for l in e["loc"]}),
        "org": sorted({o for e in entries for o in e["org"]}),
        "dos": dossiers,                      # every (dossier, name) pair
    }
    if acts:
        person["a"] = [min(acts), max(acts)]  # first and last year as a party
    # last year named as living, where that is not the last mention (0: never —
    # the later mentions call the person deceased or name a role of the past)
    last_live = max((e["last_live"] for e in entries if e["last_live"]), default=0)
    if last_live != person["y"][1]:
        person["ly"] = last_live
    person["_rows"] = [[list(e["dossier"]), e["rows"]] for e in entries]
    return person


def split_person(person_rows, rows, label):
    """Take a person apart by its mentions.

    `person_rows` is the person's `_rows` (entries of [root, row numbers]),
    `rows` the prepared mentions by row number, `label(row)` names the part a
    mention belongs to. Returns {part: person}; every entry is cut along the
    parts, so each mention lands in exactly one person.
    """
    parts = defaultdict(list)
    for root, idx in person_rows:
        cut = defaultdict(list)
        for i in idx:
            cut[label(rows[i])].append(rows[i])
        for part, rs in cut.items():
            parts[part].append(summarise(tuple(root), rs))
    return {part: assemble(entries) for part, entries in parts.items()}


OUT_ROWS = "persons_rows.json"


def pkey(p):
    y = p.get("y") or [0, 0]
    return f"{p['n']}#{y[0]}-{y[1]}#{p.get('c', 0)}"


def write_index(persons, path=OUT_PERSONS, rows_path=OUT_ROWS):
    """Write the index and, beside it, the sidecar with every person's mentions
    (`_rows` is taken out of the index: it is working data, not site data)."""
    side = {"keys": [pkey(p) for p in persons],
            "rows": [p.pop("_rows") for p in persons]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(persons, f, ensure_ascii=False, separators=(",", ":"))
    with open(rows_path, "w", encoding="utf-8") as f:
        json.dump(side, f, separators=(",", ":"))


def read_rows(persons, rows_path=OUT_ROWS):
    """The sidecar's mention lists if it belongs to this state of the index,
    else None (after the dedupe passes it no longer does)."""
    try:
        side = json.load(open(rows_path, encoding="utf-8"))
    except FileNotFoundError:
        return None
    if side["keys"] != [pkey(p) for p in persons]:
        return None
    return side["rows"]


# ═══════════════════════════════════════════════════════════════════════════════
# APPROACH 5 — Guild trajectory over time
# ═══════════════════════════════════════════════════════════════════════════════

def build_guild_data(df: pd.DataFrame) -> dict:
    print("Approach 5: guild trajectory …")

    rows = []
    for _, r in df.iterrows():
        if not isinstance(r.get("occupation_norm"), str):
            continue
        year = r.get("year")
        if not year or pd.isna(year):
            continue
        year = int(year)
        decade = (year // 10) * 10
        for occ in r["occupation_norm"].split("|"):
            occ = occ.strip()
            if not occ or occ == "unk":
                continue
            guild = GUILD_MAP.get(occ)
            rows.append({"decade": decade, "occ": occ, "guild": guild or "Sonstige"})

    occ_df = pd.DataFrame(rows)
    decades = sorted(occ_df["decade"].unique().tolist())

    # Guild trajectory (per decade)
    guild_counts = occ_df.groupby(["decade", "guild"]).size().unstack(fill_value=0)
    all_guilds = sorted(guild_counts.columns.tolist())
    guild_trajectory = {
        "decades": decades,
        "guilds": all_guilds,
        "series": {
            guild: [int(guild_counts.loc[d, guild]) if d in guild_counts.index else 0
                    for d in decades]
            for guild in all_guilds
        },
    }

    # Occupation frequency table (top 80)
    occ_freq = occ_df["occ"].value_counts().head(80)
    occ_table = [
        {"occ": occ, "count": int(cnt), "guild": GUILD_MAP.get(occ, "Sonstige")}
        for occ, cnt in occ_freq.items()
    ]

    # Occupation × decade heatmap data (top 30 occs)
    top30 = occ_freq.head(30).index.tolist()
    hm_df = occ_df[occ_df["occ"].isin(top30)].groupby(["decade", "occ"]).size().unstack(fill_value=0)
    heatmap = {
        "decades": decades,
        "occs": top30,
        "values": {
            occ: [int(hm_df.loc[d, occ]) if d in hm_df.index and occ in hm_df.columns else 0
                  for d in decades]
            for occ in top30
        },
    }

    print(f"  → {len(all_guilds)} guilds, {len(decades)} decades, {len(occ_table)} top occupations")
    return {"trajectory": guild_trajectory, "occ_table": occ_table, "heatmap": heatmap}


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Reading {INPUT_CSV} …")
    df = pd.read_csv(INPUT_CSV)

    persons = build_persons_resolved(df)
    write_index(persons)
    print(f"Saved {OUT_PERSONS} ({len(persons):,} persons, "
          f"{len(json.dumps(persons, ensure_ascii=False).encode())/1e6:.1f} MB)")

    guild = build_guild_data(df)
    with open(OUT_GUILD, "w", encoding="utf-8") as f:
        json.dump(guild, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Saved {OUT_GUILD}")
