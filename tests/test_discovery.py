"""Tests for SBDB discovery-block parsing into discovery_attributions rows."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from etl.transform import (
    _extract_discovery_program,
    _extract_mpec_id,
    _parse_discovery_date,
    normalize_discovery_attribution,
)

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED_AT = datetime(2026, 5, 20, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Program detection — survey-name → canonical code mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needle, expected",
    [
        ("Catalina Sky Survey", "CSS"),
        ("Mt. Lemmon Survey", "CSS"),
        ("Pan-STARRS Project", "PS1"),
        ("ATLAS team at IfA", "ATLAS"),
        ("NEOWISE", "NEOWISE"),
        ("LINEAR team", "LINEAR"),
        ("Spacewatch", "SPACEWATCH"),
        ("Vera C. Rubin Observatory", "RUBIN_SSP"),
    ],
)
def test_program_detected_from_who_field(needle, expected):
    assert _extract_discovery_program(needle, "") == expected


def test_program_detected_from_prose_field():
    """When `who` is just a single name (e.g. Tholen), the survey may show
    up in the longer prose paragraph instead."""
    prose = "Discovered 2018 March 1 by the Catalina Sky Survey at Mt. Lemmon."
    assert _extract_discovery_program(who="Tholen, D. J.", prose=prose) == "CSS"


def test_program_none_when_no_match():
    assert _extract_discovery_program("R. A. Tucker, D. J. Tholen", "") is None
    assert _extract_discovery_program("", "") is None


# ---------------------------------------------------------------------------
# MPEC ID extraction
# ---------------------------------------------------------------------------


def test_mpec_id_extracted_from_ref():
    ref = "20040720/MPECPaul.arc/Discovery (MPEC 2004-O02)"
    assert _extract_mpec_id(ref, "") == "MPEC 2004-O02"


def test_mpec_id_extracted_from_prose():
    prose = "Announced in MPEC 2024-Y23 on 2024 Dec 27."
    assert _extract_mpec_id("", prose) == "MPEC 2024-Y23"


def test_mpec_id_handles_lowercase_in_input():
    """Provisional designations are case-sensitive but the marker word
    'MPEC' can appear lowercase in some prose."""
    assert _extract_mpec_id("mpec 2024-Y23", "") == "MPEC 2024-Y23"


def test_mpec_id_none_when_absent():
    assert _extract_mpec_id("20050622/Numbers.arc", "discovered in 2004") is None
    assert _extract_mpec_id("", "") is None


# ---------------------------------------------------------------------------
# Date parsing — handles "YYYY-Mon-DD" plus a couple of prose variants
# ---------------------------------------------------------------------------


def test_date_parses_iso_with_short_month_name():
    assert _parse_discovery_date("2004-Jun-19") == date(2004, 6, 19)


def test_date_parses_iso_with_period_separator():
    assert _parse_discovery_date("2018 Mar. 15") == date(2018, 3, 15)


def test_date_extracts_from_prose_text():
    prose = "Discovered 2024 December 27 by ATLAS Mauna Loa."
    # The fast path tries the first 11 chars; falls through to regex
    # which expects a 3-letter month abbreviation.
    prose_short = "2024 Dec 27 ATLAS discovery."
    assert _parse_discovery_date(prose_short) == date(2024, 12, 27)
    # The full sentence above doesn't match either pattern (full month name)
    assert _parse_discovery_date(prose) is None


def test_date_none_on_empty_or_garbage():
    assert _parse_discovery_date(None) is None
    assert _parse_discovery_date("") is None
    assert _parse_discovery_date("when the morning sun rose") is None


# ---------------------------------------------------------------------------
# Full normalize against the real Apophis fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sbdb_apophis() -> dict[str, Any]:
    return json.loads((FIXTURES / "sbdb_apophis.json").read_text())


def test_apophis_normalize_returns_expected_shape(sbdb_apophis):
    row = normalize_discovery_attribution(
        sbdb_apophis, source_retrieved_at=RETRIEVED_AT
    )
    assert row is not None
    assert row["spkid"] == "20099942"
    assert row["discovery_date"] == date(2004, 6, 19)
    assert row["discovery_facility"] == "Kitt Peak"
    # Apophis was discovered by individuals, not a survey
    assert row["discovery_program"] is None
    assert row["captured_at"] == RETRIEVED_AT
    assert row["raw_record"] is sbdb_apophis["discovery"]


def test_apophis_carries_citation_text_unchanged(sbdb_apophis):
    row = normalize_discovery_attribution(
        sbdb_apophis, source_retrieved_at=RETRIEVED_AT
    )
    assert row["citation_text"] is not None
    assert "Apep" in row["citation_text"]


# ---------------------------------------------------------------------------
# Synthetic survey-discovery shapes (the modern common case)
# ---------------------------------------------------------------------------


def _sbdb_with_discovery(**overrides) -> dict[str, Any]:
    base = {
        "object": {"spkid": "54123456", "des": "2024 ABC"},
        "discovery": {
            "discovery": "Discovered 2024 Jan 15 by the Catalina Sky Survey.",
            "site": "703",
            "date": "2024-Jan-15",
            "ref": "MPEC 2024-A99",
            "name": None,
            "citation": None,
            "cref": None,
            "who": "Catalina Sky Survey",
            "location": "Mt. Lemmon",
        },
    }
    base["discovery"].update(overrides)
    return base


def test_modern_survey_discovery_yields_program_code():
    row = normalize_discovery_attribution(
        _sbdb_with_discovery(), source_retrieved_at=RETRIEVED_AT
    )
    assert row is not None
    assert row["discovery_program"] == "CSS"
    assert row["discovery_facility"] == "Mt. Lemmon"
    assert row["site_code"] == "703"
    assert row["mpec_id"] == "MPEC 2024-A99"
    assert row["discovery_date"] == date(2024, 1, 15)


def test_panstarrs_discovery_yields_ps1_code():
    row = normalize_discovery_attribution(
        _sbdb_with_discovery(who="Pan-STARRS Project", site="F51", location="Haleakala"),
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["discovery_program"] == "PS1"


def test_no_discovery_block_returns_none():
    sbdb = {"object": {"spkid": "54x"}, "discovery": None}
    assert normalize_discovery_attribution(sbdb, source_retrieved_at=RETRIEVED_AT) is None


def test_missing_spkid_returns_none():
    sbdb = {"object": {}, "discovery": {"who": "Anyone"}}
    assert normalize_discovery_attribution(sbdb, source_retrieved_at=RETRIEVED_AT) is None
