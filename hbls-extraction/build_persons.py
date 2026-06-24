#!/usr/bin/env python3
"""
build_persons.py — turn HBLS lexicon articles into clean, link-ready person records.

Input  : the HBLS PDFs (re-read with font information; the flat JSON from
         extract_hbls.py loses the small-caps name typography we need here).
Output : hbls_persons.json / hbls_persons.csv

Design
------
HBLS biographical articles are family articles: a bold headword (the surname /
family name) followed by numbered members, each printed as

    1. JACOB , Sohn von Nicolas, 1608-82, Hauptmann ...
       ^^ enum  ^^^^^ small-caps given name      ^^^ life dates / bio

Two facts from the scans drive the parser:
  * The given name is set in SMALL CAPS (font size ~4-5pt) while body text is
    7.5pt and the enumerator "1." is body size. So a "N." is a real member only
    when the next glyphs are small-caps — this rejects centuries ("18. Jahrh."),
    day-dates ("25. I.") and section numbers that the naive splitter mistook for
    members.
  * The small-caps baseline is offset ~2pt from the body line, so spans must be
    clustered into visual lines by a y-tolerance, then ordered by x, to keep a
    name next to its enumerator.

Single-person biographies (no numbering) are handled too: the given name is the
small-caps run immediately after the headword.

Each record carries surname + given + birth/death/floruit years + provenance, so
the existing fuzzy matcher (link_hls.py: given+surname+life-span) can link these
to the eos_persons / HGB dataset in a later stage.
"""
import csv
import glob
import json
import os
import re
import unicodedata

import fitz  # PyMuPDF

from extract_hbls import (HEADER_Y, FOOTER_MARGIN, SOURCE_DIR, PDF_GLOB,
                          HEADWORD_RE, ENUM_RE, ROMAN_RE,
                          _despace_caps, _looks_like_headword)

# Bibliographic sigla used throughout HBLS citations — never article headwords.
# (A closed vocabulary; the recurring offenders that survive the alphabetical
# gate because they sort near real surnames.)
SIGLA = {
    "SKL", "LLH", "SZGL", "ADB", "GLS", "HBLS", "HBLSV", "DHBS", "DHV", "NZZ",
    "ASI", "ASHR", "SGB", "QSGN", "ZSR", "BWG", "FRB", "AHVB", "OBG", "SBBV",
    "AHS", "BIG", "MDR", "ASMZ", "UBL", "ULB", "QSG", "ASG", "BSG", "JSG",
    "MDG", "MHVG", "ZGO", "ZSG", "ASA", "BIA", "RHV", "MAGW", "SBB", "SAC",
}
# A headword candidate followed by a volume/page locator is a citation, not an
# article: "SKL III, p. 42", "ADB XLV", "NZZ 1880, Nr. 3".
CIT_LEAD_RE = re.compile(r"^(?:[IVXLCDM]{1,6}[,.\s]|[Pp]\.?\s*\d|S\.\s*\d|"
                         r"\d{1,4}\s*[,.]|pag\.|Bd\.|Nr\.|Sp\.)")

LINE_TOL = 4.0        # spans within this y-distance form one visual line
SMALLCAP_MAX = 6.5    # font size at/below which a span is small-caps (names)
BODY_MIN = 7.0        # body text size floor

# --- year patterns ----------------------------------------------------------
Y = r"(1[0-9]{3})"
DATE = r"(?:\d{1,2}\.?\s*[ivxlcIVXLC]+\.?\s*)?"   # optional "25. xi." day prefix
# life-span ranges incl. abbreviated end year: "1608-82" -> 1608-1682
RANGE_RE = re.compile(rf"\b{Y}\s*[-–]\s*(\d{{2,4}})\b")
BIRTH_RE = re.compile(rf"\*\s*{DATE}{Y}")
# OCR renders the dagger (†) variously as f / j / + at a word start before a date
DEATH_RE = re.compile(rf"(?:†|\+|\b[fj])\s*{DATE}{Y}")
YEAR_RE = re.compile(rf"\b{Y}\b")

# Words that mark a NON-person (place / topic) article, checked on the lead text
PLACE_RE = re.compile(r"\b(Kt\.|Bez\.|Gem\b|Gemeinde|Pfarrei|Dorf|Weiler|"
                      r"Einwohner|Seelen|politische|Kirchgemeinde|S\. GLS|"
                      r"liegt|Fluss|Berg|Tal|See\b)")


def _alpha_key(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalpha()).upper()


def _in_header_bounds(tok, header):
    """A real headword sorts within the page's running-header [first..last]
    bounds. Citation sigla (SKL, ADB) and OCR garbage fall outside and are
    rejected — this stops a siglum from hijacking a real family's members."""
    keys = [_alpha_key(h) for h in header]
    keys = [k for k in keys if len(k) >= 3]
    if not keys:
        return True                     # no usable header -> can't judge, accept
    lo, hi = min(keys)[:2], max(keys)[:2]
    k = _alpha_key(tok)[:2]
    return lo <= k <= hi


