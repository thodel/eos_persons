#!/usr/bin/env python3
"""
harvest_srbas.py — download the TEI sources of the *Jahrrechnungen der Stadt
Basel 1535–1610* (GAMS Graz, collection context:srbas).

GAMS is a Fedora-Commons repository; every object exposes its datastreams
over plain HTTPS, no API key:

    https://gams.uni-graz.at/o:srbas.<year>/TEI_SOURCE                 TEI/XML
    https://gams.uni-graz.at/archive/objects/o:srbas.<year>/datastreams/RDF/content
    https://gams.uni-graz.at/o:srbas.konten/TEI_SOURCE                 account taxonomy

One object per account year (o:srbas.1535 … o:srbas.1610, 76 files, ~42 MB),
plus o:srbas.konten with the 165-node account taxonomy. The edition carries NO
person or place markup (persName/placeName/rs/term are absent from every
body), so the downstream scripts work on the booking texts themselves.

    python3 harvest_srbas.py              # -> tei/o_srbas.<year>.xml (gitignored)
    python3 harvest_srbas.py --from 1600 --to 1610
"""
import argparse
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TEI_URL = "https://gams.uni-graz.at/{pid}/TEI_SOURCE"
UA = {"User-Agent": "eos-persons srbas harvester (Uni Bern, "
                    "https://github.com/thodel/eos_persons)"}
YEAR_MIN, YEAR_MAX = 1535, 1610


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == retries - 1:
                raise
        except urllib.error.URLError:
            if i == retries - 1:
                raise
        time.sleep(2 ** i)


def pid_path(outdir, pid):
    return os.path.join(outdir, pid.replace(":", "_") + ".xml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "tei"))
    ap.add_argument("--from", dest="y0", type=int, default=YEAR_MIN)
    ap.add_argument("--to", dest="y1", type=int, default=YEAR_MAX)
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pids = ["o:srbas.konten"] + [f"o:srbas.{y}" for y in range(a.y0, a.y1 + 1)]
    got = skipped = missing = 0
    for pid in pids:
        dst = pid_path(a.out, pid)
        if os.path.exists(dst) and not a.force:
            skipped += 1
            continue
        data = fetch(TEI_URL.format(pid=pid))
        if data is None:
            print(f"{pid}: 404", file=sys.stderr)
            missing += 1
            continue
        with open(dst, "wb") as f:
            f.write(data)
        got += 1
        print(f"{pid}: {len(data):,} bytes", file=sys.stderr)
    print(f"downloaded {got}, kept {skipped}, missing {missing} -> {a.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
