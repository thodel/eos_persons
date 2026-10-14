#!/usr/bin/env python3
"""
build_account_places.py — geo-reference the srbas account taxonomy.

The only structured place information in the Basel Jahrrechnungen is the
account hierarchy: the Ämter/Vogteien branches (bs_AmtLiestalEinnahmen,
bs_MuttenzAusgaben, …) are named after the villages and bailiwicks whose
income and expenditure they book. Every booking inherits its account's place,
which gives the ~45 rural accounts a point on the map even though the booking
texts carry no placeName markup.

Labels are split into place names ("Füllinsdorf, Lupsingen, Ziefen" -> 3) and
each is geocoded with Nominatim (OpenStreetMap): Switzerland first, then
Alsace/Baden (countrycodes fr,de). Nominatim returns the Wikidata id of the
feature where OSM carries it (extratags), so most rows get a QID for free; the
GeoNames id is filled in a second, optional pass from Wikidata (P1566) that is
skipped silently when the endpoint rate-limits (--geonames).

`status`: `auto` when the first hit's name equals the query and it is a
settlement or castle, `review` otherwise. Rows set to `manual` by hand survive
a re-run.

    python3 build_account_places.py              # -> srbas_account_places.csv (tracked)
    python3 build_account_places.py --geonames   # also fill geonames from Wikidata
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TEI = "{http://www.tei-c.org/ns/1.0}"
XMLID = "{http://www.w3.org/XML/1998/namespace}id"
UA = {"User-Agent": "eos-persons srbas account geocoder (Uni Bern, "
                    "https://github.com/thodel/eos_persons)"}
OUT = os.path.join(HERE, "srbas_account_places.csv")
COLS = ["account_id", "label", "place", "osm", "wikidata", "matched_name",
        "kind", "geonames", "lat", "lon", "country", "status"]

NOMINATIM = "https://nominatim.openstreetmap.org/search"
WIKIDATA = "https://www.wikidata.org/w/api.php"
# label fragments that are not place names
NOISE = re.compile(r"\b(Amt|Vogtei|Wittum|Hardvogt|zu|und|Zehntenrechte)\b|Zins-")
RENAME = {"Offenburger": "Offenburg"}
AEMTER = ("bs_ÄmterEinnahmen", "bs_ÄmterAusgaben")
SETTLEMENT = {"city", "town", "village", "hamlet", "municipality", "suburb",
              "administrative", "locality", "isolated_dwelling"}
CASTLE = {"castle", "ruins", "fort", "manor", "historic"}


def account_labels():
    """(account_id, label) for every account below the two Ämter branches."""
    root = ET.parse(os.path.join(HERE, "tei", "o_srbas.konten.xml")).getroot()
    for branch in root.iter(TEI + "category"):
        if branch.get(XMLID) not in AEMTER:
            continue
        for cat in branch.iter(TEI + "category"):
            xid = cat.get(XMLID) or ""
            name = cat.find("./" + TEI + "catDesc/" + TEI + "name")
            if name is None or xid in AEMTER or xid.startswith("bs_Stadtviertel"):
                continue
            yield xid, " ".join(name.itertext()).strip()


def split_places(label):
    for part in re.split(r"[,/]| und ", label):
        part = " ".join(NOISE.sub(" ", part).split()).strip(" .-")
        if part:
            yield RENAME.get(part, part)


def get_json(url, params, retries=4):
    url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == retries - 1:
                raise
            time.sleep(10 * (2 ** i))


def nominatim(place, countrycodes):
    hits = get_json(NOMINATIM, {
        "q": place, "format": "jsonv2", "countrycodes": countrycodes,
        "extratags": 1, "limit": 8, "accept-language": "de"})
    time.sleep(1.1)                       # Nominatim usage policy: max 1 req/s
    out = []
    for h in hits:
        kind = h.get("addresstype") or h.get("type") or ""
        klass = 0 if kind in SETTLEMENT else 1 if (kind in CASTLE or h.get("class") == "historic") else 2
        out.append({
            "osm": f"{h.get('osm_type', '')[:1].upper()}{h.get('osm_id', '')}",
            "wikidata": (h.get("extratags") or {}).get("wikidata", ""),
            "matched_name": h.get("name", ""), "kind": kind,
            "lat": round(float(h["lat"]), 5), "lon": round(float(h["lon"]), 5),
            "country": h["display_name"].rsplit(",", 1)[-1].strip(),
            "_klass": klass,
            "_exact": (h.get("name", "").lower() == place.lower()),
        })
    out.sort(key=lambda r: (not r["_exact"], r["_klass"]))
    return out


def lookup(place):
    hits = nominatim(place, "ch")
    if not any(h["_exact"] for h in hits):
        hits = [h for h in nominatim(place, "fr,de") if h["_exact"]] + hits
    return hits


def geonames_for(qid):
    ents = get_json(WIKIDATA, {"action": "wbgetentities", "ids": qid,
                               "props": "claims", "format": "json"})["entities"]
    for c in ents.get(qid, {}).get("claims", {}).get("P1566", []):
        if c["mainsnak"].get("datavalue"):
            return c["mainsnak"]["datavalue"]["value"]
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geonames", action="store_true",
                    help="fill the geonames column from Wikidata P1566")
    a = ap.parse_args()
    keep, prev_geonames = {}, {}
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT, encoding="utf-8")):
            if r["status"] == "manual":
                keep[(r["account_id"], r["place"])] = r
            if r.get("wikidata") and r.get("geonames"):
                prev_geonames[r["wikidata"]] = r["geonames"]
    cache, rows = {}, []
    for xid, label in account_labels():
        for place in split_places(label):
            key = (xid, place)
            if key in keep:
                rows.append(keep[key])
                continue
            if place not in cache:
                try:
                    cache[place] = lookup(place)
                except Exception as e:      # network hiccup: leave the row for review
                    print(f"  {place}: lookup failed ({e})", file=sys.stderr)
                    cache[place] = []
            hits = cache[place]
            row = {c: "" for c in COLS}
            row.update({"account_id": xid, "label": label, "place": place, "status": "review"})
            if hits:
                best = hits[0]
                row.update({k: v for k, v in best.items() if not k.startswith("_")})
                row["geonames"] = prev_geonames.get(best["wikidata"], "")
                if best["_exact"] and best["_klass"] < 2:
                    row["status"] = "auto"
            rows.append(row)
            print(f"{xid:45s} {place:14s} {row['wikidata']:10s} {row['kind']:14s} "
                  f"{row['country']:12s} {row['status']}", file=sys.stderr)
    if a.geonames:
        for row in rows:
            if row["wikidata"] and not row["geonames"]:
                try:
                    row["geonames"] = geonames_for(row["wikidata"])
                    prev_geonames[row["wikidata"]] = row["geonames"]
                    time.sleep(1.0)
                except Exception as e:
                    print(f"  geonames for {row['wikidata']}: skipped ({e})", file=sys.stderr)
                    break
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    n_auto = sum(r["status"] == "auto" for r in rows)
    print(f"{len(rows)} account/place rows, {n_auto} auto-resolved -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
