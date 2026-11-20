#!/usr/bin/env python3
"""
link_zunftmeister.py — propose links between the guild masters (Zunftmeister)
of eight Basel guilds and the merged eos persons.

`zunftmeister/zunftmeister.csv` collects the published master lists of the
guilds (Weinleuten, Safran, Schmieden, Hausgenossen, Gartnern, Gerbern,
Schiffleuten, Goldener Stern; see `zunftmeister/README.md` for sources). This
script matches every master elected up to 1710 against `merged_persons.json`:
the surname and given name must agree and the person's life span (or, without
life dates, the span of his HGB mentions) must be compatible with the year of
election. The output is a candidate table for review, not an automatic merge.

    python3 link_zunftmeister.py \
        --zunftmeister zunftmeister/zunftmeister.csv \
        --persons      merged_persons.json \
        --out          link_zunftmeister_candidates.csv

Tiers (column `tier`):
  stark           exact name, life span known and compatible, and the person
                  is already recorded as a Zunftmeister or in a trade of the
                  guild
  wahrscheinlich  exact name, or a spelling variant with the same given name,
                  life span known and compatible
  möglich         name agrees, but only the HGB mention span fits (or the name
                  is a near match)

A second pass (`link_hgb`) extends the match to all 127,175 persons of the HGB
index `persons_resolved.json`, including those without HBLS, HLS or GND link.
Those persons have no life dates, only the span of their mentions, so the
evidence is weaker and the tiers are defined differently (see `hgb_tier`):
the namesake count (`namesakes`) is part of the output because for common
names a match is only a candidate.

The year of election is the first year of the entry in the published list.
"""
import argparse
import csv
import json
import re
from pathlib import Path

from link_hls import norm_token, given_key, given_ratio, ratio

HERE = Path(__file__).resolve().parent
LAST_YEAR = 1710          # the HGB corpus ends around 1700

PARTICLES = {"von", "vom", "zum", "zem", "zur", "zu", "de", "d", "der", "im", "am",
             "an", "ab", "in", "uff", "uf", "ze"}

# trade words that point to a guild; matched against the person's occupations
GUILD_TRADES = {
    "Hausgenossen": ("goldschmid", "wechsler", "münzmeister", "kannengiess", "zinngiess",
                     "glockengiess", "hafengiess", "buchdrucker", "siegelschneider"),
    "Safran": ("krämer", "apotheker", "kaufmann", "kaufherr", "gewürz", "spezierer",
               "seidenkrämer", "gürtler", "spengler", "seckler", "hutmacher"),
    "Schmieden": ("schmied", "eisen", "schlosser", "kupferschmied", "nagler"),
    "Gerbern": ("gerber", "lederer", "weissgerber"),
    "Gartnern": ("gärtner", "gartner", "gartner", "krämer", "händler"),
    "Schiffleuten": ("schiff", "fischer", "fergger", "ferger", "fährmann"),
    "Weinleuten": ("wein", "wirt", "weinmann", "kaufmann", "schenk"),
    "Goldener Stern": ("scherer", "wundarzt", "bader", "chirurg", "arzt", "maler", "sattler"),
}
MASTER_WORDS = ("zunftmeister", "oberstzunftmeister", "obristzunftmeister", "obrist zunftmeister",
                "meister der zunft", "zunft")


def clean_name(name):
    """Drop titles, parentheses and `genannt` / `=` appendices."""
    n = re.sub(r"\([^)]*\)", " ", name)
    n = re.split(r"\bgenannt\b|=|«", n)[0]
    n = re.sub(r"\b(Dr|Prof|Med|Hptm)\.?\b", " ", n)
    return re.sub(r"\s+", " ", n).strip(" ,.")


