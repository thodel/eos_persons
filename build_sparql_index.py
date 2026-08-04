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

# The event roles that denote a person. This list is the single source of
# truth: persons_sparql.html needs the same set both for its live-SPARQL
# filter and for its role dropdown, and the page must stay self-contained
# (it is served statically and has to work with no cached index), so the two
# regions in the HTML are generated from here rather than fetched at runtime.
#
#     python3 build_sparql_index.py --sync-page    # rewrite the page
#     python3 build_sparql_index.py --check-page   # fail if it has drifted
PERSON_ROLES = [
    "owner", "buyer", "seller", "payer", "employer", "employee",
    "beneficiary", "heir", "decedent", "claimant", "debitor", "resident",
    "bequeather", "consenting", "proclaimer", "party1", "party2",
    "pledger", "pledgee", "redeemer", "grantor", "creditor", "bidder",
    "member", "actor", "family-a", "family-b", "lessee",
]

PAGE = "persons_sparql.html"

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


# ── Keeping persons_sparql.html in step ───────────────────────────────────────

# Marker syntax differs by region: the role list sits inside <script>, where an
# HTML comment is not reliably a comment (`<!--` is legacy-parsed and `-->` only
# closes at the start of a line), so that region is delimited with JS comments.
_MARKERS = {
    "roles-js": ("// BEGIN generated:{} — build_sparql_index.py --sync-page",
                 "// END generated:{}"),
    "roles-options": ("<!-- BEGIN generated:{} — build_sparql_index.py --sync-page -->",
                      "<!-- END generated:{} -->"),
}


def _render_js(indent: str = "  ") -> str:
    """The JS array, wrapped at roughly the width the rest of the file uses."""
    lines, row = [], []
    for role in PERSON_ROLES:
        row.append(f"'{role}'")
        if len(",".join(row)) > 58:
            lines.append(indent + "  " + ",".join(row) + ",")
            row = []
    if row:
        lines.append(indent + "  " + ",".join(row))
    return (f"{indent}const PERSON_ROLES = [\n"
            + "\n".join(lines)
            + f"\n{indent}];")


def _render_options(indent: str = "      ") -> str:
    opts = [f'{indent}<option value="">— all —</option>']
    opts += [f'{indent}<option value="{r}">{r}</option>' for r in PERSON_ROLES]
    return "\n".join(opts)


def _splice(text: str, tag: str, body: str) -> str:
    """Replace the marked region `tag` in `text` with `body`."""
    begin_t, end_t = _MARKERS[tag]
    begin, end = begin_t.format(tag), end_t.format(tag)
    i, j = text.find(begin), text.find(end)
    if i < 0 or j < 0:
        raise SystemExit(f"{PAGE}: missing markers for '{tag}'. Expected:\n"
                         f"  {begin}\n  ...\n  {end}")
    # Indent the closing marker like the opening one; splicing on the marker
    # offset alone would otherwise strip its leading whitespace each run.
    indent = text[text.rfind("\n", 0, i) + 1: i]
    return text[: i + len(begin)] + "\n" + body + "\n" + indent + text[j:]


def sync_page(path: str, check: bool = False) -> bool:
    """Regenerate the role regions in the page. Returns True if it was in sync."""
    with open(path, encoding="utf-8") as fh:
        original = fh.read()

    updated = _splice(original, "roles-js", _render_js())
    updated = _splice(updated, "roles-options", _render_options())

    if updated == original:
        print(f"{path}: roles in sync ({len(PERSON_ROLES)}).")
        return True

    if check:
        print(f"{path}: OUT OF SYNC with PERSON_ROLES "
              f"({len(PERSON_ROLES)} roles). Run: "
              f"python3 build_sparql_index.py --sync-page", file=sys.stderr)
        return False

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    print(f"{path}: rewritten from PERSON_ROLES ({len(PERSON_ROLES)} roles).")
    return True


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
    parser.add_argument("--page", default=PAGE,
                        help=f"Page to keep in step (default: {PAGE})")
    parser.add_argument("--sync-page", action="store_true",
                        help="Rewrite the role regions in the page and exit")
    parser.add_argument("--check-page", action="store_true",
                        help="Exit non-zero if the page has drifted; changes nothing")
    args = parser.parse_args()

    # Both are page-only operations: neither touches the endpoint.
    if args.sync_page or args.check_page:
        ok = sync_page(args.page, check=args.check_page)
        sys.exit(0 if ok else 1)

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
