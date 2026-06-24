#!/usr/bin/env python3
"""
Improved extractor for the Historisch-Biographisches Lexikon der Schweiz (HBLS).

Why the original heuristic failed
---------------------------------
The scans are two-column pages. PyMuPDF's plain `get_text("text")` returns spans
in storage order, which interleaves the two columns and glues unrelated text
together. The original regex also treated the all-caps *running page header*
(printed at the top of every page) as an article start, producing one bogus
"article" per page, while missing the real headwords (which are letter-spaced
small/medium caps, not the same font as the header).

What this version does
----------------------
1. Column-aware reading order: spans are bucketed into a left and right column by
   their x-position, then read top-to-bottom, left column first.
2. Header / footer stripping: the bold ~9pt running header band (y < HEADER_Y)
   and the page-number footer are removed. The header words are kept separately
   and used to *validate* extraction (every detected headword on a page should
   sort alphabetically within the page's [first ... last] header bounds).
3. De-hyphenation: trailing soft hyphens (U+00AD) and "-" are rejoined.
4. Headword detection: a line is an article start when it begins with a
   letter-spaced run of capitals ("A N D W I L") that de-spaces to a real word,
   terminating at the first comma / period / "(". Citation acronyms ("BIG",
   "AHS") and numbered sub-entries ("1.", "2.") are rejected.
5. Numbered family members (the individual persons) are split out into an
   `entries` list as a best-effort convenience for downstream person-building.

Usage
-----
    python extract_hbls.py                 # extract all HBLS_band_*.pdf
    python extract_hbls.py --validate      # extract + print per-page QA stats
    python extract_hbls.py --pages 200-210 HBLS_band_01.pdf   # quick sample
"""
import argparse
import glob
import json
import os
import re
import sys
import unicodedata

import fitz  # PyMuPDF

# --- Layout constants (calibrated on HBLS_band_01..08, page width ~499pt) -----
HEADER_Y = 55      # y above which the running header lives
FOOTER_MARGIN = 22  # strip spans within this many pt of the page bottom
ROW_TOL = 3.0      # spans within this y-distance belong to the same visual line
SOURCE_DIR = "/Users/TH_1/Documents/HBLS"
PDF_GLOB = "HBLS_band_*.pdf"   # German volumes only (skip the French DHBS_tome_*)

# A leading run of capitals where letters may be separated by single spaces, e.g.
# "A N D W I L", "AN DR IO N", "ANDRIÉ". Capitals include German/French accents.
CAP = "A-ZÄÖÜÉÈÊÀÂÆŒÇ"
HEADWORD_RE = re.compile(rf"^\s*([{CAP}](?:[{CAP}]|\s(?=[{CAP}]))*)\s*([,.(]|—|$)")
ENUM_RE = re.compile(r"^\s*[—-]?\s*(\d{1,3})\s*\.\s+")  # "1. ", "— 2. "
ROMAN_RE = re.compile(r"^[IVXLCDM]+$")  # plate/volume numbers: XII, XVI, ...


def _despace_caps(s):
    """'A N D W I L' -> 'ANDWIL'; 'AN DR IO N' -> 'ANDRION'."""
    return re.sub(r"\s+", "", s)


def _looks_like_headword(token, raw_run, first_size, body_size):
    """Decide whether a leading caps run is a genuine article headword."""
    word = _despace_caps(token)
    if len(word) < 3 or len(word) > 28:
        return False
    if not any(c.isalpha() for c in word):
        return False
    if ROMAN_RE.match(word):                        # plate numbers XII, XVI, ...
        return False
    letterspaced = " " in raw_run.strip()           # true HBLS headword typography
    # Short solid-caps runs are citation acronyms (SGB, ADB, ULB), not headwords.
    if len(word) <= 3 and not letterspaced:
        return False
    smaller_font = first_size <= body_size - 0.3    # headwords set a touch smaller
    return letterspaced or smaller_font


def _page_columns(page):
    """Return (header_words, ordered_rows) for one page.

    ordered_rows is a list of dicts: {text, first_size, body_size} in reading
    order (left column top->bottom, then right column).
    """
    d = page.get_text("dict")
    W = page.rect.width
    H = page.rect.height
    mid = W / 2.0

    header_words = []
    # rows keyed by (column, y-bucket) -> list of (x0, size, text)
    buckets = {}
    for blk in d["blocks"]:
        if blk.get("type") != 0:
            continue
        for line in blk["lines"]:
            for s in line["spans"]:
                x0, y0, x1, y1 = s["bbox"]
                txt = s["text"]
                if not txt.strip():
                    continue
                if y0 < HEADER_Y:
                    # running header (bold ~9pt): keep words for validation
                    if "Bold" in s["font"] and not txt.strip().isdigit():
                        header_words.append(_despace_caps(txt.strip()))
                    continue
                if y0 > H - FOOTER_MARGIN:
                    continue
                col = 0 if (x0 + x1) / 2 < mid else 1
                key = (col, round(y0 / ROW_TOL))
                buckets.setdefault(key, []).append((x0, s["size"], txt))

    rows = []
    for (col, ybucket) in sorted(buckets):
        spans = sorted(buckets[(col, ybucket)], key=lambda r: r[0])
        text = "".join(t for _, _, t in spans)
        first_size = spans[0][1]
        rows.append({"col": col, "y": ybucket * ROW_TOL,
                     "text": text, "first_size": first_size})
    return header_words, rows


def _dehyphenate(rows):
    """Join row texts into a single string, healing line-end hyphenation."""
    out = []
    for r in rows:
        t = r["text"].rstrip()
        if t.endswith("\xad") or t.endswith("-"):
            out.append(("hyphen", t[:-1]))
        else:
            out.append(("space", t))
    pieces = []
    for i, (kind, t) in enumerate(out):
        pieces.append(t)
        if i < len(out) - 1:
            pieces.append("" if kind == "hyphen" else " ")
    return "".join(pieces)


