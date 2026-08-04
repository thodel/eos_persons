"""
persons_sparql.html must agree with build_sparql_index.PERSON_ROLES.

The page needs the role set twice — once for the live-SPARQL filter and once for
the dropdown — and it is served statically, so it cannot fetch the list at
runtime without gaining a new failure mode. Both regions are therefore generated
from the Python list, and this test is what stops them drifting back apart.

They had already drifted before the generator existed: the dropdown offered 12
of the 28 roles, so `family-a`, `lessee`, `member` and thirteen others were
simply unselectable in the UI.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from build_sparql_index import PERSON_ROLES, PAGE

PAGE_PATH = REPO / PAGE


@pytest.fixture(scope="module")
def html():
    return PAGE_PATH.read_text(encoding="utf-8")


def _region(html: str, tag: str) -> str:
    m = re.search(rf"BEGIN generated:{tag}\b.*?\n(.*?)\n[^\n]*END generated:{tag}",
                  html, re.S)
    assert m, f"missing generated region: {tag}"
    return m.group(1)


def test_js_array_matches_python(html):
    found = re.findall(r"'([^']+)'", _region(html, "roles-js"))
    assert found == PERSON_ROLES


def test_dropdown_offers_every_role(html):
    values = re.findall(r'<option value="([^"]*)"', _region(html, "roles-options"))
    assert values[0] == "", "the 'all' option must come first"
    assert values[1:] == PERSON_ROLES


def test_roles_are_unique_and_lowercase():
    assert len(set(PERSON_ROLES)) == len(PERSON_ROLES), "duplicate role"
    assert all(r == r.lower() and r.strip() == r for r in PERSON_ROLES)


def test_page_is_in_sync_per_the_generator():
    """The generator's own --check-page must agree, and must not rewrite."""
    before = PAGE_PATH.read_bytes()
    r = subprocess.run([sys.executable, "build_sparql_index.py", "--check-page"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert PAGE_PATH.read_bytes() == before, "--check-page must not modify the page"


def test_only_one_literal_role_list_in_the_page(html):
    """A third hand-written copy is the failure this whole mechanism prevents."""
    outside = html.replace(_region(html, "roles-js"), "") \
                  .replace(_region(html, "roles-options"), "")
    # 'owner' appears legitimately in CSS (.tag.role-owner); a *list* of roles
    # outside the generated regions is what must not exist.
    for probe in ("bequeather", "proclaimer", "pledgee", "lessee"):
        assert probe not in outside, (
            f"{probe!r} appears outside the generated regions — "
            "another copy of the role list has crept in")
