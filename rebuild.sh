#!/usr/bin/env bash
# rebuild.sh — the whole person pipeline in the order the data were built in.
#
#   ./rebuild.sh                 # everything, from the corpus
#   ./rebuild.sh data            # from build_data.py on (persons.csv exists)
#   ./rebuild.sh links report    # only the stages links … report
#   ./rebuild.sh --list          # show the stages and their steps
#
# Stages, in order:
#   extract     corpus → persons.csv, documents.csv, dossiers.csv; street-level index
#   data        persons.csv → persons_resolved.json (raw), guild_data.json
#   links       HLS candidates → links → Wikidata → kinship
#   dedupe      the four name-based passes
#   spelling    link_bli_hgb.py ⇄ dedupe_spelling.py until nothing merges
#   families    family graph, roles, movements, flow field, dossier map
#   identities  HBLS / HLS / GND / Wikidata identities (Stage 1–4)
#   srbas       Jahrrechnungen candidates
#   report      BLI report on the final index, tests
#
# Inputs it expects next to this repository: the DHBern street corpus and
# basler-liegenschaften-interaktiv (or .bli_cache/, see link_bli_hgb.py --fetch).
# With the private HLS export ($HLS_ARTICLES or private_inputs/hls_articles.csv)
# the HLS steps use it and the text-mining steps run; without it they fall back
# to hls_bios_wikidata.csv / hls_family_links.csv and skip the mining.
set -euo pipefail
cd "$(dirname "$0")"

STAGES=(extract data links dedupe spelling families identities srbas report)

step() { echo; echo "### $*"; "$@"; }

stage_extract() {
  step python3 extract_persons.py
  step python3 build_hgb_street_persons.py
}

stage_data() {
  step python3 build_data.py
}

stage_links() {
  step python3 link_hls.py
  step python3 apply_hls_links.py
  step python3 enrich_wikidata.py
  rm -f /tmp/wd_kin.json                      # link_wikidata_kin's cache is per QID set
  step python3 link_wikidata_kin.py
}

stage_dedupe() {
  step python3 dedupe_persons.py
  step python3 dedupe_corpus.py --apply
  step python3 dedupe_offices.py --apply
  step python3 dedupe_rare_surnames.py --apply
}

stage_spelling() {
  local n round
  for round in 1 2 3 4 5 6 7 8; do
    step python3 link_bli_hgb.py
    n=$(python3 dedupe_spelling.py | sed -n 's/^merge clusters: \([0-9]*\).*/\1/p')
    echo "round $round: $n clusters to merge"
    [ "$n" = "0" ] && return 0
    step python3 dedupe_spelling.py --apply
  done
  echo "dedupe_spelling did not settle in 8 rounds" >&2
  return 1
}

stage_families() {
  step python3 build_families.py
  step python3 extract_genealogy.py           # skip themselves without the private export
  step python3 extract_spouses.py
  step python3 link_wikidata_kin.py
  step python3 link_hls_families.py
  step python3 build_roles.py
  step python3 build_movements.py
  step python3 build_flowfield.py
  step python3 build_dossiers_geo.py
}

stage_identities() {
  # candidates on the deduplicated index: Stage 3 looks persons up by name#year
  step python3 link_hls.py
  if [ ! -f hbls-extraction/hbls_persons.json ]; then
    (cd hbls-extraction && step python3 rebuild_hbls_persons.py)
    git checkout -q -- hbls-extraction/hbls_id_map.csv   # the map belongs to authority_edges.csv
  fi
  step python3 link_hbls_hgb.py --all
  [ -f hbls-extraction/gnd_enrichment.json ] || step python3 gnd_enrich.py --no-publications
  step python3 build_identity_clusters.py
  step python3 build_merged_persons.py
  step python3 make_persons_web.py
}

stage_srbas() {
  if [ ! -f srbas-extraction/srbas_entries.jsonl ]; then
    (cd srbas-extraction && step python3 harvest_srbas.py && step python3 extract_entries.py)
  fi
  step python3 link_srbas_hgb.py
  step python3 make_srbas_web.py
}

stage_report() {
  step python3 link_bli_hgb.py
  step python3 -m pytest tests mcp_server/tests -q
}

if [ "${1:-}" = "--list" ]; then
  for s in "${STAGES[@]}"; do
    echo "$s:"
    declare -f "stage_$s" | grep -o 'python3 [^;)]*' | sed 's/^/    /'
  done
  exit 0
fi

first=${1:-extract}
last=${2:-report}
pos() { local i; for i in "${!STAGES[@]}"; do [ "${STAGES[$i]}" = "$1" ] && { echo "$i"; return 0; }; done; return 1; }
a=$(pos "$first") || { echo "unknown stage '$first' — one of: ${STAGES[*]}" >&2; exit 2; }
b=$(pos "$last")  || { echo "unknown stage '$last' — one of: ${STAGES[*]}" >&2; exit 2; }
[ "$a" -le "$b" ] || { echo "stage '$last' comes before '$first'" >&2; exit 2; }
for i in $(seq "$a" "$b"); do
  echo; echo "════════ stage: ${STAGES[$i]} ════════"
  "stage_${STAGES[$i]}"
done
echo; echo "════════ done: $first … $last ════════"