def _body_size(rows):
    """Most common first-span size = body text size for this page."""
    from collections import Counter
    c = Counter(round(r["first_size"], 1) for r in rows)
    return c.most_common(1)[0][0] if c else 7.5


def _split_members(content):
    """Best-effort: split a family article into numbered member entries."""
    parts = re.split(r"(?:^|\s)[—-]?\s*(\d{1,3})\s*\.\s+(?=[A-ZÄÖÜ])", content)
    if len(parts) < 3:
        return []
    members = []
    # parts = [pre, num, body, num, body, ...]
    for i in range(1, len(parts) - 1, 2):
        num = parts[i]
        body = parts[i + 1].strip()
        if body:
            members.append({"n": int(num), "text": body[:600]})
    return members


def extract_articles_from_pdf(pdf_path, page_range=None, collect_qa=False):
    doc = fitz.open(pdf_path)
    abs_path = os.path.abspath(pdf_path)
    base = os.path.basename(pdf_path)

    articles = []
    qa = []
    current = None
    pages = range(len(doc)) if page_range is None else page_range

    for page_num in pages:
        page = doc.load_page(page_num)
        header_words, rows = _page_columns(page)
        if not rows:
            continue
        body_size = _body_size(rows)
        text = _dehyphenate(rows)
        page_no = page_num + 1

        # Re-split the healed text into lines for headword scanning. We keep the
        # mapping loose: scan the original rows, but emit healed text per row.
        page_headwords = []
        for r in rows:
            line = r["text"].strip()
            if ENUM_RE.match(line):
                if current is not None:
                    current["content"] += " " + line
                continue
            m = HEADWORD_RE.match(line)
            is_hw = False
            if m:
                raw_run = m.group(1)
                token = _despace_caps(raw_run)
                if _looks_like_headword(token, raw_run, r["first_size"], body_size):
                    is_hw = True
            if is_hw:
                if current is not None:
                    current["content"] = current["content"].strip()
                    articles.append(current)
                remainder = line[m.end(1):].lstrip(" ,.")
                current = {
                    "keyword": token,
                    "content": remainder,
                    "page": page_no,
                    "backlink": f"file://{abs_path}#page={page_no}",
                    "source_file": base,
                }
                page_headwords.append(token)
            else:
                if current is not None:
                    current["content"] += " " + line

        if collect_qa:
            qa.append({"page": page_no, "header": header_words,
                       "found": page_headwords})

    if current is not None:
        current["content"] = current["content"].strip()
        articles.append(current)

    # de-hyphenate accumulated content and split members
    for a in articles:
        a["content"] = re.sub(r"\xad\s*", "", a["content"])
        a["content"] = re.sub(r"\s+", " ", a["content"]).strip()
        members = _split_members(a["content"])
        if members:
            a["entries"] = members

    return (articles, qa) if collect_qa else articles


def _alpha_key(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalpha()).upper()


def validate(qa):
    """Check that found headwords sort within each page's header bounds."""
    pages = ok = oob = empty = total = 0
    for p in qa:
        pages += 1
        hdr = [_alpha_key(h) for h in p["header"] if _alpha_key(h)]
        found = p["found"]
        total += len(found)
        if not found:
            empty += 1
            continue
        if len(hdr) >= 1:
            lo, hi = min(hdr), max(hdr)
            for f in found:
                k = _alpha_key(f)
                if lo[:3] <= k[:3] <= hi[:3] or not hdr:
                    ok += 1
                else:
                    oob += 1
    print(f"  pages scanned        : {pages}")
    print(f"  headwords found      : {total}  (avg {total/max(pages,1):.1f}/page)")
    print(f"  within header bounds : {ok}")
    print(f"  out of bounds (susp.): {oob}")
    print(f"  pages w/ 0 headwords : {empty}")


def process_directory(out="hbls_articles.json"):
    pdfs = sorted(glob.glob(os.path.join(SOURCE_DIR, PDF_GLOB)))
    print(f"Found {len(pdfs)} HBLS volumes in {SOURCE_DIR}")
    alls = []
    for p in pdfs:
        print(f"Processing {os.path.basename(p)} ...", flush=True)
        arts = extract_articles_from_pdf(p)
        alls.extend(arts)
        print(f"  -> {len(arts)} articles")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(alls, f, ensure_ascii=False, indent=2)
    print(f"\nDone. {len(alls)} articles -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?", help="single PDF (default: all HBLS volumes)")
    ap.add_argument("--pages", help="page range like 200-210 (1-based)")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--out", default="hbls_articles.json")
    args = ap.parse_args()

    if args.pdf or args.pages:
        pdf = args.pdf or os.path.join(SOURCE_DIR, "HBLS_band_01.pdf")
        if not os.path.isabs(pdf) and not os.path.exists(pdf):
            pdf = os.path.join(SOURCE_DIR, pdf)
        rng = None
        if args.pages:
            a, b = args.pages.split("-")
            rng = range(int(a) - 1, int(b))
        arts, qa = extract_articles_from_pdf(pdf, page_range=rng, collect_qa=True)
        print(f"{len(arts)} articles from {os.path.basename(pdf)}"
              + (f" pages {args.pages}" if args.pages else ""))
        if args.validate:
            validate(qa)
        for a in arts[:8]:
            ents = f"  [{len(a.get('entries', []))} members]" if a.get("entries") else ""
            print(f"\n[{a['keyword']}] p{a['page']}{ents}\n  {a['content'][:240]}")
    else:
        process_directory(args.out)


if __name__ == "__main__":
    main()
