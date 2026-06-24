#!/usr/bin/env python3
"""
build_prices.py — property-price field ("Preiskarte", a meteorology-style
pressure map of house values over Basel).

Each property-transaction document (a purchase / sale / rent-purchase event)
carries a price in money spans. We convert every price to a common unit
(Pfund-equivalent), attach it to the dossier's location and year, then:

  • interpolate a smooth price *field* per decade (inverse-distance weighting
    of log-prices in a ±window) — the "pressure" surface;
  • list the most expensive individual houses per decade (the "highs").

Output prices.json:
  { decades:[…], grid:{cell_deg,bbox},
    field:[{d, lat, lon, p}],          # smoothed price surface, per decade
    top:[{d, lat, lon, p, dos, t}] }   # priciest houses, per decade
"""
import re
import json
import math
import collections
import lxml.etree as ET

XML = "hgb_full_26_05_29_05.xml"
OUT = "prices.json"

SALE = {"property-purchase", "sale", "rent-purchase"}
# currency → Pfund (lb). 1 lb = 20 ß = 240 d; Basel Gulden ≈ 1.6 lb (16th c.).
CUR = {"Pfund": 1.0, "Schilling": 0.05, "Pfennig": 1/240, "Denare": 1/240,
       "Stebler": 1/240, "Gulden": 1.6}
PRICE_MIN, PRICE_MAX = 5.0, 30000.0      # drop OCR garbage / trivial dues

CELL = 0.0010          # ~110 m grid
WINDOW = 20            # ±yr around a decade feeding its field
RADIUS = 0.0026        # ~290 m IDW search radius
DECADE_STEP = 10


def lv95_to_wgs84(E, N):
    e = (E - 2_600_000) / 1e6
    n = (N - 1_200_000) / 1e6
    lon = (2.6779094 + 4.728982*e + 0.791484*e*n + 0.1306*e*n**2 - 0.0436*e**3) * 100/36
    lat = (16.9023892 + 3.238272*n - 0.270978*e**2 - 0.002528*n**2
           - 0.0447*e**2*n - 0.0140*n**3) * 100/36
    return lat, lon


def to_pfund(norm):
    tot, any_ = 0.0, False
    for part in norm.split("|"):
        m = re.match(r"\s*([\d.]+)\s*([A-Za-zä]+)", part.strip())
        if m and m.group(2) in CUR:
            tot += float(m.group(1)) * CUR[m.group(2)]; any_ = True
    return tot if any_ else None


def extract():
    tx = []
    ctx = ET.iterparse(XML, events=("end",), tag="document", recover=True)
    for _, doc in ctx:
        meta = doc.find("metadata")
        if meta is None:
            doc.clear(); continue
        yr = meta.get("year", "")
        loc = meta.get("location", "")
        if not yr.isdigit() or "POINT" not in loc:
            doc.clear(); continue
        if not any(eg.get("class") in SALE for eg in doc.iter("eventGroup")):
            doc.clear(); continue
        vals = [to_pfund(sp.get("norm")) for sp in doc.iter("span")
                if sp.get("class") == "money" and sp.get("norm")]
        vals = [v for v in vals if v]
        if not vals:
            doc.clear(); continue
        price = max(vals)
        if not (PRICE_MIN <= price <= PRICE_MAX):
            doc.clear(); continue
        m = re.search(r"POINT\(([\d.]+)\s+([\d.]+)\)", loc)
        lat, lon = lv95_to_wgs84(float(m.group(1)), float(m.group(2)))
        tx.append({"y": int(yr), "lat": round(lat, 6), "lon": round(lon, 6),
                   "p": round(price), "dos": meta.get("dossierid", ""),
                   "t": (meta.get("text", "") or "")[:90]})
        doc.clear()
    return tx


def main():
    tx = extract()
    print(f"{len(tx)} priced transactions "
          f"({min(t['y'] for t in tx)}–{max(t['y'] for t in tx)})")

    lats = [t["lat"] for t in tx]; lons = [t["lon"] for t in tx]
    bbox = [min(lats), min(lons), max(lats), max(lons)]
    decades = list(range((min(t["y"] for t in tx)//10)*10,
                         (max(t["y"] for t in tx)//10)*10 + 1, DECADE_STEP))

    # grid cell centers covering the bbox
    cy0 = math.floor(bbox[0] / CELL); cy1 = math.ceil(bbox[2] / CELL)
    cx0 = math.floor(bbox[1] / CELL); cx1 = math.ceil(bbox[3] / CELL)

    field, top = [], []
    for d in decades:
        win = [t for t in tx if d - WINDOW <= t["y"] <= d + WINDOW]
        if not win:
            continue
        # IDW field (interpolate log-price)
        for cy in range(cy0, cy1 + 1):
            clat = (cy + 0.5) * CELL
            for cx in range(cx0, cx1 + 1):
                clon = (cx + 0.5) * CELL
                wsum = lsum = 0.0
                for t in win:
                    dd = math.hypot(t["lat"] - clat, (t["lon"] - clon) * 0.67)
                    if dd > RADIUS:
                        continue
                    w = 1.0 / (dd * dd + 1e-8)
                    wsum += w; lsum += w * math.log(t["p"])
                if wsum > 0:
                    field.append({"d": d, "lat": round(clat, 6),
                                  "lon": round(clon, 6),
                                  "p": round(math.exp(lsum / wsum))})
        # top houses this decade (dedup by dossier, keep max price)
        best = {}
        for t in win:
            k = t["dos"] or (t["lat"], t["lon"])
            if k not in best or t["p"] > best[k]["p"]:
                best[k] = t
        for t in sorted(best.values(), key=lambda x: -x["p"])[:15]:
            top.append({"d": d, "lat": t["lat"], "lon": t["lon"], "p": t["p"],
                        "dos": t["dos"], "t": t["t"]})

    out = {
        "decades": decades,
        "grid": {"cell_deg": CELL, "bbox": bbox},
        "pmin": min(t["p"] for t in tx), "pmax": max(t["p"] for t in tx),
        "field": field, "top": top,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    import os
    print(f"{OUT}: {os.path.getsize(OUT)/1024:.0f} KB, {len(field)} field cells, "
          f"{len(top)} top-house entries, {len(decades)} decades")
    # quick profile of the priciest houses overall
    print("\nMost expensive recorded houses:")
    for t in sorted(tx, key=lambda x: -x["p"])[:8]:
        print(f"  {t['p']:>6} lb  {t['y']}  {t['dos']}  {t['t'][:55]}")


if __name__ == "__main__":
    main()
