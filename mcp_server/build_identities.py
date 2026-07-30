"""
build_identities.py — load merged_persons.json (Stage 4) into hgb.db

The HGB tables come from an ~800 MB XML parse that takes ~10 minutes; the
cross-corpus identities are regenerated on every pipeline run. So they get
their own build step that attaches to the existing database rather than
forcing a full rebuild:

    python build_identities.py --json ../merged_persons.json --db hgb.db

Safe to re-run: the identity tables are dropped and rebuilt each time, and no
HGB table is touched.

Each row is one real person, resolved across HBLS (printed lexicon 1921–34),
HLS (its online successor) and the HGB land register, with GND/Wikidata
authority ids and a sources[] array carrying provenance back to each corpus.
See ../hbls-extraction/DEDUP_PLAN.md.
"""

import argparse
import json
import sqlite3
import sys
import time

DDL = """
DROP TABLE IF EXISTS identities;
DROP TABLE IF EXISTS fts_identities;

CREATE TABLE identities (
    id            TEXT PRIMARY KEY,   -- "person:00050"
    name          TEXT,
    surname       TEXT,
    given         TEXT,
    birth_year    INTEGER,
    death_year    INTEGER,
    gender        TEXT,
    status        TEXT,               -- "merged" | "review"
    conflicts     TEXT,               -- JSON array; empty for merged
    corpora       TEXT,               -- "hbls+hgb+hls"
    n_corpora     INTEGER,
    gnd           TEXT,
    wikidata      TEXT,
    viaf          TEXT,
    hls_id        TEXT,
    occupations   TEXT,               -- JSON array
    places        TEXT,               -- JSON object {birth,death,activity}
    publications  TEXT,               -- JSON array [{title,year}]
    n_publications INTEGER,
    dossiers      TEXT,               -- JSON array of HGB dossier ids
    n_dossiers    INTEGER,
    mention_from  INTEGER,
    mention_to    INTEGER,
    bio           TEXT,
    sources       TEXT                -- JSON array [{corpus,id,url,…}]
);

CREATE INDEX idx_ident_gnd  ON identities(gnd);
CREATE INDEX idx_ident_wd   ON identities(wikidata);
CREATE INDEX idx_ident_hls  ON identities(hls_id);
CREATE INDEX idx_ident_life ON identities(birth_year, death_year);

CREATE VIRTUAL TABLE fts_identities USING fts5(
    id UNINDEXED, name, occupations, places, bio, publications
);
"""

COLS = ("id name surname given birth_year death_year gender status conflicts "
        "corpora n_corpora gnd wikidata viaf hls_id occupations places "
        "publications n_publications dossiers n_dossiers mention_from "
        "mention_to bio sources").split()


def first(seq):
    return seq[0] if seq else None


def to_row(p):
    auth = p.get("authority") or {}
    places = p.get("places") or {}
    span = p.get("mention_span") or [None, None]
    hls = [s["id"] for s in p.get("sources", []) if s["corpus"] == "hls"]
    pubs = p.get("publications") or []
    doss = p.get("dossiers") or []
    return {
        "id": p["id"],
        "name": p.get("name") or "",
        "surname": p.get("surname"),
        "given": p.get("given"),
        "birth_year": p.get("birth_year"),
        "death_year": p.get("death_year"),
        "gender": p.get("gender"),
        "status": p.get("status"),
        "conflicts": json.dumps(p.get("conflicts") or [], ensure_ascii=False),
        "corpora": "+".join(p.get("corpora") or []),
        "n_corpora": len(p.get("corpora") or []),
        "gnd": first(auth.get("gnd") or []),
        "wikidata": first(auth.get("wikidata") or []),
        "viaf": auth.get("viaf"),
        "hls_id": first(hls),
        "occupations": json.dumps(p.get("occupations") or [], ensure_ascii=False),
        "places": json.dumps(places, ensure_ascii=False),
        "publications": json.dumps(pubs, ensure_ascii=False),
        "n_publications": len(pubs),
        "dossiers": json.dumps(doss, ensure_ascii=False),
        "n_dossiers": len(doss),
        "mention_from": span[0],
        "mention_to": span[1],
        "bio": p.get("bio"),
        "sources": json.dumps(p.get("sources") or [], ensure_ascii=False),
    }


def fts_text(row, person):
    """Flatten the searchable fields — plain words, not the JSON envelopes."""
    occ = " ".join(person.get("occupations") or [])
    pl = " ".join(v for vals in (person.get("places") or {}).values() for v in vals)
    pub = " ".join(x.get("title", "") for x in (person.get("publications") or []))
    return occ, pl, (row["bio"] or ""), pub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="../merged_persons.json")
    ap.add_argument("--db", default="hgb.db")
    ap.add_argument("--include-review", action="store_true",
                    help="also load clusters flagged for review (default: merged only)")
    args = ap.parse_args()

    t0 = time.time()
    with open(args.json, encoding="utf-8") as f:
        people = json.load(f)
    if not args.include_review:
        people = [p for p in people if p.get("status") == "merged"]
    print(f"{len(people):,} identities from {args.json}")

    con = sqlite3.connect(args.db)
    con.executescript(DDL)
    ins = f"INSERT INTO identities({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for p in people:
        row = to_row(p)
        con.execute(ins, [row[c] for c in COLS])
        occ, pl, bio, pub = fts_text(row, p)
        con.execute(
            "INSERT INTO fts_identities(id, name, occupations, places, bio, publications)"
            " VALUES(?,?,?,?,?,?)", (row["id"], row["name"], occ, pl, bio, pub))
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
    ngnd = con.execute("SELECT COUNT(*) FROM identities WHERE gnd IS NOT NULL").fetchone()[0]
    ntri = con.execute("SELECT COUNT(*) FROM identities WHERE n_corpora = 3").fetchone()[0]
    nhgb = con.execute("SELECT COUNT(*) FROM identities WHERE corpora LIKE '%hgb%'").fetchone()[0]
    con.close()
    print(f"  {n:,} rows, {ngnd:,} with a GND id, {ntri} in all three corpora, "
          f"{nhgb:,} attested in the HGB")
    print(f"  done in {time.time() - t0:.1f}s -> {args.db}")


if __name__ == "__main__":
    sys.exit(main())
