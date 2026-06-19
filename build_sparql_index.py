"""
build_sparql_index.py
Queries the Historisches Grundbuch Basel SPARQL endpoint and builds a cached
JSON index of person mentions for use by persons_sparql.html.

Usage:
    python3 build_sparql_index.py [--limit N] [--out PATH]

Options:
    --limit N    Max name strings to fetch (default: 5000)
    --out PATH   Output path (default: persons_sparql_index.json)

The output JSON is an array of objects consumed directly by persons_sparql.html:
    [{ "n": "Georg Bulacher", "c": 12, "y": [1640, 1670], "roles": ["owner","payer"] }, ...]
"""

import json
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error

ENDPOINT = "https://sparql-gdb.lod4hss.org/eos"

PERSON_ROLES = [
    "owner", "buyer", "seller", "payer", "employer", "employee",
    "beneficiary", "heir", "decedent", "claimant", "debitor", "resident",
    "bequeather", "consenting", "proclaimer", "party1", "party2",
    "pledger", "pledgee", "redeemer", "grantor", "creditor", "bidder",
    "member", "actor", "family-a", "family-b", "lessee",
]

ROLES_SPARQL = " ".join(f'"{r}"' for r in PERSON_ROLES)


def sparql(query: str, timeout: int = 120) -> dict:
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


def build_index(limit: int) -> list:
    roles_filter = "(" + ", ".join(f'"{r}"' for r in PERSON_ROLES) + ")"

    # Query 1: get all distinct name strings with person roles
    print(f"Fetching up to {limit} name strings from SPARQL endpoint…")
    name_query = f"""
PREFIX eos: <https://eos.lod4hss.org/ontology#>
SELECT DISTINCT ?nameText WHERE {{
  ?er a eos:eventRole .
  ?er eos:hasRole ?role .
  ?er eos:hasRoleText ?nameText .
  FILTER(?role IN {roles_filter})
  FILTER(STRLEN(STR(?nameText)) > 2)
}}
LIMIT {limit}
""".strip()

    t0 = time.time()
    result = sparql(name_query)
    names = [b["nameText"]["value"] for b in result["results"]["bindings"]]
    print(f"  Got {len(names)} name strings in {time.time()-t0:.1f}s")

    if not names:
        print("No names returned — check endpoint connectivity.")
        return []

    # Query 2: for each batch of names, get counts and year ranges
    # We batch to avoid SPARQL query length limits
    BATCH = 200
    index = []
    total = len(names)

    for i in range(0, total, BATCH):
        batch = names[i : i + BATCH]
        values_clause = " ".join(f'"{n.replace(chr(34), chr(39))}"' for n in batch)

        detail_query = f"""
PREFIX eos: <https://eos.lod4hss.org/ontology#>
PREFIX sim: <https://sdhss.org/ontology/sources-information-metadata/>
SELECT ?nameText
       (COUNT(DISTINCT ?er) AS ?cnt)
       (MIN(?year) AS ?yFrom)
       (MAX(?year) AS ?yTo)
       (GROUP_CONCAT(DISTINCT ?role; separator="|") AS ?roles)
WHERE {{
  VALUES ?nameText {{ {values_clause} }}
  ?er a eos:eventRole .
  ?er eos:hasRole ?role .
  ?er eos:hasRoleText ?nameText .
  ?er eos:isPartOfEvent ?event .
  ?event eos:isPartOfEventGroup ?evg .
  ?evg eos:hasYear ?year .
  FILTER(?role IN {roles_filter})
}}
GROUP BY ?nameText
ORDER BY DESC(?cnt)
""".strip()

        t1 = time.time()
        try:
            res = sparql(detail_query, timeout=180)
        except Exception as e:
            print(f"  Batch {i//BATCH + 1} failed: {e}. Skipping.")
            continue

        for b in res["results"]["bindings"]:
            name = b["nameText"]["value"]
            cnt  = int(b["cnt"]["value"])
            yf   = int(b["yFrom"]["value"]) if b.get("yFrom") else None
            yt   = int(b["yTo"]["value"])   if b.get("yTo")   else None
            roles = [r for r in b["roles"]["value"].split("|") if r] if b.get("roles") else []
            index.append({
                "n": name,
                "c": cnt,
                "y": [yf, yt] if yf and yt else [None, None],
                "roles": roles,
            })

        done = min(i + BATCH, total)
        elapsed = time.time() - t1
        print(f"  Batch {i//BATCH + 1}/{(total + BATCH - 1)//BATCH}: {done}/{total} names ({elapsed:.1f}s)")

    # Sort by mention count descending
    index.sort(key=lambda x: x["c"], reverse=True)
    return index


def main():
    parser = argparse.ArgumentParser(description="Build persons SPARQL index JSON.")
    parser.add_argument("--limit", type=int, default=5000,
                        help="Max distinct name strings to include (default: 5000)")
    parser.add_argument("--out", default="persons_sparql_index.json",
                        help="Output file path (default: persons_sparql_index.json)")
    args = parser.parse_args()

    try:
        index = build_index(args.limit)
    except urllib.error.URLError as e:
        print(f"Connection error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nWrote {len(index)} entries to {args.out}")


if __name__ == "__main__":
    main()
