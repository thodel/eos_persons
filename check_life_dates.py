#!/usr/bin/env python3
"""
check_life_dates.py — the cross-check of life dates, written up.

For every HLS biography a register person is linked to it lists the two
sources of the life — the HLS dates with their qualifiers, Wikidata's dates
given to the year — how they were reconciled (lifedates.explain), and what the
register holds for that life. It then verifies the index: every linked person
has to fit the life of its biography (link_hls.person_fits).

    python3 check_life_dates.py     # → life_dates_check.csv, life_dates_report.md

Reads persons_resolved.json, the HLS table (link_hls.default_hls), and
hls_life_splits.csv — the persons apply_hls_links.py took apart because part of
their mentions lay outside the life.
"""
import collections
import csv
import json
import os

from link_hls import default_hls, life_envelope, load_hls, person_fits

OUT_CSV = "life_dates_check.csv"
OUT_MD = "life_dates_report.md"
SPLITS = "hls_life_splits.csv"
COLS = ["hls_id", "hls_title", "hls_birth", "birth_kind", "wikidata_birth", "birth",
        "hls_death", "death_kind", "wikidata_death", "death",
        "born_from", "born_to", "died_from", "died_to",
        "persons", "mentions", "first_mention", "last_mention", "all_fit"]
HOW = {"agree": "the two sources agree",
       "no_wikidata": "no year-precise date on Wikidata",
       "wikidata_used": "HLS gives a fence (first mention, before, after); Wikidata's year is taken",
       "same_year": "Wikidata repeats the HLS's first or last mention as the date",
       "wikidata_ignored": "Wikidata's year does not respect the HLS fence and is ignored",
       "disagree": "two firm dates that differ — the life holds both",
       "wikidata_only": "only Wikidata has a date"}
KIND = {"before_birth": "mentioned before the birth",
        "child": "a party to a transaction as a child",
        "dead_early": "called deceased before the death",
        "after_death": "a party to a transaction after the death",
        "late_naming": "named as living more than 15 years after the death",
        "beyond": "mentioned more than 60 years after the death"}


