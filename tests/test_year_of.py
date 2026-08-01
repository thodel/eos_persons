"""
Regression tests for link_hls.year_of.

The function looks trivial enough to "simplify" back to a bare \\d{3,4} search,
which is the bug these tests exist to prevent: GND encodes an imprecise year by
replacing its final digits with X, so '[149X]' ("some year in the 1490s") parses
as the year 149 and travels on into life spans, year-range filters and the
published corpus statistics, indistinguishable from a real date.

The shapes below are the complete set observed across 55,099 date strings in the
HLS export and the GND enrichment — not invented examples.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from link_hls import year_of


@pytest.mark.parametrize("text,expected", [
    # precise dates — every shape present in the two sources
    ("1724",        1724),   # bare year          (4207 in GND, 5493 in HLS)
    ("1792-06-16",  1792),   # ISO date           (2314 / 42775)
    ("1695-10",     1695),   # year-month         (17 / 264)
    ("[1290/1300]", 1290),   # range -> earliest bound
])
def test_precise_dates_are_parsed(text, expected):
    assert year_of(text) == expected


@pytest.mark.parametrize("text", [
    "[149X]",   # decade only — the truncation bug: must not yield 149
    "[152X]",
    "[169X]",
    "[178X]",
    "[16XX]",   # century only
    "[1XXX]",
    "[XXXX]",   # nothing at all
])
def test_imprecise_dates_yield_none(text):
    assert year_of(text) is None, f"{text!r} must not produce a precise year"


@pytest.mark.parametrize("text", ["", None, "n/a", "ohne Datum", "X"])
def test_empty_and_junk(text):
    assert year_of(text) is None


def test_lowercase_placeholder_also_rejected():
    """GND is uppercase, but a lowercased feed must not slip through."""
    assert year_of("[149x]") is None


def test_does_not_split_a_longer_number():
    """A stray long digit run is not a year and must not be truncated into one."""
    assert year_of("123456") is None


def test_bc_dates_keep_prior_behaviour():
    """HLS carries a handful of BC dates; the sign was never handled and the
    fix must not silently change what they parse to."""
    assert year_of("-0042-11-16") == 42
