#!/usr/bin/env python3
"""
hgb_corpus.py — one streaming reader for the HGB annotated corpus.

The corpus is published, split per street, in
    https://github.com/DHBern/economies-of-space-automatically-annotated-data
        street_data/street_HGB_1_001.xml … street_HGB_1_229.xml

Layout of a street file (BeNASch XML):

    <corpus>
      <series id="HGB_1_005" name="St. Alban-Graben">            ← street
        <collection id="HGB_1_005_014" variant_names="…">          ← dossier / property
          <metadata>
            <dossiertype>Liegenschaft</dossiertype>
            <location>POINT(2611586.47 1267028.73)</location>      ← LV95
            <address>St. Alban-Graben 2</address>
            <dossier_history>…</dossier_history>
          </metadata>
          <document id="…">
            <metadata>
              <street_id/> <dossier_id/> <year/> <source/> <language/>
              <checked_by_gpt/> <text>…</text> <pages><page nr="3">URL</page></pages>
            </metadata>
            <text><token token_id="0">…</token>…</text>
            <spans>…</spans> <relations>…</relations> <eventGroups>…</eventGroups>
          </document>
        </collection>
      </series>
    </corpus>

The earlier single-file export (hgb_full_*.xml) carried the same information
as *attributes* on <document><metadata …/> (dossierid, year, location, text …).
`doc_meta()` reads either shape, so every build script can simply call

    for doc, meta in hgb_corpus.iter_documents():
        …

and get a uniform `meta` dict:

    doc_id, street_id, street_name, dossier_id, year (int|None), source,
    language, checked_by_gpt (bool), text, pages [(nr, url)], n_pages,
    location ("POINT(E N)" LV95 or None), address, dossiertype

Location of the street files, in order of precedence:
    --street-dir / `street_dir=` argument,
    $HGB_STREET_DIR,
    ../economies-of-space-automatically-annotated-data/street_data (sibling checkout),
    ./street_data
A single legacy file can be passed instead via $HGB_XML / `files=[…]`.
"""
import glob
import os
import re
import sys

from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_REPO = "economies-of-space-automatically-annotated-data"

_CANDIDATE_DIRS = (
    os.environ.get("HGB_STREET_DIR"),
    os.path.join(HERE, "..", DATA_REPO, "street_data"),
    os.path.join(HERE, DATA_REPO, "street_data"),
    os.path.join(HERE, "street_data"),
)

POINT_RE = re.compile(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)")


def street_dir(explicit=None):
    """Directory holding street_HGB_*.xml, or None."""
    for d in (explicit,) + _CANDIDATE_DIRS:
        if d and os.path.isdir(d) and glob.glob(os.path.join(d, "street_*.xml")):
            return os.path.abspath(d)
    return None


def corpus_files(street_dir_=None, files=None):
    """Ordered list of XML files that make up the corpus."""
    if files:
        return list(files)
    if os.environ.get("HGB_XML") and not street_dir_:
        return [os.environ["HGB_XML"]]
    d = street_dir(street_dir_)
    if d is None:
        sys.exit("hgb_corpus: no street_data directory found — clone "
                 f"DHBern/{DATA_REPO} next to this repo or set $HGB_STREET_DIR")
    return sorted(glob.glob(os.path.join(d, "street_*.xml")))


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _collection_meta(coll):
    """dossier-level metadata from a <collection> element (new layout)."""
    out = {"location": None, "address": None, "dossiertype": None,
           "variant_names": None, "valid_from": None, "valid_to": None,
           "predecessors": [], "successors": []}
    if coll is None:
        return out
    out["variant_names"] = coll.get("variant_names") or None
    md = coll.find("metadata")
    if md is None:
        return out
    loc = (md.findtext("location") or "").strip()
    out["location"] = loc if POINT_RE.search(loc) else None
    out["address"] = (md.findtext("address") or "").strip() or None
    out["dossiertype"] = (md.findtext("dossiertype") or "").strip() or None
    froms, tos = [], []
    for vp in md.iter("validity_period"):
        f, t = _int(vp.get("from")), _int(vp.get("to"))
        if f: froms.append(f)
        if t: tos.append(t)
    out["valid_from"] = min(froms) if froms else None
    out["valid_to"] = max(tos) if tos else None
    out["predecessors"] = [e.get("id") for e in md.iter("predecessor") if e.get("id")]
    out["successors"] = [e.get("id") for e in md.iter("successor") if e.get("id")]
    return out