def split_name(name, surname_first=False):
    """-> (given, surname) token strings, `surname` incl. leading particles.

    The lists are not uniform: most give `forename surname`, the Schmieden list
    mostly `surname forename`. `name_candidates` tries both.
    """
    toks = clean_name(name).replace(",", " ").split()
    if not toks:
        return "", ""
    if len(toks) == 1:
        return "", toks[0]
    if surname_first:
        # leading particles belong to the surname: "von Oltingen Hans"
        i = 0
        while i < len(toks) - 1 and toks[i].lower() in PARTICLES:
            i += 1
        i += 1
        return " ".join(toks[i:]), " ".join(toks[:i])
    i = len(toks) - 1
    while i > 0 and toks[i - 1].lower() in PARTICLES:
        i -= 1
    return " ".join(toks[:i]), " ".join(toks[i:])


def name_candidates(name):
    a = split_name(name, False)
    b = split_name(name, True)
    return [a] if a == b else [a, b]


def surname_key(s):
    toks = [norm_token(t) for t in s.split() if norm_token(t) and t.lower() not in PARTICLES]
    return toks[-1] if toks else ""


def life_window(p):
    """(lo, hi, basis): the years in which the person can have been a master."""
    b, d = p.get("birth_year"), p.get("death_year")
    ms = p.get("mention_span") or [None, None]
    if b is not None and d is not None:
        return b + 22, d + 1, "life"
    if b is not None:
        return b + 22, b + 85, "life"
    if d is not None:
        return d - 65, d + 1, "life"
    if ms[0] is not None:
        return ms[0] - 12, ms[1] + 12, "mentions"
    return None, None, None


def fits(window, yf, yt):
    lo, hi, _ = window
    if lo is None:
        return False
    return not (hi < yf or lo > (yt or yf))


def hints(p, zunft):
    text = " ".join((p.get("occupations") or []) + (p.get("titles") or []) +
                    (p.get("roles_gnd") or []) + (p.get("organisations") or [])).lower()
    master = any(w in text for w in MASTER_WORDS)
    trade = any(t in text for t in GUILD_TRADES.get(zunft, ()))
    return master, trade


def score_pair(master_cands, p):
    """Best (surname_ratio, given_ratio) over the name orders.

    A conflicting count of given names ("Hans Heinrich" vs "Johannes") caps the
    given-name score at 0.85: it is a near match, never an exact one, because
    the second given name is what tells the Basel namesakes apart.
    """
    best = (0.0, 0.0)
    ps, pg = surname_key(p.get("surname") or ""), given_key(p.get("given") or "")
    for given, surname in master_cands:
        sr = ratio(surname_key(surname), ps)
        gk = given_key(given)
        gr = given_ratio(gk, pg) if gk and pg else 0.5
        if gk and pg and len(gk.split()) != len(pg.split()):
            gr = min(gr, 0.85)
        if (sr, gr) > best:
            best = (sr, gr)
    return best


def tier_of(sr, gr, window, yf, yt, master, trade):
    ok = fits(window, yf, yt)
    if not ok:
        return None
    exact = sr == 1.0 and gr >= 0.9
    near = sr >= 0.88 and gr >= 0.8
    if not (exact or near):
        return None
    if window[2] == "life" and exact and (master or trade):
        return "stark"
    if window[2] == "life" and exact:
        return "wahrscheinlich"
    if window[2] == "life" and near and (master or trade or gr >= 0.9):
        return "wahrscheinlich"      # spelling variant (Fäsch/Faesch) with a fitting life
    return "möglich"


GUILD_NAMES = {
    "Hausgenossen": ("hausgenoss",), "Safran": ("safran",), "Schmieden": ("schmied",),
    "Gerbern": ("gerber",), "Gartnern": ("gartner", "gärtner"), "Schiffleuten": ("schiffleut",),
    "Weinleuten": ("weinleut",), "Goldener Stern": ("stern", "himmel"),
}
HGB_MAX_NAMESAKES = 3      # beyond this a name-only match is not listed


def hgb_hints(p, zunft):
    """(zunftmeister title, guild named in the organisation, trade of the guild)."""
    titles = " ".join(p.get("tit") or []).lower()
    orgs = " ".join(p.get("org") or []).lower()
    occ = " ".join(p.get("occ") or []).lower()
    master = "zunftmeister" in titles or "zunfftmeister" in titles or "zunftenstr" in titles
    guild = any(g in orgs for g in GUILD_NAMES.get(zunft, ()))
    trade = any(t in occ for t in GUILD_TRADES.get(zunft, ()))
    return master, guild, trade