def _plausible_given(g):
    """Reject OCR/topic-article noise masquerading as a given name.

    Genuine HBLS given names are 1-3 capitalised word(s), no digits. Topic
    articles (Kulturkampf, Konferenzen ...) are set in small print and leak
    garbage like '1871' or 'VII.1870dadurchwurde...'."""
    g = g.strip()
    if not g:
        return True                      # empty is fine (record kept on years)
    if any(c.isdigit() for c in g):
        return False
    if ROMAN_RE.match(_despace_caps(g)):  # 'VII', 'XII'
        return False
    toks = g.split()
    if len(toks) > 3 or len(g) > 26:
        return False
    return bool(re.match(r"^[A-ZÄÖÜÉÈÊÀÂÆŒÇ]", g))


def _name_from_spans(spans):
    """Reconstruct a given name from a run of small-caps spans.

    Each name word is OCR'd as a size~5 capital initial + size~4 remainder, e.g.
    'J'(5) + 'acob'(4) -> 'Jacob'; 'J'(5)'ean'(4) 'J'(5)'acques'(4) ->
    'Jean Jacques'. A new word starts at each capital-initial span.
    """
    out = []
    for x, sz, txt in spans:
        t = re.sub(r"\s+", "", txt)            # de-letterspace within the span
        if not t:
            continue
        if t[0].isupper() and (len(t) == 1 or sz >= 4.6):
            out.append(t)                      # new word (capital initial)
        elif out:
            out[-1] += t                       # continuation of current word
        else:
            out.append(t)
    name = " ".join(out)
    name = re.sub(r"[^\wÄÖÜäöüÉÈÊÀÂÆŒÇéèêàâç' .-]", "", name).strip(" .,-")
    return name


def page_lines(page):
    """Return (header_words, lines). Each line: dict(col,y,spans) where spans is
    a list of (x, size, text) sorted left-to-right."""
    d = page.get_text("dict")
    W, H = page.rect.width, page.rect.height
    mid = W / 2.0
    header = []
    raw = {0: [], 1: []}
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                x0, y0, x1, y1 = s["bbox"]
                txt = s["text"]
                if not txt.strip():
                    continue
                if y0 < HEADER_Y:
                    if "Bold" in s["font"] and not txt.strip().isdigit():
                        header.append(_despace_caps(txt.strip()))
                    continue
                if y0 > H - FOOTER_MARGIN:
                    continue
                col = 0 if (x0 + x1) / 2 < mid else 1
                raw[col].append((y0, x0, s["size"], txt))

    lines = []
    for col in (0, 1):
        spans = sorted(raw[col], key=lambda r: (r[0], r[1]))
        clusters = []
        for y0, x0, sz, txt in spans:
            for c in clusters:
                if abs(y0 - c["y"]) <= LINE_TOL:
                    c["spans"].append((x0, sz, txt))
                    break
            else:
                clusters.append({"y": y0, "spans": [(x0, sz, txt)]})
        for c in clusters:
            c["spans"].sort(key=lambda r: r[0])
        clusters.sort(key=lambda c: c["y"])
        for c in clusters:
            lines.append({"col": col, "y": c["y"], "spans": c["spans"]})
    return header, lines


def _flush(buf):
    """Collapse accumulated (size,text) bio spans into clean text + years."""
    text = "".join(t for _, t in buf)
    text = re.sub(r"\xad\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.-—;")
    return text


