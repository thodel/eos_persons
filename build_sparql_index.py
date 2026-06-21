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

    total_roles = len(PERSON_ROLES)
    for i, role in enumerate(PERSON_ROLES, 1):
        t0 = time.time()
        print(f"[{i}/{total_roles}] role='{role}'", end=" ", flush=True)
        rows = fetch_role(role, page_size)
        for name, year in rows:
            e = agg[name]
            e["c"] += 1
            e["roles"].add(role)
            if e["yFrom"] is None or year < e["yFrom"]:
                e["yFrom"] = year
            if e["yTo"] is None or year > e["yTo"]:
                e["yTo"] = year
        print(f"→ {len(rows)} rows in {time.time()-t0:.1f}s", flush=True)

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