def hgb_span_fits(p, yf, yt, tight):
    """Mentions around the election: tight = a mention within 5 years of the term."""
    y0, y1 = p["y"]
    if p.get("dead_year") and p["dead_year"] < yf - 2:
        return False
    if y1 - y0 > 75:                       # a merged namesake chain, not one man
        return False
    if tight:
        return y0 <= (yt or yf) + 5 and y1 >= yf - 5
    return y0 <= (yt or yf) + 12 and y1 >= yf - 15


def hgb_tier(exact, tight, master, guild, trade, namesakes):
    """Tiers for persons without life dates.

    wahrscheinlich  exact name, mentions around the election, and either a
                    Zunftmeister title / the guild in the organisation or a
                    trade of the guild
    möglich         name agrees and the mentions are in the right decades,
                    with at most HGB_MAX_NAMESAKES candidates for the master
    """
    if exact and tight and (master or guild or trade):
        return "wahrscheinlich"
    if namesakes <= HGB_MAX_NAMESAKES or master or guild:
        return "möglich"
    return None


def hgb_key(p):
    return f"{p['n']}#{p['y'][0]}"


def load_masters(path):
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            yf = int(r["year_from"])
            if yf <= LAST_YEAR:
                yield r, yf, int(r["year_to"]) if r["year_to"].isdigit() else None


def link(masters_path, persons):
    out = []
    by_surname = {}
    for p in persons:
        by_surname.setdefault(surname_key(p.get("surname") or "")[:2], []).append(p)
    for r, yf, yt in load_masters(masters_path):
        cands = name_candidates(r["name"])
        keys = {surname_key(s)[:2] for _, s in cands if surname_key(s)}
        pool = [p for k in sorted(keys) for p in by_surname.get(k, [])]
        found = []
        for p in pool:
            sr, gr = score_pair(cands, p)
            if sr < 0.88 or gr < 0.8:
                continue
            window = life_window(p)
            master, trade = hints(p, r["zunft"])
            t = tier_of(sr, gr, window, yf, yt, master, trade)
            if not t:
                continue
            auth = p.get("authority") or {}
            found.append({
                "zunft": r["zunft"], "master": r["name"], "year_from": yf,
                "year_to": yt or "", "pool": "merged", "person_id": p["id"], "person": p["name"],
                "birth": p.get("birth_year") or "", "death": p.get("death_year") or "",
                "mention_span": "-".join(str(x) for x in (p.get("mention_span") or [])),
                "basis": window[2], "name_surname": round(sr, 2), "name_given": round(gr, 2),
                "recorded_master": "ja" if master else "", "trade_match": "ja" if trade else "",
                "status": p.get("status", ""),
                "wikidata": ";".join(auth.get("wikidata", []) if isinstance(auth.get("wikidata"), list) else [auth.get("wikidata", "")]).strip(";"),
                "gnd": ";".join(auth.get("gnd", []) if isinstance(auth.get("gnd"), list) else [auth.get("gnd", "")]).strip(";"),
                "tier": t,
            })
        rank = {"stark": 0, "wahrscheinlich": 1, "möglich": 2}
        found.sort(key=lambda x: (rank[x["tier"]], -x["name_surname"], -x["name_given"]))
        out.extend(found[:6])
    return out