def doc_meta(doc, coll_meta=None):
    """Uniform metadata dict for a <document>, old or new layout."""
    md = doc.find("metadata")
    m = {"doc_id": doc.get("id")}
    if md is None:
        return None
    if md.get("year") is not None or md.get("dossierid") is not None:
        # legacy single-file export: everything is an attribute
        m.update({
            "street_id": (md.get("dossierid") or "")[:9] or None,
            "street_name": None,
            "dossier_id": md.get("dossierid"),
            "year": _int(md.get("year")),
            "source": md.get("source"),
            "language": md.get("language"),
            "checked_by_gpt": md.get("checked_by_gpt") == "true",
            "text": md.get("text") or "",
            "pages": [],
            "n_pages": _int(md.get("pages")),
            "location": md.get("location") if POINT_RE.search(md.get("location") or "") else None,
            "address": None,
            "dossiertype": md.get("dossiertype"),
        })
        return m
    pages = []
    for pg in md.iter("page"):
        pages.append((_int(pg.get("nr")), (pg.text or "").strip()))
    coll = doc.getparent() if coll_meta is None else None
    cm = coll_meta if coll_meta is not None else _collection_meta(
        coll if coll is not None and coll.tag == "collection" else None)
    series = None
    if coll is not None and coll.getparent() is not None and coll.getparent().tag == "series":
        series = coll.getparent()
    m.update({
        "street_id": (md.findtext("street_id") or "").strip() or None,
        "street_name": series.get("name") if series is not None else cm.get("street_name"),
        "dossier_id": (md.findtext("dossier_id") or "").strip() or None,
        "year": _int(md.findtext("year")),
        "source": (md.findtext("source") or "").strip() or None,
        "language": (md.findtext("language") or "").strip() or None,
        "checked_by_gpt": (md.findtext("checked_by_gpt") or "").strip() == "true",
        "text": (md.findtext("text") or ""),
        "pages": pages,
        "n_pages": len(pages) or None,
        "location": cm.get("location"),
        "address": cm.get("address"),
        "dossiertype": cm.get("dossiertype"),
    })
    return m


def iter_documents(street_dir_=None, files=None, progress=True, every=5000):
    """Yield (document_element, meta) for every document in the corpus.

    The element is cleared after the consumer's turn, so don't keep it.
    """
    n = 0
    for path in corpus_files(street_dir_, files):
        coll_meta = None
        coll_id = None
        ctx = etree.iterparse(path, events=("end",), tag=("document", "collection"),
                              recover=True, huge_tree=True)
        for _, el in ctx:
            if el.tag == "collection":
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
                coll_meta, coll_id = None, None
                continue
            parent = el.getparent()
            if parent is not None and parent.tag == "collection":
                if coll_id != parent.get("id"):
                    coll_meta = _collection_meta(parent)
                    series = parent.getparent()
                    coll_meta["street_name"] = (series.get("name")
                                                if series is not None and series.tag == "series"
                                                else None)
                    coll_id = parent.get("id")
                meta = doc_meta(el, coll_meta)
                if meta is not None:
                    meta["street_name"] = coll_meta.get("street_name")
            else:
                meta = doc_meta(el)
            if meta is not None:
                yield el, meta
            n += 1
            if progress and n % every == 0:
                print(f"  …{n:,} documents ({os.path.basename(path)})",
                      file=sys.stderr, flush=True)
            el.clear()
            while el.getprevious() is not None and el.getprevious().tag == "document":
                del el.getparent()[0]
    if progress:
        print(f"  {n:,} documents read", file=sys.stderr, flush=True)


def iter_dossiers(street_dir_=None, files=None):
    """Yield one dict per <collection> (dossier) with its metadata and document
    count / year range — without touching the documents' annotations."""
    for path in corpus_files(street_dir_, files):
        ctx = etree.iterparse(path, events=("end",), tag="collection",
                              recover=True, huge_tree=True)
        for _, coll in ctx:
            cm = _collection_meta(coll)
            series = coll.getparent()
            years, sources = [], set()
            n_docs = 0
            for d in coll.findall("document"):
                n_docs += 1
                md = d.find("metadata")
                if md is not None:
                    y = _int(md.findtext("year"))
                    if y:
                        years.append(y)
                    s = (md.findtext("source") or "").strip()
                    if s:
                        sources.add(s)
            yield {
                "dossier_id": coll.get("id"),
                "street_id": series.get("id") if series is not None else None,
                "street_name": series.get("name") if series is not None else None,
                "n_docs": n_docs,
                "year_min": min(years) if years else None,
                "year_max": max(years) if years else None,
                "sources": sorted(sources),
                **cm,
            }
            coll.clear()
            while coll.getprevious() is not None:
                del coll.getparent()[0]


def parse_point(loc):
    """'POINT(E N)' → (E, N) floats, or (None, None)."""
    m = POINT_RE.search(loc or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def lv95_to_wgs84(E, N):
    """Swiss LV95 → WGS84 (lat, lon); swisstopo approximation, ~1 m accuracy."""
    e = (E - 2_600_000) / 1e6
    n = (N - 1_200_000) / 1e6
    lon = (2.6779094 + 4.728982 * e + 0.791484 * e * n + 0.1306 * e * n ** 2
           - 0.0436 * e ** 3) * 100 / 36
    lat = (16.9023892 + 3.238272 * n - 0.270978 * e ** 2 - 0.002528 * n ** 2
           - 0.0447 * e ** 2 * n - 0.0140 * n ** 3) * 100 / 36
    return lat, lon


if __name__ == "__main__":
    import collections
    files = corpus_files()
    print(f"{len(files)} street files in {os.path.dirname(files[0])}")
    n = 0
    years = collections.Counter()
    for doc, meta in iter_documents(files=files[:1]):
        n += 1
        if n <= 2:
            print({k: (v[:60] if isinstance(v, str) else v) for k, v in meta.items()})
        years[meta["year"] is not None] += 1
    print(n, "documents in first file;", dict(years))
