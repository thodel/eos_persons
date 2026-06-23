#!/usr/bin/env python3
"""
build_movements.py — regenerate movements.csv (Personenbewegungen) input.

Each row is one appearance of a person at a property location in a given year.
Persons are grouped by their *deduplicated* identity (persons_resolved.json),
so spelling variants that previously looked like separate one-off people now
form a single trajectory across the city.

Pipeline:
  • dossier → LV95 coordinate, read from the corpus XML metadata;
  • each raw mention (persons.csv: name, occupation, year, dossier) is mapped to
    its resolved person via the person's (dossier, name) list;
  • a person who appears at ≥2 distinct locations is emitted as a trajectory,
    sorted by year, with event_role = start (first) / end (last) / present.

Schema matches the existing movements.csv:
  ,person_id,name,occupation,coordinates,year,event_role
"""
import re
import csv
import json
import collections

csv.field_size_limit(10_000_000)

XML = "hgb_full_26_05_29_05.xml"
PERSONS = "persons_resolved.json"
RAW = "persons.csv"
OUT = "movements.csv"
MIN_LOCATIONS = 2     # a "movement" needs at least two distinct places


def dossier_coords():
    """dossier id → 'POINT(E N)' (LV95), first occurrence in the XML."""
    coords = {}
    pat = re.compile(r'dossierid="([^"]+)"[^>]*location="(POINT\([^"]+\))"')
    with open(XML, errors="replace") as f:
        for line in f:
            if "dossierid" not in line or "location" not in line:
                continue
            m = pat.search(line)
            if m and m.group(1) not in coords:
                coords[m.group(1)] = m.group(2)
    return coords


def main():
    print("Reading dossier coordinates …")
    coords = dossier_coords()
    print(f"  {len(coords)} dossiers with coordinates")

    persons = json.load(open(PERSONS, encoding="utf-8"))
    # (dossier, name) → resolved person index
    key2person = {}
    for i, p in enumerate(persons):
        for e in p.get("dos", []):
            if isinstance(e, list) and len(e) >= 2:
                key2person.setdefault((e[0], e[1]), i)

    # collect appearances per person: (year, coord, name, occ)
    appearances = collections.defaultdict(list)
    n_rows = 0
    with open(RAW, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            did = row.get("dossierid", "")
            name = row.get("name", "")
            pid = key2person.get((did, name))
            if pid is None:
                continue
            co = coords.get(did)
            if not co:
                continue
            yr = row.get("year", "")
            if not re.fullmatch(r"\d{3,4}", yr or ""):
                continue
            occ = (row.get("occupation_norm") or "").strip()
            appearances[pid].append((int(yr), co, name.strip(), occ))
            n_rows += 1
    print(f"  {n_rows} located mentions across {len(appearances)} persons")

    # build movement rows for persons appearing at ≥2 distinct locations
    out_rows = []
    pseq = 0
    for pid, apps in appearances.items():
        # dedup identical (year, coord); keep a representative name/occ
        seen = {}
        for yr, co, name, occ in apps:
            k = (yr, co)
            if k not in seen or (occ and not seen[k][3]):
                seen[k] = (yr, co, name, occ)
        recs = sorted(seen.values(), key=lambda r: r[0])
        if len({co for _, co, _, _ in recs}) < MIN_LOCATIONS:
            continue
        pidstr = f"P{pseq:05d}"
        pseq += 1
        n = len(recs)
        for j, (yr, co, name, occ) in enumerate(recs):
            role = "start" if j == 0 else ("end" if j == n - 1 else "present")
            out_rows.append([pidstr, name, occ, co, yr, role])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["", "person_id", "name", "occupation", "coordinates",
                    "year", "event_role"])
        for idx, r in enumerate(out_rows):
            w.writerow([idx] + r)

    movers = len({r[0] for r in out_rows})
    print(f"\n→ {OUT}: {len(out_rows)} rows, {movers} persons with movement "
          f"(≥{MIN_LOCATIONS} locations)")
    # quick profile
    per = collections.Counter(r[0] for r in out_rows)
    dist = collections.Counter(per.values())
    print("  locations per person:", dict(sorted(dist.items())[:8]))


if __name__ == "__main__":
    main()
