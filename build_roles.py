#!/usr/bin/env python3
"""
build_roles.py — derive office / role lists ("Rollen") from resolved persons.

Reads persons_resolved.json and assigns each person to civic, judicial,
administrative, military, ecclesiastical and status positions, based on their
normalized affiliations (org), titles (tit) and occupations (occ). Emits
roles_data.json: a taxonomy of positions, each with the persons who held it
and the years they are attested in that role.
"""
import re
import json
import collections

from build_data import GUILD_MAP   # reuse the 16-guild occupation mapping

PERSONS = "persons_resolved.json"

# Offices a Zunftmeister may also hold that say nothing about their guild —
# excluded when inferring the Zunft from a person's other occupations.
NON_CRAFT = {
    "rat", "ratsherr", "bürgermeister", "burgermeister", "vogt", "obervogt",
    "untervogt", "landvogt", "statthalter", "schultheiss", "schaffner",
    "salzmeister", "rüstmeister", "gerichtsschreiber", "stadtschreiber",
    "kaplan", "no_occ", "käufer", "zunftmeister", "oberster zunftmeister",
    "alt-zunftmeister", "alt oberster zunftmeister", "obristmeister",
}


def infer_guild(occs):
    """Infer a Zunftmeister's guild from any craft occupation they also bear."""
    for o in occs:
        o = o.strip().lower()
        if o in NON_CRAFT:
            continue
        g = GUILD_MAP.get(o)
        if g and g not in ("Klerus & Freie Berufe", "Verwaltung"):
            return g
    return None


def clean(s):
    return re.sub(r"[^\wäöüáàéè]", "", s.strip().lower())


# ── Position taxonomy ────────────────────────────────────────────────────────
# Each position has: id, label, category, and matchers over the three fields.
#   occ  : set of exact normalized occupation strings (lower-case)
#   occ_re: regex tested against each occupation
#   org_re: regex tested against each cleaned org affiliation
#   tit  : set of cleaned title tokens
# A person joins the position if ANY matcher fires on ANY of their values.

CATEGORIES = [
    ("regiment", "Regiment & Rat"),
    ("justiz", "Justiz"),
    ("verwaltung", "Verwaltung & Kanzlei"),
    ("militaer", "Militär"),
    ("kirche", "Kirche & Klerus"),
    ("status", "Stand & Titel"),
]

POSITIONS = [
    # ── Regiment & Rat ──
    dict(id="rat", label="Rat (Ratsherren)", cat="regiment",
         org_re=r"^r[aä]h?t(z|s|en|e|es)?$",
         occ={"rat", "ratsherr", "ratsgeselle", "ratsredner", "ratssubstitut",
              "ratsubstitut", "altratsherr"}),
    dict(id="buergermeister", label="Bürgermeister", cat="regiment",
         tit={"burgermeister", "burgmeister"},
         occ={"bürgermeister", "burgermeister", "alt-bürgermeister", "burgmeister",
              "stadt-bürgermeister"}),
    dict(id="oberstzunftmeister", label="Oberstzunftmeister", cat="regiment",
         occ={"oberster zunftmeister", "alt oberster zunftmeister",
              "obristmeister", "oberstzunftmeister"}, guild_facet=True),
    dict(id="zunftmeister", label="Zunftmeister", cat="regiment",
         occ={"zunftmeister", "alt-zunftmeister"}, guild_facet=True),
    dict(id="statthalter", label="Statthalter", cat="regiment",
         occ={"statthalter"}),
    dict(id="ratsbote", label="Ratsboten & Ratsknechte", cat="regiment",
         occ={"ratsbote", "ratsknecht", "oberster ratknecht", "ratspfeifer"}),

    # ── Justiz ──
    dict(id="gericht", label="Gerichtsmitglieder", cat="justiz",
         org_re=r"^ger(icht)?(s|e|en)?$",
         occ={"richter", "bergrichter"}),
    dict(id="schultheiss", label="Schultheiss", cat="justiz",
         occ={"schultheiss", "alt-schultheiss", "stadt-schultheiss"}),
    dict(id="vogt", label="Vögte (Land-, Ober-, Untervogt)", cat="justiz",
         occ={"vogt", "landvogt", "obervogt", "untervogt", "reichsvogt",
              "bettelvogt"}),
    dict(id="notar", label="Notare & Prokuratoren", cat="justiz",
         occ={"notar", "prokurator"}),
    dict(id="nachrichter", label="Nachrichter (Scharfrichter)", cat="justiz",
         occ={"nachrichter"}),

    # ── Verwaltung & Kanzlei ──
    dict(id="stadtschreiber", label="Stadtschreiber", cat="verwaltung",
         occ={"stadtschreiber", "oberschreiber"}),
    dict(id="schreiber", label="Schreiber (Kanzlei)", cat="verwaltung",
         occ_re=r"schreiber$"),
    dict(id="schaffner", label="Schaffner", cat="verwaltung",
         occ_re=r"schaffner$"),
    dict(id="muenzmeister", label="Münzmeister", cat="verwaltung",
         occ={"münzmeister", "gold-münzmeister"}),
    dict(id="baumeister", label="Bau- & Werkmeister", cat="verwaltung",
         occ={"baumeister", "werkmeister", "steinmetzwerkmeister",
              "zimmerwerkmeister", "brückenmeister", "wegmeister", "dolenmeister",
              "brunnenmeister", "mauermeister"}),
    dict(id="finanzmeister", label="Finanz- & Lagerämter", cat="verwaltung",
         occ={"zinsmeister", "salzmeister", "kornmeister", "rechenmeister",
              "ballenmeister", "brotmeister", "ackermeister"}),
    dict(id="spitalmeister", label="Spitalmeister & Pfleger", cat="verwaltung",
         occ={"spitalmeister", "alt-spitalmeister", "pfleger", "pflegerherr",
              "herbergmeister"}),

    # ── Militär ──
    dict(id="hauptmann", label="Hauptleute", cat="militaer",
         tit={"hauptmann", "hauptman"}, occ={"hauptmann"}),
    dict(id="wehrmeister", label="Wacht-, Büchsen- & Rüstmeister", cat="militaer",
         occ={"wachtmeister", "büchsenmeister", "rüstmeister", "gussmeister"}),

    # ── Kirche & Klerus ──
    dict(id="kaplan", label="Kapläne", cat="kirche", occ={"kaplan"}),
    dict(id="pfarrer", label="Pfarrer", cat="kirche", occ={"pfarrer"}),
    dict(id="prediger", label="Prediger", cat="kirche", occ={"prediger"}),
    dict(id="praelat", label="Prälaten (Dekan, Propst, Prior, Abt, Bischof)",
         cat="kirche",
         occ={"dekan", "domdekan", "propst", "prior", "abt", "bischof"}),
    dict(id="orden", label="Ordensleute (Bruder/Schwester)", cat="kirche",
         tit={"bruder", "swester", "schwester"}),

    # ── Stand & Titel ──
    dict(id="doktor", label="Doktoren & Magister", cat="status",
         tit={"dr", "d", "doctor", "doktor", "magister", "mag"}),
    dict(id="ritter", label="Ritter", cat="status",
         tit={"ritter", "ritters"}),
    dict(id="junker", label="Junker (Adel)", cat="status",
         tit={"junckher", "juncker", "junker", "junkher", "jungkher", "jungher",
              "jkr", "jkn", "jr", "j"}),
    dict(id="meister", label="Meister", cat="status",
         tit={"meister", "meyster", "mr", "m"}),
    dict(id="buerger", label="Bürger", cat="status",
         org_re=r"^(burger|bürger|burgere|burgern|burgere|bgr|civis|civi|bur|b)$"),
    dict(id="hintersaesse", label="Hintersässen & Einwohner", cat="status",
         org_re=r"^(hinders|sesshaf|jnwoner|jnwohner|hindersa|hinderse)"),
]