def link_hgb(masters_path, resolved, merged_ids=None):
    """Second pass over persons_resolved.json (all HGB persons).

    `merged_ids` maps an HGB key (`name#first year`) to the merged person id, so
    that a candidate already in `merged_persons.json` is marked as such.
    """
    merged_ids = merged_ids or {}
    by_surname = {}
    for p in resolved:
        toks = p["n"].split()
        if toks:
            by_surname.setdefault(surname_key(toks[-1])[:2], []).append(p)
    rank = {"wahrscheinlich": 0, "möglich": 1}
    out = []
    for r, yf, yt in load_masters(masters_path):
        cands = name_candidates(r["name"])
        keys = {surname_key(s)[:2] for _, s in cands if surname_key(s)}
        found = []
        for p in (q for k in sorted(keys) for q in by_surname.get(k, [])):
            toks = p["n"].split()
            probe = {"surname": toks[-1], "given": " ".join(toks[:-1])}
            sr, gr = score_pair(cands, probe)
            if sr < 0.9 or gr < 0.8:
                continue
            if not hgb_span_fits(p, yf, yt, tight=False):
                continue
            tight = hgb_span_fits(p, yf, yt, tight=True)
            found.append((p, sr, gr, tight))
        for p, sr, gr, tight in found:
            master, guild, trade = hgb_hints(p, r["zunft"])
            t = hgb_tier(sr == 1.0 and gr >= 0.9, tight, master, guild, trade, len(found))
            if not t:
                continue
            key = hgb_key(p)
            out.append({
                "zunft": r["zunft"], "master": r["name"], "year_from": yf,
                "year_to": yt or "", "pool": "hgb", "person_id": merged_ids.get(key, key),
                "person": p["n"], "birth": "", "death": p.get("dead_year") or "",
                "mention_span": f"{p['y'][0]}-{p['y'][1]}", "basis": "mentions",
                "name_surname": round(sr, 2), "name_given": round(gr, 2),
                "recorded_master": "ja" if master else "", "guild_org": "ja" if guild else "",
                "trade_match": "ja" if trade else "", "namesakes": len(found),
                "n_dossiers": p.get("d", ""), "occupations": ";".join(p.get("occ") or []),
                "status": "", "wikidata": "", "gnd": "", "tier": t,
            })
    out.sort(key=lambda x: (x["zunft"], x["year_from"], x["master"], rank[x["tier"]],
                            -x["name_surname"], x["person"], x["mention_span"]))
    # at most six per master
    kept, seen = [], {}
    for x in out:
        k = (x["zunft"], x["master"], x["year_from"])
        seen[k] = seen.get(k, 0) + 1
        if seen[k] <= 6:
            kept.append(x)
    return kept


FIELDS = ["zunft", "master", "year_from", "year_to", "pool", "person_id", "person", "birth", "death",
          "mention_span", "basis", "name_surname", "name_given", "recorded_master", "guild_org",
          "trade_match", "namesakes", "n_dossiers", "occupations", "status", "wikidata", "gnd", "tier"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zunftmeister", default=str(HERE / "zunftmeister" / "zunftmeister.csv"))
    ap.add_argument("--persons", default=str(HERE / "merged_persons.json"))
    ap.add_argument("--hgb", default=str(HERE / "persons_resolved.json"),
                    help="all HGB persons (second pass); '' skips it")
    ap.add_argument("--out", default=str(HERE / "link_zunftmeister_candidates.csv"))
    a = ap.parse_args(argv)
    persons = json.load(open(a.persons, encoding="utf-8"))
    rows = link(a.zunftmeister, persons)
    if a.hgb:
        merged_ids = {s["id"]: p["id"] for p in persons for s in p.get("sources", [])
                      if s.get("corpus") == "hgb"}
        rows += link_hgb(a.zunftmeister, json.load(open(a.hgb, encoding="utf-8")), merged_ids)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    n_masters = sum(1 for _ in load_masters(a.zunftmeister))
    for pool in ("merged", "hgb"):
        sub = [r for r in rows if r["pool"] == pool]
        linked = {(r["zunft"], r["master"], r["year_from"]) for r in sub}
        by_tier = {}
        for r in sub:
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
        print(f"{pool}: {len(linked)} of {n_masters} masters up to {LAST_YEAR} with candidates; "
              f"{len(sub)} rows {by_tier}")
    anyl = {(r["zunft"], r["master"], r["year_from"]) for r in rows}
    print(f"together: {len(anyl)} masters with at least one candidate")


if __name__ == "__main__":
    main()
