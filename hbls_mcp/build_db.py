"""
build_db.py — convert persons_resolved.json (137k HBLS records) into hbls.db

Run once before starting the server:
    python build_db.py --json ../persons_resolved.json --db hbls.db
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA encoding     = 'UTF-8';

CREATE TABLE IF NOT EXISTS persons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    variants        TEXT,
    mention_count   INTEGER,
    dossier_count   INTEGER,
    year_from       INTEGER,
    year_to         INTEGER,
    dead_year       INTEGER,
    occupations     TEXT,
    titles          TEXT,
    families        TEXT,
    locations       TEXT,
    orgs            TEXT,
    hls_id          TEXT,
    hls_url         TEXT,
    hls_title       TEXT,
    hls_rel         TEXT,
    wd_qid          TEXT,
    wd_birth        INTEGER,
    wd_death        INTEGER,
    wd_occupations  TEXT,
    wd_gnd          TEXT,
    kin             TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_persons USING fts5(
    name, variants,
    content=persons, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS persons_ai AFTER INSERT ON persons BEGIN
    INSERT INTO fts_persons(rowid, name, variants)
        VALUES (new.id, new.name, new.variants);
END;
"""

# Columns in the INSERT statement (in order, id is always NULL for AUTOINCREMENT)
INSERT_COLS = [
    "name", "variants", "mention_count", "dossier_count",
    "year_from", "year_to", "dead_year", "occupations", "titles",
    "families", "locations", "orgs",
    "hls_id", "hls_url", "hls_title", "hls_rel",
    "wd_qid", "wd_birth", "wd_death", "wd_occupations", "wd_gnd",
    "kin",
]
N_INSERT_COLS = len(INSERT_COLS)  # 22
INSERT_SQL = (
    "INSERT INTO persons ("
    + ",".join(INSERT_COLS)
    + ") VALUES ("
    + ",".join(["?"] * N_INSERT_COLS)
    + ")"
)


def _j(val):
    return json.dumps(val, ensure_ascii=False) if val is not None else None


def _int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def init_db(path):
    con = sqlite3.connect(path)
    con.executescript(DDL)
    con.commit()
    return con


def parse(json_path, db_path, batch=1000):
    t0 = time.time()
    con = init_db(db_path)
    cur = con.cursor()

    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    n_total = len(data)
    rows = []
    n = 0

    print(f"Loading {n_total:,} records from {json_path}")
    print(f"INSERT cols: {N_INSERT_COLS}  |  SQL: {INSERT_SQL[:60]}...")

    for rec in data:
        # Extract year range from [from, to] list
        y = rec.get("y", [])
        yf = _int(y[0]) if isinstance(y, list) and len(y) > 0 else None
        yt = _int(y[1]) if isinstance(y, list) and len(y) > 1 else None

        # HLS sub-record
        h = rec.get("hls") if isinstance(rec.get("hls"), dict) else {}
        # Wikidata sub-record
        w = rec.get("wd") if isinstance(rec.get("wd"), dict) else {}

        rows.append((
            rec.get("n"),
            _j(rec.get("v")),
            rec.get("c"),
            rec.get("d"),
            yf, yt,
            rec.get("dead_year"),
            _j(rec.get("occ")),
            _j(rec.get("tit")),
            _j(rec.get("fam")),
            _j(rec.get("loc")),
            _j(rec.get("org")),
            h.get("id"), h.get("url"), h.get("t"), h.get("rel"),
            w.get("qid"), w.get("b"), w.get("d"),
            _j(w.get("occ")), w.get("gnd"),
            _j(rec.get("kin")),
        ))
        n += 1

        if n % batch == 0:
            cur.executemany(INSERT_SQL, rows)
            con.commit()
            rows = []
            elapsed = time.time() - t0
            rate = n / elapsed if elapsed > 0 else 1
            eta = (n_total - n) / rate
            print(f"  {n:,}/{n_total:,} … {elapsed:.0f}s (eta {eta:.0f}s)",
                  end="\r", flush=True)

    cur.executemany(INSERT_SQL, rows)
    con.commit()
    elapsed = time.time() - t0
    print(f"\nDone: {n:,} records in {elapsed:.1f}s → {db_path}")

    cur.execute("SELECT COUNT(*) FROM persons")
    count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM fts_persons")
    fts = cur.fetchone()[0]
    print(f"persons table: {count:,} rows  |  FTS index: {fts:,} rows")

    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="../persons_resolved.json")
    ap.add_argument("--db",   default="hbls.db")
    ap.add_argument("--batch", type=int, default=1000)
    args = ap.parse_args()
    json_p = Path(args.json).resolve()
    db_p   = Path(args.db).resolve()
    if not json_p.exists():
        sys.exit(f"ERROR: {json_p} not found")
    print(f"Building {db_p} from {json_p}")
    parse(str(json_p), str(db_p), args.batch)
