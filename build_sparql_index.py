"""
build_sparql_index.py
Queries the Historisches Grundbuch Basel SPARQL endpoint and builds a cached
JSON index of person mentions for use by persons_sparql.html.

Strategy: query one role at a time in pages of raw (nameText, year) rows,
aggregate in Python — avoids expensive server-side GROUP BY / DISTINCT.

Usage:
    python3 build_sparql_index.py [--page-size N] [--out PATH]

Options:
    --page-size N   Rows per SPARQL request (default: 5000)
    --out PATH      Output path (default: persons_sparql_index.json)
"""

import json
import re
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict

ENDPOINT = "https://sparql-gdb.lod4hss.org/eos"

# Roles considered person references (same list as in persons_sparql.html)
PERSON_ROLES = [
    "owner", "buyer", "seller", "payer", "employer", "employee",
    "beneficiary", "heir", "decedent", "claimant", "debitor", "resident",
    "bequeather", "consenting", "proclaimer", "party1", "party2",
    "pledger", "pledgee", "redeemer", "grantor", "creditor", "bidder",
    "member", "actor", "family-a", "family-b", "lessee",
]

# Anaphoric references, determiners and bare generic nouns that the extraction
# records as person roles. They are correct as *references* to a person, but
# carry no identity, and being extremely frequent they otherwise dominate the
# index when it is browsed by mention count ("seine" alone had 11,033).
#
# Matched only against the WHOLE normalised string, never as a substring, so
# multi-word mentions that embed a real name survive — "seine Frau Ennelin"
# is kept, bare "seine" is dropped. Middle High German / Early New High German
# orthography varies freely (i/j/y, -in/-en), hence the many variants.
PRONOUN_STOPWORDS = frozenset("""
sein seine seinem seinen seiner seines seim seyn sen
sin sine sinem sinen siner sines sins sim syn synem synen syner sym
ir ire irem iren irer ires irs
jr jre jrem jren jrer jres jrs jro jme jnen
yr yre yrem yren yrer
ihm ihme ihn ihnen ihr ihre ihrem ihren ihrer ihres
ime inen
er sie es sich selbs selbst
ich wir uns unser unsere unserem unseren unserm unsern
der die das dem den des ders
ein eine einem einen einer eines eins
derselb derselbe derselben desselben demselben denselben
dieselb dieselbe dieselben dasselbe
dessen deren denen
welcher welche welchem welchen welches
sel selig seligen seelig seeligen sal
jeder jede jedem jeden
eig eigen
eius sue sic idem eiusdem
wer wem wen was
und oder aber
""".split())

# Punctuation/whitespace the extraction leaves attached to a span.
_NORM_RE = re.compile(r"^[\W_]+|[\W_]+$", flags=re.UNICODE)


def is_name_like(text: str) -> bool:
    """True unless the whole span normalises to a stopword (or to nothing)."""
    norm = _NORM_RE.sub("", text).casefold()
    if len(norm) < 2:
        return False
    return norm not in PRONOUN_STOPWORDS


def sparql(query: str, timeout: int = 90) -> dict:
    data = query.encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_role(role: str, page_size: int) -> list[tuple[str, int]]:
    """Return list of (nameText, year) for a single role, paginating."""
    rows = []
    offset = 0
    while True:
        query = f"""
PREFIX eos: <https://eos.lod4hss.org/ontology#>
SELECT ?nameText ?year WHERE {{
  ?er a eos:eventRole .
  ?er eos:hasRole "{role}" .
  ?er eos:hasRoleText ?nameText .
  ?er eos:isPartOfEvent ?event .
  ?event eos:isPartOfEventGroup ?evg .
  ?evg eos:hasYear ?year .
  FILTER(STRLEN(STR(?nameText)) > 2)
}}
LIMIT {page_size} OFFSET {offset}
""".strip()
        try:
            result = sparql(query)
        except Exception as e:
            print(f"    page at offset {offset} failed: {e}", flush=True)
            break

        bindings = result["results"]["bindings"]
        for b in bindings:
            name = b["nameText"]["value"]
            year = b["year"]["value"]
            try:
                rows.append((name, int(year)))
            except ValueError:
                pass

        if len(bindings) < page_size:
            break  # last page
        offset += page_size

    return rows


def build_index(page_size: int) -> list:
    # Aggregate: name -> {count, min_year, max_year, roles}
    agg: dict[str, dict] = defaultdict(lambda: {"c": 0, "yFrom": None, "yTo": None, "roles": set()})

    kept_rows = 0
    dropped_rows = 0
    dropped_forms = defaultdict(int)

    total_roles = len(PERSON_ROLES)
    for i, role in enumerate(PERSON_ROLES, 1):
        t0 = time.time()
        print(f"[{i}/{total_roles}] role='{role}'", end=" ", flush=True)
        rows = fetch_role(role, page_size)
        for name, year in rows:
            if not is_name_like(name):
                dropped_rows += 1
                dropped_forms[name] += 1
                continue
            kept_rows += 1
            e = agg[name]
            e["c"] += 1
            e["roles"].add(role)
            if e["yFrom"] is None or year < e["yFrom"]:
                e["yFrom"] = year
            if e["yTo"] is None or year > e["yTo"]:
                e["yTo"] = year
        print(f"→ {len(rows)} rows in {time.time()-t0:.1f}s", flush=True)

    print(f"\nFiltered {dropped_rows:,} anaphoric/determiner rows "
          f"({len(dropped_forms)} distinct forms); kept {kept_rows:,}.")
    for form, n in sorted(dropped_forms.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    dropped {n:>6}  {form!r}")

    # Serialise
    index = [
        {
            "n":     name,
            "c":     data["c"],
            "y":     [data["yFrom"], data["yTo"]],
            "roles": sorted(data["roles"]),
        }
        for name, data in agg.items()
    ]
    index.sort(key=lambda x: x["c"], reverse=True)
    return index


def main():
    parser = argparse.ArgumentParser(description="Build persons SPARQL index JSON.")
    parser.add_argument("--page-size", type=int, default=5000,
                        help="Rows per SPARQL page request (default: 5000)")
    parser.add_argument("--out", default="persons_sparql_index.json",
                        help="Output file (default: persons_sparql_index.json)")
    args = parser.parse_args()

    print(f"Endpoint : {ENDPOINT}")
    print(f"Page size: {args.page_size}")
    print(f"Roles    : {len(PERSON_ROLES)}")
    print()

    try:
        index = build_index(args.page_size)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nWrote {len(index):,} name entries to {args.out}")


if __name__ == "__main__":
    main()