def _extract_years(text):
    b = de = None
    fl = []
    m = BIRTH_RE.search(text)
    if m:
        b = int(m.group(1))
    m = DEATH_RE.search(text)
    if m:
        de = int(m.group(1))
    if b is None and de is None:
        m = RANGE_RE.search(text)
        if m:
            b = int(m.group(1))
            end = m.group(2)
            if len(end) == 4:
                de = int(end)
            else:  # abbreviated: "1608-82" -> 1682, carry/borrow the century
                de = (b // 100) * 100 + int(end)
                if de < b:
                    de += 100
            if not (b <= de <= b + 110):   # sanity: implausible life span
                de = None
    if b is None and de is None:
        fl = sorted({int(y) for y in YEAR_RE.findall(text)})
    return b, de, (fl if fl else None)


def parse_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    base = os.path.basename(pdf_path)
    vol = re.search(r"band_(\d+)", base)
    vol = int(vol.group(1)) if vol else None
    abs_path = os.path.abspath(pdf_path)

    persons = []
    article = None          # current family/headword article
    person = None           # current person record being built
    bio_buf = []            # (size, text) for current person's bio

    def close_person():
        nonlocal person, bio_buf
        if person is not None:
            person["bio"] = _flush(bio_buf)
            b, de, fl = _extract_years(person["bio"])
            # given-name dates sometimes precede the name; also scan a short head
            person["birth_year"] = b
            person["death_year"] = de
            person["floruit_years"] = fl
            keep = (_plausible_given(person["given"])
                    and (person["given"] or b or de))
            if keep:
                person["id"] = "hbls:%s:%d" % (vol, len(persons) + 1)
                persons.append(person)
        person = None
        bio_buf = []

    for pno in range(len(doc)):
        page = doc.load_page(pno)
        header, lines = page_lines(page)
        body = 7.5
        page_no = pno + 1
        for ln in lines:
            spans = ln["spans"]
            text = "".join(t for _, _, t in spans).strip()
            if not text:
                continue

            # 1) headword? -> start a new article (family / surname)
            m = HEADWORD_RE.match(text)
            if m:
                tok = _despace_caps(m.group(1))
                lead = text[m.end(1):].lstrip(" ,.")
                if _looks_like_headword(tok, m.group(1), spans[0][1], body):
                    # Reject citation sigla / OCR noise masquerading as headwords:
                    #  - alphabetically out of the page's header bounds, or
                    #  - a known bibliographic siglum (incl. siglum+volume merges), or
                    #  - followed by a volume/page locator instead of a name/prose.
                    bare = re.sub(r"[IVXLCDM]+$", "", tok)  # strip trailing volume
                    if (not _in_header_bounds(tok, header)
                            or tok in SIGLA or bare in SIGLA
                            or CIT_LEAD_RE.match(lead)):
                        if person is not None:
                            bio_buf.append((body, text))
                        continue
                if _looks_like_headword(tok, m.group(1), spans[0][1], body):
                    close_person()
                    lead = text[m.end(1):].lstrip(" ,.")
                    is_place = bool(PLACE_RE.search(lead[:80]))
                    article = {"keyword": tok, "page": page_no,
                               "is_place": is_place}
                    # single-person bio: small-caps given right after headword
                    gn_spans = [s for s in spans[1:]
                                if s[1] <= SMALLCAP_MAX and s[2].strip()]
                    if not is_place and gn_spans:
                        person = _new_person(article, vol, base, abs_path,
                                             page_no, None,
                                             _name_from_spans(gn_spans))
                        bio_buf = [(body, lead)]
                    continue

            if article is None or article.get("is_place"):
                continue

            # 2) walk spans: detect "N." enumerators followed by small-caps name
            i = 0
            n = len(spans)
            while i < n:
                x, sz, txt = spans[i]
                em = re.search(r"(?:^|[—–-]|\.)\s*(\d{1,3})\s*\.\s*$", txt)
                nxt = spans[i + 1] if i + 1 < n else None
                if (em and nxt and nxt[1] <= SMALLCAP_MAX
                        and re.match(r"\s*[A-ZÄÖÜÉÈÆŒÇ]", nxt[2])):
                    # text before the enumerator belongs to the previous person
                    pre = txt[:em.start()]
                    if pre.strip():
                        bio_buf.append((sz, pre))
                    close_person()
                    # gather the small-caps name run
                    j = i + 1
                    name_spans = []
                    while j < n and spans[j][1] <= SMALLCAP_MAX:
                        name_spans.append(spans[j])
                        j += 1
                    person = _new_person(article, vol, base, abs_path, page_no,
                                         int(em.group(1)),
                                         _name_from_spans(name_spans))
                    bio_buf = []
                    i = j
                    continue
                if person is not None:
                    bio_buf.append((sz, txt))
                i += 1

    close_person()
    return persons


def _new_person(article, vol, base, abs_path, page_no, n, given):
    surname = article["keyword"].title()
    given = (given or "").strip()
    full = f"{given} {surname}".strip()
    pid = "hbls:%s:%s:%d:%s" % (vol, article["keyword"], page_no, n if n else 0)
    return {
        "id": pid,
        "name": full,
        "given": given,
        "surname": surname,
        "keyword": article["keyword"],
        "member_n": n,
        "birth_year": None,
        "death_year": None,
        "floruit_years": None,
        "bio": "",
        "volume": vol,
        "page": page_no,
        "source_file": base,
        "backlink": f"file://{abs_path}#page={page_no}",
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--out", default="hbls_persons")
    args = ap.parse_args()

    pdfs = ([args.pdf] if args.pdf
            else sorted(glob.glob(os.path.join(SOURCE_DIR, PDF_GLOB))))
    allp = []
    for p in pdfs:
        if not os.path.isabs(p) and not os.path.exists(p):
            p = os.path.join(SOURCE_DIR, p)
        print(f"Parsing {os.path.basename(p)} ...", flush=True)
        pp = parse_pdf(p)
        allp.extend(pp)
        print(f"  -> {len(pp)} persons")

    with open(args.out + ".json", "w", encoding="utf-8") as f:
        json.dump(allp, f, ensure_ascii=False, indent=2)
    cols = ["id", "name", "given", "surname", "keyword", "member_n",
            "birth_year", "death_year", "floruit_years", "volume", "page",
            "source_file", "backlink", "bio"]
    with open(args.out + ".csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in allp:
            row = dict(p)
            if row.get("floruit_years"):
                row["floruit_years"] = "-".join(map(str, row["floruit_years"]))
            row["bio"] = row["bio"][:500]
            w.writerow(row)
    print(f"\nDone. {len(allp)} persons -> {args.out}.json / .csv")


if __name__ == "__main__":
    main()
