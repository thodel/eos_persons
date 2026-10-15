"""
The name list is read from the street-split corpus of
DHBern/economies-of-space-automatically-annotated-data. These tests pin the two
things every downstream build depends on: that hgb_corpus reports dossier
metadata (coordinates, address) from the <collection> level onto each document,
and that extract_persons attaches attributes to the *right* person — a nested
reference ("Peter Müller" inside "Hans, Sohn des Peter Müller") must become its
own row and must not leak its name, occupation or death marker onto Hans.
"""
import csv
import sys
from pathlib import Path

import pytest
from lxml import etree

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import hgb_corpus          # noqa: E402
import extract_persons     # noqa: E402

STREET_XML = """<?xml version='1.0' encoding='UTF-8'?>
<corpus>
  <series id="HGB_1_999" name="Teststrasse">
    <collection id="HGB_1_999_001" variant_names="zem Test">
      <metadata>
        <dossiertype>Liegenschaft</dossiertype>
        <location>POINT(2611586.47 1267028.73)</location>
        <address>Teststrasse 1</address>
        <dossier_history><phase iteration="1"><validity_period from="1400" to="1489"/>
          <relationships><successor id="HGB_1_999_002"/></relationships></phase></dossier_history>
      </metadata>
      <document id="doc-1">
        <metadata>
          <street_id>HGB_1_999</street_id>
          <dossier_id>HGB_1_999_001</dossier_id>
          <year>1450</year>
          <source>Gerichtsarchiv</source>
          <language>german</language>
          <checked_by_gpt>true</checked_by_gpt>
          <text>Hans Sohn des Peter Müller sel . des Metzgers von Liestal</text>
          <pages><page nr="7"><![CDATA[https://example.org/page7]]></page></pages>
        </metadata>
        <text/>
        <spans>
          <span id="0" start="0" end="9" element="reference" class="per" confidence="0.9" text="Hans Sohn des Peter Müller sel . des Metzgers von Liestal" numerus="sgl" specificity="spc" subclass="">
            <span id="1" start="0" end="0" element="head" class="nam" confidence="1.0" text="Hans"/>
            <span id="2" start="1" end="9" element="appo" class="fam" confidence="0.9" text="Sohn des Peter Müller sel . des Metzgers von Liestal">
              <span id="3" start="1" end="1" element="head" class="fam" confidence="1.0" text="Sohn"/>
              <span id="4" start="3" end="9" element="reference" class="per" confidence="0.9" text="Peter Müller sel . des Metzgers von Liestal" numerus="sgl" specificity="spc" subclass="">
                <span id="5" start="3" end="4" element="head" class="nam" confidence="1.0" text="Peter Müller"/>
                <span id="6" start="5" end="6" element="attr" class="dead" confidence="1.0" text="sel ."/>
                <span id="7" start="7" end="8" element="appo" class="occ" confidence="0.9" text="des Metzgers">
                  <span id="8" start="8" end="8" element="head" class="occ" confidence="1.0" text="Metzgers" norm="metzger"/>
                </span>
                <span id="9" start="9" end="10" element="attr" class="loc" confidence="0.9" text="von Liestal"/>
              </span>
            </span>
          </span>
          <span id="10" start="12" end="12" element="reference" class="per" confidence="1.0" text="er" numerus="sgl" specificity="spc" subclass="">
            <span id="10_head" start="12" end="12" element="head" class="pro" confidence="1.0" text="er"/>
          </span>
        </spans>
        <relations/>
        <eventGroups>
          <eventGroup event_id="0" class="property-purchase" start="0" end="12" ref="" type="event">
            <event event_id="0.0">
              <role role="buyer" confidence="0.8" ref="0" text="Hans"/>
              <role role="seller" confidence="0.8" ref="4" text="Peter Müller"/>
            </event>
          </eventGroup>
        </eventGroups>
      </document>
    </collection>
  </series>
</corpus>
"""


@pytest.fixture(scope="module")
def street_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("street") / "street_HGB_1_999.xml"
    p.write_text(STREET_XML, encoding="utf-8")
    return p


def test_collection_metadata_is_projected_onto_documents(street_file):
    docs = list(hgb_corpus.iter_documents(files=[str(street_file)], progress=False))
    assert len(docs) == 1
    _, meta = docs[0]
    assert meta["dossier_id"] == "HGB_1_999_001"
    assert meta["street_id"] == "HGB_1_999"
    assert meta["street_name"] == "Teststrasse"
    assert meta["year"] == 1450
    assert meta["location"] == "POINT(2611586.47 1267028.73)"
    assert meta["address"] == "Teststrasse 1"
    assert meta["dossiertype"] == "Liegenschaft"
    assert meta["checked_by_gpt"] is True
    assert meta["pages"] == [(7, "https://example.org/page7")]
    assert meta["text"].startswith("Hans Sohn des Peter")


def test_iter_dossiers_reads_history(street_file):
    d = list(hgb_corpus.iter_dossiers(files=[str(street_file)]))
    assert len(d) == 1
    assert d[0]["successors"] == ["HGB_1_999_002"]
    assert (d[0]["valid_from"], d[0]["valid_to"]) == (1400, 1489)
    assert d[0]["n_docs"] == 1 and d[0]["year_min"] == 1450


def test_legacy_attribute_metadata_still_reads():
    doc = etree.fromstring(
        '<document id="x"><metadata dossierid="HGB_1_001_005" year="1401" '
        'location="POINT(1 2)" source="Gerichtsarchiv" text="t" pages="2" '
        'checked_by_gpt="false"/></document>')
    m = hgb_corpus.doc_meta(doc)
    assert m["dossier_id"] == "HGB_1_001_005" and m["year"] == 1401
    assert m["location"] == "POINT(1 2)" and m["n_pages"] == 2


def test_nested_person_is_its_own_row_and_does_not_leak(street_file):
    rows = []
    for doc, meta in hgb_corpus.iter_documents(files=[str(street_file)], progress=False):
        rows.extend(extract_persons.person_rows(doc, meta))
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"Hans", "Peter Müller"}, "pronoun 'er' must not be a row"

    hans = by_name["Hans"]
    assert hans["family_relation"] == "Sohn"
    assert hans["is_deceased"] == 0
    assert hans["occupation_norm"] == "" and hans["location"] == ""
    assert hans["roles"] == "buyer"

    peter = by_name["Peter Müller"]
    assert peter["is_deceased"] == 1
    assert peter["occupation_norm"] == "metzger"
    assert peter["occupation_text"] == "Metzgers"
    assert peter["location"] == "von Liestal"
    assert peter["family_relation"] == ""
    assert peter["roles"] == "seller"

    for r in rows:
        assert r["dossierid"] == "HGB_1_999_001" and r["year"] == 1450
        assert r["page_url"] == "https://example.org/page7"
        assert r["checked_by_gpt"] == 1


def test_csv_columns_match_what_build_data_reads():
    needed = {"name", "year", "dossierid", "occupation_norm", "title",
              "family_relation", "location", "org_affiliation", "is_deceased"}
    assert needed <= set(extract_persons.PERSON_COLS)
