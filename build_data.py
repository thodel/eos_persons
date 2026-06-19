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


def tokens_subset(a: str, b: str) -> bool:
    """True if every expanded token of a has a fuzzy match in expanded tokens of b."""
    ta = [expand(t) for t in clean_tokens(a)]
    tb = [expand(t) for t in clean_tokens(b)]
    return len(ta) >= 1 and all(any(token_sim(t, p) for p in tb) for t in ta)


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
        for _, row in grp.iterrows():
            nm = row.get("name")
            yr = row.get("year")
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
                if all_y and max(all_y) - min(all_y) > 80:
                    continue
                uf.union((dossier, a), (dossier, b))

    # Step 2: collect per-dossier clusters
    # Node is (dossierid, name, year_bin) so same name in the same dossier but
    # >80 years apart becomes a different cluster automatically.
    LIFESPAN = 80
    dossier_clusters: dict[tuple, list[dict]] = defaultdict(list)
    for _, row in df.iterrows():
        yr = int(row["year"]) if pd.notna(row.get("year")) else 0
        year_bin = yr // LIFESPAN
        base_node = (row["dossierid"], row["name"])
        # map the base UF node to the binned node so merged partial names
        # still land in the correct bin
        root = uf.find(base_node)
        binned = (root, year_bin)
        dossier_clusters[binned].append(row.to_dict())

    # Step 3: pick canonical name per cluster (most tokens, fewest abbrevs)
    def pick_canonical(names: list[str]) -> str:
        def score(n):
            toks = clean_tokens(n)
            abbr = sum(1 for t in toks if t.endswith(".") or len(t) <= 2)
            return (len(toks) - abbr, len(n))
        return max(names, key=score)

    per_dossier: list[dict] = []
    for root, rows in dossier_clusters.items():
        names = list({r["name"] for r in rows})
        canon = pick_canonical(names)
        occs = set()
        for r in rows:
            if isinstance(r.get("occupation_norm"), str):
                for o in r["occupation_norm"].split("|"):
                    o = o.strip()
                    if o and o != "unk":
                        occs.add(o)
        titles = set()
        for r in rows:
            if isinstance(r.get("title"), str):
                for t in r["title"].split("|"):
                    t = t.strip()
                    if t:
                        titles.add(t)
        fam = set()
        for r in rows:
            if isinstance(r.get("family_relation"), str):
                for f in r["family_relation"].split("|"):
                    f = f.strip()
                    if f:
                        fam.add(f)
        locs = set()
        for r in rows:
            if isinstance(r.get("location"), str):
                for l in r["location"].split("|"):
                    l = l.strip()
                    if l:
                        locs.add(l)
        orgs = set()
        for r in rows:
            if isinstance(r.get("org_affiliation"), str):
                for o in r["org_affiliation"].split("|"):
                    o = o.strip()
                    if o:
                        orgs.add(o)
        years = [int(r["year"]) for r in rows if pd.notna(r.get("year"))]

        def is_dead(r):
            v = r.get("is_deceased")
            return v == 1 or v == 1.0 or str(v) == "1.0"

        dead_years = [int(r["year"]) for r in rows
                      if pd.notna(r.get("year")) and is_dead(r)]
        live_years = [int(r["year"]) for r in rows
                      if pd.notna(r.get("year")) and not is_dead(r)]

        # Earliest year a deceased marker appears = upper bound on death year.
        # The person was already dead at (or before) this document.
        dead_year = min(dead_years) if dead_years else None

        per_dossier.append({
            "canonical": canon,
            "variants": sorted(names),
            "dossier": root[0],
            "mentions": len(rows),
            "years": [min(years), max(years)] if years else [0, 0],
            "occ": sorted(occs),   # norm only — occupation_text dropped
            "title": sorted(titles),
            "fam": sorted(fam),
            "loc": sorted(locs),
            "org": sorted(orgs),
            "dead_year": dead_year,   # earliest year marked deceased (None if never)
            "live_years": live_years, # years with live (non-deceased) mentions
            "ckey": canonical_key(canon),
        })

    # Step 3b: split any per-dossier cluster where live mentions appear after
    # the earliest deceased mention (those rows belong to a later generation).
    split_dossier: list[dict] = []
    for p in per_dossier:
        if p["dead_year"] is None or not p["live_years"]:
            split_dossier.append(p)
            continue
        late_live = [y for y in p["live_years"] if y > p["dead_year"]]
        if not late_live:
            split_dossier.append(p)
            continue
        # Build a "later person" entry from the late live mentions
        # (keep all fields the same except years and dead_year)
        early_live = [y for y in p["live_years"] if y <= p["dead_year"]]
        p_early = dict(p)
        p_early["live_years"] = early_live
        all_early = (early_live or []) + [p["dead_year"]]
        p_early["years"] = [min(all_early), max(all_early)]
        split_dossier.append(p_early)

        p_late = dict(p)
        p_late["dead_year"] = None
        p_late["live_years"] = late_live
        p_late["years"] = [min(late_live), max(late_live)]
        p_late["ckey"] = p["ckey"]   # same canonical key, will be re-grouped
        split_dossier.append(p_late)

    per_dossier = split_dossier

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
    persons = []
    for ckey, entries in cross.items():
        all_names = sorted({n for e in entries for n in e["variants"]})
        canon = pick_canonical([e["canonical"] for e in entries])
        occs  = sorted({o for e in entries for o in e["occ"]})
        titles = sorted({t for e in entries for t in e["title"]})
        fams  = sorted({f for e in entries for f in e["fam"]})
        locs  = sorted({l for e in entries for l in e["loc"]})
        orgs  = sorted({o for e in entries for o in e["org"]})
        dossiers = sorted({e["dossier"] for e in entries})
        all_years = [y for e in entries for y in e["years"] if y > 0]
        mentions = sum(e["mentions"] for e in entries)
        dead_years_all = [e["dead_year"] for e in entries if e["dead_year"] is not None]
        dead_year_out = min(dead_years_all) if dead_years_all else None
        persons.append({
            "n": canon,
            "v": all_names,
            "c": mentions,
            "d": len(dossiers),
            "y": [min(all_years), max(all_years)] if all_years else [0, 0],
            "dead_year": dead_year_out,  # earliest year mentioned as deceased
            "occ": occs,
            "tit": titles,
            "fam": fams,
            "loc": locs,
            "org": orgs,
            "dos": dossiers[:30],
        })

    persons.sort(key=lambda p: -p["c"])
    print(f"  → {len(persons):,} resolved persons from {len(df):,} mentions")
    return persons


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
    with open(OUT_PERSONS, "w", encoding="utf-8") as f:
        json.dump(persons, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Saved {OUT_PERSONS} ({len(persons):,} persons, "
          f"{len(json.dumps(persons, ensure_ascii=False).encode())/1e6:.1f} MB)")

    guild = build_guild_data(df)
    with open(OUT_GUILD, "w", encoding="utf-8") as f:
        json.dump(guild, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Saved {OUT_GUILD}")
