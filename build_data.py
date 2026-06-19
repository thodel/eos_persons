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
    """Stable sort key for cross-dossier matching."""
    return " ".join(sorted(expand(t) for t in clean_tokens(name)))


def tokens_subset(a: str, b: str) -> bool:
    """True if every (expanded) token of a appears in (expanded) tokens of b."""
    ta = {expand(t) for t in clean_tokens(a)}
    tb = {expand(t) for t in clean_tokens(b)}
    return len(ta) >= 1 and ta.issubset(tb)


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
    # "unambiguous" = exactly one longer name in the dossier is a superset of the shorter
    for dossier, grp in df.groupby("dossierid"):
        names = grp["name"].dropna().unique().tolist()
        names.sort(key=lambda n: -len(clean_tokens(n)))
        for i, a in enumerate(names):
            # find all longer names b that contain all tokens of a
            supersets = [b for b in names if b != a and tokens_subset(a, b)]
            if len(supersets) == 1:
                # unambiguous: exactly one match → safe to merge
                uf.union((dossier, a), (dossier, supersets[0]))

    # Step 2: collect per-dossier clusters
    dossier_clusters: dict[tuple, list[dict]] = defaultdict(list)
    for _, row in df.iterrows():
        node = (row["dossierid"], row["name"])
        root = uf.find(node)
        dossier_clusters[root].append(row.to_dict())

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
        dead = any(r.get("is_deceased") == 1 or r.get("is_deceased") == "1.0" for r in rows)
        per_dossier.append({
            "canonical": canon,
            "variants": sorted(names),
            "dossier": root[0],
            "mentions": len(rows),
            "years": [min(years), max(years)] if years else [0, 0],
            "occ": sorted(occs),
            "title": sorted(titles),
            "fam": sorted(fam),
            "loc": sorted(locs),
            "org": sorted(orgs),
            "dead": dead,
            "ckey": canonical_key(canon),
        })

    # Step 4: cross-dossier grouping by canonical key
    # Only merge across dossiers when the canonical name has ≥2 tokens
    # (single first-names like "Hans" or "Anna" are too ambiguous to link globally)
    cross: dict[str, list[dict]] = defaultdict(list)
    _uid = 0
    for p in per_dossier:
        key_tokens = p["ckey"].split()
        if len(key_tokens) >= 2:
            # For common names (surname + firstname only), also require year-range
            # overlap within a human lifetime (≤70 yrs) to avoid merging homonyms
            existing = cross[p["ckey"]]
            if existing:
                # check overlap with the existing cluster's year range
                cluster_y0 = min(e["years"][0] for e in existing if e["years"][0] > 0)
                cluster_y1 = max(e["years"][1] for e in existing if e["years"][1] > 0)
                py0, py1 = p["years"]
                overlap = py0 <= cluster_y1 + 70 and py1 >= cluster_y0 - 70
                if not overlap:
                    cross[f"__time_{_uid}"].append(p)
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
        dead = any(e["dead"] for e in entries)
        persons.append({
            "n": canon,
            "v": all_names,
            "c": mentions,
            "d": len(dossiers),
            "y": [min(all_years), max(all_years)] if all_years else [0, 0],
            "occ": occs,
            "tit": titles,
            "fam": fams,
            "loc": locs,
            "org": orgs,
            "dead": dead,
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
