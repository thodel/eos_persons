"""
build_db.py — parse the HGB corpus XML into hgb.db (SQLite + FTS5)

Run once before starting the server:
    python build_db.py --street-dir ../../economies-of-space-automatically-annotated-data/street_data --db hgb.db
    python build_db.py --xml ../hgb_full_26_05_29_05.xml --db hgb.db     # legacy single file

The corpus is the street-split export of
DHBern/economies-of-space-automatically-annotated-data (~865 MB, 120 files);
hgb_corpus.iter_documents() streams it with low memory (~200 MB peak) and also
still reads the earlier single-file export.
"""

import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hgb_corpus  # noqa: E402


# ── Schema ────────────────────────────────────────────────────────────────────

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    dossier_id  TEXT,
    year        INTEGER,
    source      TEXT,
    location    TEXT,         -- WKT POINT(E N) or NULL
    language    TEXT,
    pages       INTEGER,
    text_raw    TEXT,         -- full document text from metadata/text
    checked     INTEGER,      -- 0/1
    street_id   TEXT,         -- HGB_1_005
    address     TEXT,         -- dossier address (collection metadata)
    dossiertype TEXT,         -- Liegenschaft, Strassenkörper, …
    page_url    TEXT          -- first Transkribus page image
);

CREATE TABLE IF NOT EXISTS spans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT REFERENCES documents(id),
    span_id     TEXT,
    parent_id   TEXT,         -- for nested spans
    class       TEXT,         -- per, loc, org, date, money, …
    element     TEXT,         -- reference, head, value, trigger
    text        TEXT,
    confidence  REAL,
    token_start INTEGER,
    token_end   INTEGER,
    numerus     TEXT,
    specificity TEXT,
    subclass    TEXT,
    norm        TEXT          -- normalised value (money, date)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT REFERENCES documents(id),
    event_id    TEXT,
    class       TEXT,
    token_start INTEGER,
    token_end   INTEGER,
    tense       TEXT,
    polarity    TEXT,
    modality    TEXT
);

-- Full-text search tables
CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
    id UNINDEXED, text_raw, content=documents, content_rowid=rowid
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_spans USING fts5(
    doc_id UNINDEXED, span_id UNINDEXED, class UNINDEXED,
    text, content=spans, content_rowid=rowid
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
    INSERT INTO fts_documents(rowid, id, text_raw) VALUES (new.rowid, new.id, new.text_raw);
END;
CREATE TRIGGER IF NOT EXISTS spans_ai AFTER INSERT ON spans BEGIN
    INSERT INTO fts_spans(rowid, doc_id, span_id, class, text)
    VALUES (new.rowid, new.doc_id, new.span_id, new.class, new.text);
END;
"""


def init_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(DDL)
    con.executescript(TRIGGERS)
    con.commit()
    return con


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse(db_path: str, batch: int = 500, street_dir=None, files=None):
    con = init_db(db_path)
    cur = con.cursor()

    doc_rows, span_rows, event_rows = [], [], []
    n_docs = 0
    t0 = time.time()

    for doc_el, meta in hgb_corpus.iter_documents(street_dir, files, progress=False):
        doc_id = meta["doc_id"]
        if not doc_id:
            continue

        doc_rows.append((
            doc_id,
            meta["dossier_id"],
            meta["year"],
            meta["source"],
            meta["location"],
            meta["language"],
            meta["n_pages"],
            meta["text"] or "",
            1 if meta["checked_by_gpt"] else 0,
            meta["street_id"],
            meta["address"],
            meta["dossiertype"],
            meta["pages"][0][1] if meta["pages"] else None,
        ))

        # spans
        for sp in doc_el.findall(".//spans/span"):
            parent = sp.getparent()
            parent_id = parent.get("id") if parent.tag == "span" else None
            span_rows.append((
                doc_id,
                sp.get("id"),
                parent_id,
                sp.get("class"),
                sp.get("element"),
                sp.get("text", ""),
                _float(sp.get("confidence")),
                _int(sp.get("start")),
                _int(sp.get("end")),
                sp.get("numerus"),
                sp.get("specificity"),
                sp.get("subclass"),
                sp.get("norm"),
            ))

        # events
        for ev in doc_el.findall(".//eventGroups/eventGroup"):
            event_rows.append((
                doc_id,
                ev.get("event_id"),
                ev.get("class"),
                _int(ev.get("start")),
                _int(ev.get("end")),
                ev.get("tense"),
                ev.get("polarity"),
                ev.get("modality"),
            ))

        n_docs += 1

        if n_docs % batch == 0:
            _flush(cur, doc_rows, span_rows, event_rows)
            con.commit()
            doc_rows, span_rows, event_rows = [], [], []
            elapsed = time.time() - t0
            print(f"  {n_docs:,} documents … {elapsed:.0f}s", end="\r", flush=True)

    _flush(cur, doc_rows, span_rows, event_rows)
    con.commit()

    elapsed = time.time() - t0
    print(f"\nDone: {n_docs:,} documents in {elapsed:.1f}s → {db_path}")
    con.close()


def _flush(cur, docs, spans, events):
    cur.executemany(
        "INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", docs
    )
    cur.executemany(
        "INSERT INTO spans(doc_id,span_id,parent_id,class,element,text,"
        "confidence,token_start,token_end,numerus,specificity,subclass,norm) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?)", spans
    )
    cur.executemany(
        "INSERT INTO events(doc_id,event_id,class,token_start,token_end,"
        "tense,polarity,modality) VALUES (?,?,?,?,?,?,?,?)", events
    )


def _int(v):
    try: return int(v)
    except: return None

def _float(v):
    try: return float(v)
    except: return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default=None,
                    help="legacy single-file export (hgb_full_*.xml)")
    ap.add_argument("--street-dir", default=None,
                    help="street_data/ of the DHBern data repo (default: auto-detect)")
    ap.add_argument("--db",  default="hgb.db")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()
    files = [args.xml] if args.xml else None
    src = args.xml or hgb_corpus.street_dir(args.street_dir) or "<no corpus found>"
    print(f"Parsing {src} → {args.db}")
    parse(args.db, args.batch, street_dir=args.street_dir, files=files)
