#!/usr/bin/env python3
"""
build_flowfield.py — aggregate all person movements into a meteorology-style
flow field (Bewegungsfeld).

Every consecutive hop in a person's trajectory (location A → location B, from
movements.csv) is a displacement vector. Binning the hops' origins into a
spatial grid and averaging their directions yields a wind-map-like field: each
cell carries the prevailing direction of relocation, how coherent that flow is,
and how much movement passes through it — sliceable by decade.

Output flowfield.json:
  { grid:{cell_deg,lat0,lon0}, decades:[…],
    cells:[{d, cx, cy, lat, lon, ang, coh, n}] }   # d = decade or "all"
"""
import re
import csv
import json
import math
import collections

MOVEMENTS = "movements.csv"
OUT = "flowfield.json"
CELL_DEG = 0.0012        # ~130 m cells over Basel's old town
MIN_HOPS = 3             # ignore near-empty cells


def lv95_to_wgs84(E, N):
    e = (E - 2_600_000) / 1e6
    n = (N - 1_200_000) / 1e6
    lon = (2.6779094 + 4.728982*e + 0.791484*e*n + 0.1306*e*n**2 - 0.0436*e**3) * 100/36
    lat = (16.9023892 + 3.238272*n - 0.270978*e**2 - 0.002528*n**2
           - 0.0447*e**2*n - 0.0140*n**3) * 100/36
    return lat, lon


def parse_point(s):
    m = re.search(r"POINT\s*\(\s*([\d.]+)\s+([\d.]+)\s*\)", s or "")
    if not m:
        return None
    return lv95_to_wgs84(float(m.group(1)), float(m.group(2)))


def main():
    # gather each person's (year, lat, lon) appearances
    traj = collections.defaultdict(list)
    with open(MOVEMENTS, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pt = parse_point(row.get("coordinates", ""))
            yr = row.get("year", "")
            if not pt or not re.fullmatch(r"\d{3,4}", yr or ""):
                continue
            traj[row["person_id"]].append((int(yr), pt[0], pt[1]))

    # build hops: consecutive, distinct locations
    # accumulate per (decade, cell): vector sum of unit displacement + count
    acc = collections.defaultdict(lambda: [0.0, 0.0, 0])   # sx, sy, n
    lats, lons = [], []
    n_hops = 0
    for pid, pts in traj.items():
        pts.sort()
        for (y0, la0, lo0), (y1, la1, lo1) in zip(pts, pts[1:]):
            if abs(la1 - la0) < 1e-9 and abs(lo1 - lo0) < 1e-9:
                continue                                   # no move
            # planar displacement (lon scaled by latitude)
            dx = (lo1 - lo0) * math.cos(math.radians(la0))
            dy = (la1 - la0)
            d = math.hypot(dx, dy)
            if d == 0:
                continue
            ux, uy = dx / d, dy / d
            decade = (y0 // 10) * 10
            cx = math.floor(lo0 / CELL_DEG)
            cy = math.floor(la0 / CELL_DEG)
            for key in ((decade, cx, cy), ("all", cx, cy)):
                a = acc[key]
                a[0] += ux; a[1] += uy; a[2] += 1
            lats.append(la0); lons.append(lo0)
            n_hops += 1

    cells = []
    decset = set()
    for (d, cx, cy), (sx, sy, n) in acc.items():
        if n < MIN_HOPS:
            continue
        ang = math.degrees(math.atan2(sy, sx))             # 0=E, 90=N
        coh = math.hypot(sx, sy) / n                        # 0..1 resultant
        cells.append({
            "d": d, "cx": cx, "cy": cy,
            "lat": round((cy + 0.5) * CELL_DEG, 6),
            "lon": round((cx + 0.5) * CELL_DEG, 6),
            "ang": round(ang, 1), "coh": round(coh, 3), "n": n,
        })
        if d != "all":
            decset.add(d)

    out = {
        "grid": {"cell_deg": CELL_DEG,
                 "bbox": [min(lats), min(lons), max(lats), max(lons)] if lats else None},
        "decades": sorted(decset),
        "cells": cells,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)

    import os
    nall = sum(1 for c in cells if c["d"] == "all")
    print(f"{n_hops} hops from {len(traj)} persons")
    print(f"{OUT}: {os.path.getsize(OUT)/1024:.0f} KB, {len(cells)} cell-entries "
          f"({nall} in the all-period field), {len(decset)} decades "
          f"{min(decset)}–{max(decset)}")


if __name__ == "__main__":
    main()
