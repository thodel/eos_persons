# HBLS extraction

Extracts articles and clean person records from the **Historisch-Biographisches
Lexikon der Schweiz** (HBLS, 8 volumes, 1921–1934) OCR scans, and builds the data
file behind the static **HBLS** tab (`../hbls.html`).

Source PDFs live in `/Users/TH_1/Documents/HBLS/` (`HBLS_band_01..08.pdf`; the
French `DHBS_tome_*` volumes are intentionally skipped).

## Pipeline

```bash
python3 -m venv venv && ./venv/bin/pip install pymupdf

# 1. articles (column-aware, header-stripped, de-hyphenated)
./venv/bin/python extract_hbls.py            # -> hbls_articles.json
./venv/bin/python extract_hbls.py --pages 400-402 --validate HBLS_band_01.pdf

# 2. clean, link-ready person records (font-aware small-caps name parsing)
./venv/bin/python build_persons.py           # -> hbls_persons.json / .csv

# 3. compact data for the static web tab (articles + joined persons)
./venv/bin/python make_web_data.py           # -> ../hbls_web.json

# 4. linking & deduplication (see DEDUP_PLAN.md)
python3 ../link_hbls_hls.py                   # -> ../link_hbls_hls_candidates.csv
./venv/bin/python basel_subset.py            # -> hbls_persons_basel.{csv,json}

# 5. merge the identity clusters into one record per person (Stage 4)
python3 ../build_identity_clusters.py         # -> ../identity_clusters.{json,csv}
python3 ../build_merged_persons.py            # -> ../merged_persons.{json,csv}
```

- `DEDUP_PLAN.md` — staged plan to dedupe people across HBLS / HLS / EOS-HGB.
- `link_hbls_hls.py` matched 2,339 HBLS persons to HLS bios (2,201 unambiguous).
- `basel_subset.py` isolates the 4,932 Basel-connected persons (first link slice).

`extract_lexicon.py` is the original prototype, kept for reference; `extract_hbls.py`
supersedes it (see git history / the report for why the prototype's heuristic failed).

## Outputs

| file | rows | note |
|---|---|---|
| `hbls_articles.json` | 18,244 | one per headword; full text, page, backlink (gitignored, regenerable) |
| `hbls_persons.json/.csv` | 29,208 | per-person: surname+given+life years+provenance (gitignored) |
| `../hbls_web.json` | 18,244 | trimmed index for `hbls.html` (tracked, 8 MB) |

## Person record schema

```json
{ "id": "hbls:1:51", "name": "Hans Ulrich Abegg", "given": "Hans Ulrich",
  "surname": "Abegg", "keyword": "ABEGG", "member_n": 9,
  "birth_year": 1584, "death_year": 1622, "floruit_years": null,
  "bio": "...", "volume": 1, "page": 70,
  "backlink": "file://…/HBLS_band_01.pdf#page=70" }
```

Designed to feed the existing fuzzy matcher (`../link_hls.py`, keyed on
given + surname + life-span overlap) for linking to HLS and the EOS person data.

## Known limitations
- Multi-line given names occasionally truncate.
- Small residue (<0.3%) of OCR-split headwords (e.g. `DOLF`); harmless downstream.
- Given-name OCR noise in small caps (`Joh`, `Wal`); life years are the stronger join key.
