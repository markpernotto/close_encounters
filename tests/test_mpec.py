"""Tests for the MPC MPEC source + transform path."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etl.sources.mpc_mpec import (
    _extract_featured_designations,
    _extract_issued_at,
    _extract_mentioned_designations,
    _extract_mpec_id,
    _extract_pre_block,
    _extract_title,
    mpec_url,
    parse_mpec_html,
)
from etl.transform import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    RELATIONSHIP_DISCOVERY,
    RELATIONSHIP_FOLLOW_UP,
    RESOLVED_VIA_MPEC,
    mpec_object_links,
    normalize_mpec_publication,
)

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED_AT = datetime(2026, 5, 20, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mpec_id, expected_path",
    [
        ("MPEC 2024-Y17", "/mpec/K24/K24Y17.html"),
        ("MPEC 2004-O02", "/mpec/K04/K04O02.html"),
        ("MPEC 2026-A05", "/mpec/K26/K26A05.html"),
        ("MPEC 1999-A99", "/mpec/K99/K99A99.html"),
    ],
)
def test_mpec_url_builds_canonical_path(mpec_id, expected_path):
    assert mpec_url(mpec_id).endswith(expected_path)


def test_mpec_url_handles_lowercase_marker():
    assert mpec_url("mpec 2024-Y17").endswith("K24Y17.html")


def test_mpec_url_raises_on_bad_input():
    with pytest.raises(ValueError):
        mpec_url("not-an-mpec-id")


# ---------------------------------------------------------------------------
# Parser primitives — title, pre block, issued date
# ---------------------------------------------------------------------------


@pytest.fixture
def html_y17() -> str:
    return (FIXTURES / "mpec_2024-Y17.html").read_text()


@pytest.fixture
def html_o02() -> str:
    return (FIXTURES / "mpec_2004-O02.html").read_text()


def test_title_strips_mpec_prefix(html_y17):
    title = _extract_title(html_y17)
    assert title is not None
    assert not title.startswith("MPEC")  # the 'MPEC YYYY-XXX : ' prefix was stripped


def test_pre_block_starts_with_mpec_header(html_y17):
    pre = _extract_pre_block(html_y17)
    assert pre is not None
    assert "M.P.E.C. 2024-Y17" in pre


def test_mpec_id_extracted_from_pre_header_with_periods(html_y17):
    pre = _extract_pre_block(html_y17)
    assert _extract_mpec_id(pre) == "MPEC 2024-Y17"


def test_mpec_id_extracted_from_old_announcement(html_o02):
    pre = _extract_pre_block(html_o02)
    assert _extract_mpec_id(pre) == "MPEC 2004-O02"


def test_issued_at_parses_full_month_name(html_y17):
    pre = _extract_pre_block(html_y17)
    issued = _extract_issued_at(pre)
    assert issued is not None
    assert issued == datetime(2024, 12, 20, 15, 21, tzinfo=UTC)


def test_issued_at_parses_2004_format(html_o02):
    pre = _extract_pre_block(html_o02)
    issued = _extract_issued_at(pre)
    assert issued is not None
    assert issued.year == 2004
    assert issued.month == 7


# ---------------------------------------------------------------------------
# Designation extraction
# ---------------------------------------------------------------------------


def test_featured_designation_from_y17(html_y17):
    pre = _extract_pre_block(html_y17)
    featured = _extract_featured_designations(pre)
    # The MPEC announces 2024 YD
    assert "2024 YD" in featured


def test_mentioned_designations_include_featured(html_y17):
    pre = _extract_pre_block(html_y17)
    mentioned = _extract_mentioned_designations(pre)
    assert "2024 YD" in mentioned


def test_mentioned_designations_dedupe_repeats(html_y17):
    pre = _extract_pre_block(html_y17)
    mentioned = _extract_mentioned_designations(pre)
    # 2024 YD appears many times in the observation block; should be one entry
    assert mentioned.count("2024 YD") == 1


# ---------------------------------------------------------------------------
# parse_mpec_html — the integrated parser
# ---------------------------------------------------------------------------


def test_parse_y17_yields_full_structure(html_y17):
    parsed = parse_mpec_html(html_y17)
    assert parsed["mpec_id"] == "MPEC 2024-Y17"
    assert isinstance(parsed["issued_at"], datetime)
    assert parsed["title"]  # non-empty
    assert "2024 YD" in parsed["featured_designations"]
    assert "2024 YD" in parsed["mentioned_designations"]


def test_parse_o02_yields_id_and_date(html_o02):
    parsed = parse_mpec_html(html_o02)
    assert parsed["mpec_id"] == "MPEC 2004-O02"
    assert parsed["issued_at"].year == 2004


# ---------------------------------------------------------------------------
# normalize_mpec_publication
# ---------------------------------------------------------------------------


def test_normalize_returns_publication_row(html_y17):
    parsed = parse_mpec_html(html_y17)
    pub = normalize_mpec_publication(parsed, resolved_at=RETRIEVED_AT)
    assert pub is not None
    assert pub["mpec_id"] == "MPEC 2024-Y17"
    assert pub["resolved_via"] == RESOLVED_VIA_MPEC
    assert pub["resolved_at"] == RETRIEVED_AT
    assert pub["source_url"].endswith("/K24Y17.html")
    assert pub["publication_date"] == date(2024, 12, 20)
    assert pub["title"]


def test_normalize_returns_none_when_no_mpec_id():
    parsed = {"mpec_id": None, "title": "stuff", "issued_at": None,
              "featured_designations": [], "mentioned_designations": []}
    assert normalize_mpec_publication(parsed, resolved_at=RETRIEVED_AT) is None


# ---------------------------------------------------------------------------
# mpec_object_links — featured → discovery, mentioned → follow_up
# ---------------------------------------------------------------------------


def test_featured_yields_discovery_relationship_at_high_confidence():
    parsed = {
        "mpec_id": "MPEC 2024-Y17",
        "featured_designations": ["2024 YD"],
        "mentioned_designations": ["2024 YD"],
    }
    links = mpec_object_links(
        parsed, publication_id=42, extracted_at=RETRIEVED_AT
    )
    assert len(links) == 1
    link = links[0]
    assert link["designation"] == "2024 YD"
    assert link["relationship"] == RELATIONSHIP_DISCOVERY
    assert link["confidence"] == CONFIDENCE_HIGH
    assert link["publication_id"] == 42


def test_mentioned_but_not_featured_yields_follow_up_relationship():
    parsed = {
        "mpec_id": "MPEC 2024-Y17",
        "featured_designations": ["2024 YD"],
        "mentioned_designations": ["2024 YD", "2024 YE", "99942"],
    }
    links = mpec_object_links(parsed, publication_id=42, extracted_at=RETRIEVED_AT)
    by_des = {link["designation"]: link for link in links}
    assert by_des["2024 YD"]["relationship"] == RELATIONSHIP_DISCOVERY
    assert by_des["2024 YE"]["relationship"] == RELATIONSHIP_FOLLOW_UP
    assert by_des["2024 YE"]["confidence"] == CONFIDENCE_MEDIUM
    assert by_des["99942"]["relationship"] == RELATIONSHIP_FOLLOW_UP


def test_object_links_resolve_spkid_when_provided():
    parsed = {
        "mpec_id": "MPEC 2024-Y17",
        "featured_designations": ["2024 YD"],
        "mentioned_designations": ["2024 YD"],
    }
    links = mpec_object_links(
        parsed, publication_id=42, extracted_at=RETRIEVED_AT,
        designation_to_spkid={"2024 YD": "54123456"},
    )
    assert links[0]["spkid"] == "54123456"


def test_object_links_spkid_none_when_unresolved():
    parsed = {
        "mpec_id": "MPEC 2024-Y17",
        "featured_designations": ["2024 YD"],
        "mentioned_designations": [],
    }
    links = mpec_object_links(parsed, publication_id=42, extracted_at=RETRIEVED_AT)
    assert links[0]["spkid"] is None


def test_no_designations_means_no_links():
    parsed = {
        "mpec_id": "MPEC 2024-Y17",
        "featured_designations": [],
        "mentioned_designations": [],
    }
    assert mpec_object_links(parsed, publication_id=42, extracted_at=RETRIEVED_AT) == []
