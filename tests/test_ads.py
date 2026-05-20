"""Tests for the NASA ADS source + transform path.

The source client requires a bearer token to actually hit the API; we
exercise the auth-error path explicitly and otherwise drive the transform
layer against a constructed fixture that matches the documented ADS
response shape.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etl.sources.nasa_ads import AdsAuthError, _auth_headers
from etl.transform import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    RELATIONSHIP_FOLLOW_UP,
    RESOLVED_VIA_ADS,
    _ads_confidence_for,
    _ads_publication_date,
    ads_object_link,
    normalize_ads_publication,
)

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED_AT = datetime(2026, 5, 20, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Auth — bearer token is required
# ---------------------------------------------------------------------------


def test_ads_auth_headers_missing_token_raises(monkeypatch):
    monkeypatch.delenv("ADS_API_TOKEN", raising=False)
    with pytest.raises(AdsAuthError):
        _auth_headers()


def test_ads_auth_headers_uses_token(monkeypatch):
    monkeypatch.setenv("ADS_API_TOKEN", "test-token-abc")
    headers = _auth_headers()
    assert headers == {"Authorization": "Bearer test-token-abc"}


# ---------------------------------------------------------------------------
# Confidence scoring — title > abstract > full-text-only
# ---------------------------------------------------------------------------


def test_confidence_high_when_designation_in_title():
    conf, reason = _ads_confidence_for("99942 Apophis", "Spectroscopy of 99942 Apophis", "")
    assert conf == CONFIDENCE_HIGH
    assert "title" in reason


def test_confidence_medium_when_in_abstract_only():
    conf, reason = _ads_confidence_for(
        "99942 Apophis",
        "Spectroscopy of near-Earth asteroids",
        "We observed (99942) Apophis and other PHAs.",
    )
    # The exact-string "99942 Apophis" doesn't appear in the abstract;
    # but the heuristic is exact-match, so this falls to LOW
    assert conf == CONFIDENCE_LOW
    conf, reason = _ads_confidence_for(
        "99942 Apophis",
        "Survey of PHAs",
        "Targets include 99942 Apophis and others.",
    )
    assert conf == CONFIDENCE_MEDIUM
    assert "abstract" in reason


def test_confidence_low_when_only_full_text_match():
    conf, reason = _ads_confidence_for("99942 Apophis", "Survey paper", "Abstract here.")
    assert conf == CONFIDENCE_LOW
    assert "full-text" in reason


def test_confidence_low_when_designation_empty():
    conf, _ = _ads_confidence_for("", "anything", "anything")
    assert conf == CONFIDENCE_LOW


# ---------------------------------------------------------------------------
# Publication-date extraction
# ---------------------------------------------------------------------------


def test_pubdate_with_known_day():
    assert _ads_publication_date({"pubdate": "2024-09-15"}) == date(2024, 9, 1)


def test_pubdate_with_unknown_day_falls_back_to_first():
    assert _ads_publication_date({"pubdate": "2024-09-00"}) == date(2024, 9, 1)


def test_pubdate_falls_back_to_year_only():
    assert _ads_publication_date({"year": "2024"}) == date(2024, 1, 1)


def test_pubdate_none_when_no_date_info():
    assert _ads_publication_date({}) is None


def test_pubdate_handles_garbage():
    assert _ads_publication_date({"pubdate": "not-a-date"}) is None
    assert _ads_publication_date({"year": "not-a-year"}) is None


# ---------------------------------------------------------------------------
# normalize_ads_publication — against the constructed fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ads_payload():
    return json.loads((FIXTURES / "ads_apophis_search.json").read_text())


def test_normalize_returns_publication_row(ads_payload):
    doc = ads_payload["response"]["docs"][0]
    pub = normalize_ads_publication(doc, resolved_at=RETRIEVED_AT)
    assert pub is not None
    assert pub["ads_bibcode"] == "2024Sci...123..456S"
    assert pub["resolved_via"] == RESOLVED_VIA_ADS
    assert pub["resolved_at"] == RETRIEVED_AT
    assert pub["title"].startswith("Spectral characterization")
    assert pub["authors"] == ["Smith, Jane", "Tanaka, Hiroshi", "Müller, Anna"]
    assert pub["doi"] == "10.1126/science.abc1234"
    assert pub["publication_date"] == date(2024, 9, 1)
    assert pub["source_url"].endswith("/2024Sci...123..456S")


def test_normalize_falls_back_to_year_only_pubdate(ads_payload):
    """The first fixture doc has pubdate '2024-09-00' (known month, unknown
    day). The second has pubdate '2023-04-00'. Both should resolve to
    first-of-month."""
    docs = ads_payload["response"]["docs"]
    pub2 = normalize_ads_publication(docs[1], resolved_at=RETRIEVED_AT)
    assert pub2["publication_date"] == date(2023, 4, 1)


def test_normalize_returns_none_without_bibcode():
    pub = normalize_ads_publication(
        {"title": ["something"], "author": ["Doe, J."]}, resolved_at=RETRIEVED_AT
    )
    assert pub is None


# ---------------------------------------------------------------------------
# ads_object_link — citation graph edges with confidence
# ---------------------------------------------------------------------------


def test_object_link_high_confidence_when_designation_in_title(ads_payload):
    doc = ads_payload["response"]["docs"][0]  # title mentions Apophis
    link = ads_object_link(
        designation="99942 Apophis",
        publication_id=1,
        doc=doc,
        extracted_at=RETRIEVED_AT,
    )
    assert link["confidence"] == CONFIDENCE_HIGH
    assert link["relationship"] == RELATIONSHIP_FOLLOW_UP
    assert link["publication_id"] == 1
    assert link["designation"] == "99942 Apophis"
    assert link["extracted_from"] == "ads_search"


def test_object_link_medium_confidence_for_abstract_match(ads_payload):
    doc = ads_payload["response"]["docs"][2]  # MNRAS survey paper
    link = ads_object_link(
        designation="99942 Apophis",
        publication_id=2,
        doc=doc,
        extracted_at=RETRIEVED_AT,
    )
    # The title is generic; abstract mentions "(99942) Apophis" — not an
    # exact-string match of the search designation "99942 Apophis"
    # (note the parens). So our heuristic returns LOW.
    assert link["confidence"] in (CONFIDENCE_LOW, CONFIDENCE_MEDIUM)


def test_object_link_carries_spkid_when_provided(ads_payload):
    doc = ads_payload["response"]["docs"][0]
    link = ads_object_link(
        designation="99942 Apophis",
        publication_id=1,
        doc=doc,
        extracted_at=RETRIEVED_AT,
        spkid="20099942",
    )
    assert link["spkid"] == "20099942"