def matches(pos, occs, tits, orgs):
    occset = pos.get("occ")
    if occset and any(o in occset for o in occs):
        return True
    occ_re = pos.get("occ_re")
    if occ_re and any(re.search(occ_re, o) for o in occs):
        return True
    titset = pos.get("tit")
    if titset and any(clean(t) in titset for t in tits):
        return True
    org_re = pos.get("org_re")
    if org_re and any(re.match(org_re, clean(o)) for o in orgs):
        return True
    return False


def main():
    persons = json.load(open(PERSONS))
    buckets = {p["id"]: [] for p in POSITIONS}

    for p in persons:
        occs = [o.strip().lower() for o in p.get("occ", [])]
        tits = p.get("tit", [])
        orgs = p.get("org", [])
        if not (occs or tits or orgs):
            continue
        name = p["n"]
        if not name or len(name) < 2:
            continue
        guild = infer_guild(occs)
        for pos in POSITIONS:
            if matches(pos, occs, tits, orgs):
                rec = {"n": name, "y": p.get("y"), "c": p.get("c", 0)}
                if pos.get("guild_facet"):
                    rec["g"] = guild or "unbekannt"
                buckets[pos["id"]].append(rec)

    positions_out = []
    for pos in POSITIONS:
        people = buckets[pos["id"]]
        # dedup by name, keep widest year range / max mentions
        by_name = {}
        for r in people:
            e = by_name.get(r["n"])
            if e is None:
                by_name[r["n"]] = dict(r)
            else:
                if r.get("y") and e.get("y"):
                    e["y"] = [min(e["y"][0], r["y"][0]), max(e["y"][1], r["y"][1])]
                elif r.get("y"):
                    e["y"] = r["y"]
                e["c"] = max(e["c"], r["c"])
                # prefer a known guild over "unbekannt"
                if e.get("g") in (None, "unbekannt") and r.get("g") not in (None, "unbekannt"):
                    e["g"] = r["g"]
        merged = sorted(by_name.values(),
                        key=lambda r: (r["y"][0] if r.get("y") else 9999, r["n"]))
        years = [r["y"] for r in merged if r.get("y")]
        entry = {
            "id": pos["id"],
            "label": pos["label"],
            "cat": pos["cat"],
            "count": len(merged),
            "year_min": min(y[0] for y in years) if years else None,
            "year_max": max(y[1] for y in years) if years else None,
            "persons": merged,
        }
        if pos.get("guild_facet"):
            gc = collections.Counter(r.get("g", "unbekannt") for r in merged)
            # known guilds first (by count), "unbekannt" last
            known = sorted([(g, n) for g, n in gc.items() if g != "unbekannt"],
                           key=lambda x: -x[1])
            facet = [{"guild": g, "count": n} for g, n in known]
            if gc.get("unbekannt"):
                facet.append({"guild": "unbekannt", "count": gc["unbekannt"]})
            entry["guilds"] = facet
        positions_out.append(entry)

    out = {
        "categories": [{"id": cid, "label": lbl} for cid, lbl in CATEGORIES],
        "positions": positions_out,
    }
    with open("roles_data.json", "w") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    import os
    print(f"roles_data.json: {os.path.getsize('roles_data.json')/1024:.0f} KB")
    print(f"\n{'position':40s} {'cat':12s} count   span")
    for p in positions_out:
        print(f"  {p['label']:38s} {p['cat']:11s} {p['count']:5d}  "
              f"{p['year_min']}–{p['year_max']}")


if __name__ == "__main__":
    main()
