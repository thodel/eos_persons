#!/usr/bin/env python3
"""
extract_entries.py — flatten the srbas TEI files into one booking per line.

The TEI marks every booking as <p ana="#bk_entry"> (or <item>) and every
subtotal as ana="#bk_total"; the xml:id encodes the account
(bs_<Konto>-<n>, keyed to o:srbas.konten). The amounts are already parsed by
the edition (<measure type="currency" unit="lb|ß|d" quantity=…>), so we sum
them per booking in Pfund (1 lb = 20 ß = 240 d) for later use.

    python3 extract_entries.py            # -> srbas_entries.jsonl (gitignored)

Each line:
  {"year", "pid", "entry_id", "account", "kind", "text", "amount_lb", "uri"}
`uri` is the citable GAMS fragment, e.g. https://gams.uni-graz.at/o:srbas.1535#bs_Strafen-1
"""
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
TEI = "{http://www.tei-c.org/ns/1.0}"
XMLID = "{http://www.w3.org/XML/1998/namespace}id"
UNIT_LB = {"lb": 1.0, "ß": 1 / 20, "ß-w": 1 / 20, "d": 1 / 240}


def amount_lb(el):
    total, seen = 0.0, False
    for m in el.iter(TEI + "measure"):
        if m.get("type") != "currency":
            continue
        try:
            q = float(m.get("quantity", ""))
        except ValueError:
            continue
        f = UNIT_LB.get(m.get("unit", ""))
        if f is None:
            continue
        total += q * f
        seen = True
    return round(total, 4) if seen else None


def iter_entries(path):
    pid = os.path.basename(path)[:-4].replace("o_srbas.", "o:srbas.")
    year = int(pid.rsplit(".", 1)[1])
    root = ET.parse(path).getroot()
    for el in root.iter():
        ana = el.get("ana") or ""
        if ana not in ("#bk_entry", "#bk_total"):
            continue
        text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        if not text:
            continue
        xid = el.get(XMLID) or ""
        m = re.match(r"(bs_[^-]+)", xid)
        yield {
            "year": year, "pid": pid, "entry_id": xid,
            "account": m.group(1) if m else "",
            "kind": ana[1:], "text": text, "amount_lb": amount_lb(el),
            "uri": f"https://gams.uni-graz.at/{pid}#{xid}" if xid
                   else f"https://gams.uni-graz.at/{pid}",
        }


def main():
    tei_dir = os.path.join(HERE, "tei")
    out = os.path.join(HERE, "srbas_entries.jsonl")
    files = sorted(f for f in glob.glob(os.path.join(tei_dir, "o_srbas.*.xml"))
                   if re.search(r"o_srbas\.\d{4}\.xml$", f))
    if not files:
        sys.exit(f"no TEI files in {tei_dir}; run harvest_srbas.py first")
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        for f in files:
            for row in iter_entries(f):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
    print(f"{len(files)} files, {n} bookings -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
