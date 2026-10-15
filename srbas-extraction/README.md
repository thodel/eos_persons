# Jahrrechnungen der Stadt Basel 1535–1610 (srbas)

Cross-linking the **Basel city accounts** (Jahrrechnungen, ed. Susanna Burghartz
& Georg Vogeler, Basel/Graz 2015) with the Economies-of-Space persons and places.
The edition lives on GAMS Graz under `context:srbas`:
<https://gams.uni-graz.at/context:srbas>.

## Source and access

GAMS is a Fedora-Commons repository; every object exposes its datastreams over
plain HTTPS, no API key, no bulk dump:

| what | URL |
|---|---|
| TEI of one account year | `https://gams.uni-graz.at/o:srbas.<year>/TEI_SOURCE` |
| RDF (bookkeeping ontology) | `https://gams.uni-graz.at/archive/objects/o:srbas.<year>/datastreams/RDF/content` |
| account taxonomy (165 nodes) | `https://gams.uni-graz.at/o:srbas.konten/TEI_SOURCE` |
| list of all objects | `https://gams.uni-graz.at/context:srbas?mode=chrono` |
| query objects (SPARQL result XML) | `https://gams.uni-graz.at/archive/objects/query:srbas.fulltext/methods/sdef:Query/getXML?params=…` |

76 objects, `o:srbas.1535` … `o:srbas.1610`, one per account year, 42 MB of TEI.
Citable fragment URIs: `https://gams.uni-graz.at/o:srbas.<year>#<xml:id of the booking>`.
The dissemination package (XSLT/ODD) is on GitHub: <https://github.com/GVogeler/srbas>.
Check the licence on the GAMS object before redistributing the texts.

**Finding that shapes everything below:** the TEI has *no* person or place
markup. `persName`, `placeName`, `rs`, `name`, `term` are absent from every
body (the only two `persName` are the editors in the header). What the edition
models is bookkeeping: account (`xml:id="bs_<Konto>-<n>"`), booking
(`ana="#bk_entry"`), subtotal (`#bk_total`) and parsed amounts
(`<measure type="currency" unit="lb|ß|d" quantity=…>`). Persons and places
therefore have to be recovered from the booking texts and from the account
hierarchy.

| | |
|---|---|
| bookings (`#bk_entry`) | 78,728 |
| subtotals | 9,950 |
| words | ≈ 805,000 |
| bookings with a name mention (heuristic) | 4,653 |
| distinct name profiles (given + surname, normalised) | 3,287 |

## Pipeline

```bash
python3 harvest_srbas.py            # -> tei/o_srbas.<year>.xml + o_srbas.konten.xml (gitignored)
python3 extract_entries.py          # -> srbas_entries.jsonl   one booking per line (gitignored)
python3 extract_names.py            # -> srbas_name_mentions.csv   (tracked)
python3 build_account_places.py     # -> srbas_account_places.csv  (tracked, Wikidata)

# HGB side
python3 ../build_hgb_street_persons.py   # -> ../hgb_street_persons.json (gitignored, 51 MB)
python3 ../link_srbas_hgb.py             # -> ../link_srbas_hgb_candidates.csv
                                         #    ../link_srbas_hgb_street_candidates.csv
python3 ../make_srbas_web.py                # -> ../srbas_web.json for ../jahrrechnungen.html
python3 -m pytest ../tests/test_srbas_names.py ../tests/test_street_resolution.py
```

### Persons: `extract_names.py`

Lexical heuristic: a known early-modern given name (lexicon in the script,
case-insensitive because the transcription writes `hans` and `Hans` alike),
optionally a second given name, then a capitalised surname token (particle
surnames like *Im Kilchzimmer*, *Zum Rappen* are kept whole), optionally an
origin (*von Oberwilen*). Feast-day genitives (*Johannis Baptistae*), saints,
inn names and the place tokens of the account taxonomy are excluded.

Inflection is normalised because the accounts write names in the oblique case
("empfangen von *Jacoben Gebharten*"): given-name dative `-en/-n` is stripped
always, surname genitive `-s` always, surname dative `-en` only in a dative
context (after *von, dem, herrn, meister, geben, …* or after a dative given
name). Both raw and normalised forms are kept so the linker can try either.