def main():
    persons = json.load(open("persons_resolved.json", encoding="utf-8"))
    linked = collections.defaultdict(list)
    for p in persons:
        if p.get("hls"):
            linked[p["hls"]["id"]].append(p)
    bios = {b["id"]: b for b in load_hls(default_hls()) if b["id"] in linked}

    rows, misfit = [], []
    for hid in sorted(linked, key=lambda h: linked[h][0]["hls"]["t"]):
        ps, bio = linked[hid], bios.get(hid)
        fit = True
        for p in ps:
            if not person_fits(life_envelope(p), p):
                fit = False
                misfit.append(p)
        if bio is None:               # the table changed since the links were set
            continue
        life = bio["life"]
        rows.append({
            "hls_id": hid, "hls_title": bio["title"],
            "hls_birth": bio["birth"] or "", "birth_kind": bio["birth_kind"] or "",
            "wikidata_birth": "|".join(map(str, sorted(set(bio["wd_birth"])))),
            "birth": bio["life_how"][0],
            "hls_death": bio["death"] or "", "death_kind": bio["death_kind"] or "",
            "wikidata_death": "|".join(map(str, sorted(set(bio["wd_death"])))),
            "death": bio["life_how"][1],
            "born_from": life.blo, "born_to": life.bhi,
            "died_from": life.dlo, "died_to": life.dhi,
            "persons": len(ps), "mentions": sum(p.get("c", 0) for p in ps),
            "first_mention": min(p["y"][0] for p in ps),
            "last_mention": max(p["y"][1] for p in ps),
            "all_fit": "yes" if fit else "NO",
        })
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    splits = list(csv.DictReader(open(SPLITS, encoding="utf-8"))) if os.path.exists(SPLITS) else []
    n_linked = sum(len(v) for v in linked.values())
    L = []
    L.append("# Life dates: HLS and Wikidata against the register\n")
    L.append(f"Written by `check_life_dates.py`. {n_linked} register persons are linked to "
             f"{len(linked)} HLS biographies; the table behind this report is `{OUT_CSV}`, "
             f"the persons that were split are in `{SPLITS}`. The rules are those of "
             "`lifedates.py`.\n")

    L.append("## The two sources\n")
    for fld, label in (("birth", "Birth"), ("death", "Death")):
        c = collections.Counter(r[fld] for r in rows)
        L.append(f"**{label}** — " + "; ".join(
            f"{n} × {HOW[k]}" for k, n in c.most_common()) + ".\n")
    kinds = collections.Counter((r["birth_kind"] or "exact") for r in rows)
    L.append("Qualifiers of the HLS birth dates: " + ", ".join(
        f"{k.replace('_', ' ')} {n}" for k, n in kinds.most_common()) + "; of the death dates: "
        + ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in collections.Counter(
            (r["death_kind"] or "exact") for r in rows).most_common()) + ".\n")

    dis = [r for r in rows if "disagree" in (r["birth"], r["death"])
           or "wikidata_ignored" in (r["birth"], r["death"])]
    L.append(f"### Where HLS and Wikidata contradict each other ({len(dis)})\n")
    L.append("| biography | HLS | Wikidata | what was done | life used |")
    L.append("|---|---|---|---|---|")
    for r in dis:
        for fld, hv, kv, wv in (("birth", "hls_birth", "birth_kind", "wikidata_birth"),
                                ("death", "hls_death", "death_kind", "wikidata_death")):
            if r[fld] in ("disagree", "wikidata_ignored"):
                kind = (r[kv] or "exact").replace("_", " ")
                rng = (f"born {r['born_from']}–{r['born_to']}" if fld == "birth"
                       else f"died {r['died_from']}–{r['died_to']}")
                L.append(f"| {r['hls_title']} | {fld} {r[hv]} ({kind}) | {r[wv].replace('|', ', ')} "
                         f"| {HOW[r[fld]]} | {rng} |")
    L.append("")

    L.append("## Register persons against the life\n")
    L.append(f"Every linked person fits the life of its biography: "
             f"**{'yes' if not misfit else 'NO — ' + str(len(misfit)) + ' do not'}**.\n")
    for p in misfit[:20]:
        L.append(f"- {p['n']} {p['y']} ⇄ {p['hls']['t']} {p['hls'].get('life')}")
    if splits:
        c = collections.Counter()
        for s in splits:
            for k in s["conflicts"].split("|"):
                if k:
                    c[k.split(":")[0]] += 1
        early = sum(1 for s in splits if s["earlier"])
        late = sum(1 for s in splits if s["later"])
        L.append(f"On the way there {len(splits)} persons of the raw index were taken apart, "
                 "because part of their mentions lie outside the life — an earlier bearer "
                 f"of the name was split off {early} times, a later one {late} times. "
                 "What the life excluded (persons):\n")
        for k, n in c.most_common():
            L.append(f"- {KIND.get(k, k)}: {n}")
        L.append("")
        L.append("| register person | mentions | biography | life (born … died) | kept | earlier bearer | later bearer |")
        L.append("|---|---|---|---|---|---|---|")
        for s in sorted(splits, key=lambda s: (s["hls_title"], s["person"])):
            lf = s["life"].split("|")
            L.append(f"| {s['person']} | {s['years']} ×{s['mentions']} | {s['hls_title']} "
                     f"| {lf[0]}–{lf[1]} … {lf[2]}–{lf[3]} | {s['kept']} | {s['earlier'] or '–'} "
                     f"| {s['later'] or '–'} |")
        L.append("")
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"→ {OUT_CSV}: {len(rows)} biographies; → {OUT_MD}")
    print(f"  linked persons: {n_linked}; not fitting their life: {len(misfit)}; "
          f"persons split: {len(splits)}")
    c = collections.Counter(r["birth"] for r in rows) + collections.Counter(r["death"] for r in rows)
    print(f"  HLS against Wikidata (birth and death dates): {dict(c)}")


if __name__ == "__main__":
    main()