Columns of `srbas_name_mentions.csv`: `year, pid, entry_id, account, raw,
given_raw, given_norm, surname_raw, surname_norm, origin, uri`.
Precision is good on the common patterns (see `tests/test_srbas_names.py`);
recall is limited to names whose given name is in the lexicon — extend
`GIVEN_NAMES` when you see gaps. Names of persons outside Basel (Strasbourg
messengers, imperial envoys) are extracted too; `origin` helps to filter.

### Places: `build_account_places.py`

The only structured place information is the account hierarchy: the
Ämter/Vogteien branches (*Amt Liestal*, *Muttenz*, *Vogtei Riehen*, …) book
the income and expenditure of the rural bailiwicks, so every booking in them
inherits a place. The script splits the ~45 account labels into place names,
looks each one up in Wikidata (label match, coordinates, country CH/FR/DE,
settlement preferred, GeoNames id via P1566) and writes
`srbas_account_places.csv` with a `status` column: `auto` for an unambiguous
hit, `review` otherwise. Rows set to `manual` by hand survive a re-run.
Wikidata rate-limits shared proxies hard; the script backs off on 429.

Places *inside* booking texts (journeys, messengers, origins) are not
extracted here; `origin` in the name mentions is a first handle on them.

## Linking to the HGB: `../link_srbas_hgb.py`

Name mentions are aggregated into profiles (`given_norm + surname_norm` →
years, bookings, accounts) and matched against two HGB targets with the
`link_hls` name functions (surname `ratio` ≥ 0.85 on the best of the raw /
normalised / de-inflected forms, `given_ratio` ≥ 0.74 on canonicalised given
names) and a temporal check (srbas years inside the HGB mention span ± 15
years; no post-mortem grace, a person paid in a Jahrrechnung is alive):

1. **corpus** — `persons_resolved.json`, the city-wide HGB name index also used
   by `link_hbls_hgb.py`. Broad recall, homonyms across the whole city.
2. **street** — `hgb_street_persons.json`, built by
   `../build_hgb_street_persons.py` from the DHBern release
   *Economies of Space: Full Annotated Dataset*
   (<https://github.com/DHBern/economies-of-space-automatically-annotated-data>,
   used read-only; clone it next to this repo or pass `--src`). Mentions are
   resolved into persons *per street* with the same rules as the corpus-wide
   index: token-subset merge inside a dossier, 80-year lifespan bins and
   death splits, canonical-key merge across the dossiers of the street, and
   the Kölner-Phonetik pass of `dedupe_corpus.py` with the street itself as
   the context anchor. One record per resolved person with canonical name,
   merged variants, mention years, `dead_year`, dossiers, LV95 point,
   occupations (normalised where the release has it), event roles and a
   `merged_by` trace. Nothing merges across streets. A hit here places the
   Jahrrechnung name on the map and keeps homonyms on different streets
   apart — the cleaner target for the actual cross-link.

Both outputs are candidate tables for review, one row per (srbas profile,
HGB person) pair, sorted by score, with `n_candidates` for ambiguity.
`srbas_uri` points at the first booking; the full list of bookings for a
profile is in `srbas_name_mentions.csv`.

## Web page: `../jahrrechnungen.html`

`make_srbas_web.py` compacts everything above into `srbas_web.json` (one
record per name profile with up to four cited bookings spread over the years,
a text excerpt of ≤ 140 characters each, and the three best candidates per
target; street candidates carry WGS84 points converted from LV95). The page
shows the street-level hits and the bailiwick accounts on a map, filters by
target, score, ambiguity and mention count, and links every booking to its
GAMS fragment. The excerpts are short quotations for verification; the full
texts stay with the edition.

## Known limitations

- No gold standard yet: the scores rank, they do not decide. Start with
  `n_candidates == 1` and `srbas_mentions ≥ 3`.
- Given-name lexicon recall; dative stripping can over-strip genuine `-en`
  surnames (*Hagen*) — the raw form is kept and also compared.
- Account places are bailiwicks, not the places named in the texts.
- The street-level resolution never merges across streets by design; a
  person with property on two streets is two records, and only the
  corpus-wide index joins them. Different canonical given-name sequences
  (Hans vs. Hans Heinrich) never merge across dossiers, as in the HGB rules.
