"""Tests for the NASA Sentry source + transform path."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from etl.sources.jpl_sentry import _rows as sentry_rows
from etl.transform import (
    AGENCY_NASA_SENTRY,
    SENTRY_URL,
    _parse_year_range,
    _risk_class_for_sentry,
    normalize_sentry_assessment,
)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_DATE = date(2026, 5, 19)
RETRIEVED_AT = datetime(2026, 5, 19, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Source: row extraction handles both dict-style (current) and column-style
# (legacy) responses
# ---------------------------------------------------------------------------


@pytest.fixture
def sentry_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "sentry_summary.json").read_text())


def test_sentry_payload_has_expected_envelope(sentry_payload):
    assert sentry_payload["signature"]["source"].startswith("NASA/JPL Sentry")
    assert isinstance(sentry_payload["data"], list)
    # The Sentry API returns `count` as a string in their current version
    assert int(sentry_payload["count"]) == len(sentry_payload["data"])


def test_sentry_rows_returns_dicts_directly_for_current_format(sentry_payload):
    rows = sentry_rows(sentry_payload)
    assert isinstance(rows, list)
    assert len(rows) > 100  # Sentry list has thousands; loose lower bound
    first = rows[0]
    assert {"des", "id", "h", "ip"} <= first.keys()


def test_sentry_rows_handles_legacy_column_oriented_response():
    legacy = {
        "fields": ["des", "h", "ip"],
        "data": [["1979 XB", "18.54", "8.5e-7"], ["2024 YR4", "23.0", "1.0e-9"]],
        "count": 2,
    }
    rows = sentry_rows(legacy)
    assert rows == [
        {"des": "1979 XB", "h": "18.54", "ip": "8.5e-7"},
        {"des": "2024 YR4", "h": "23.0", "ip": "1.0e-9"},
    ]


# ---------------------------------------------------------------------------
# Year-range parsing — Sentry's "range" is "YYYY-YYYY" or "YYYY"
# ---------------------------------------------------------------------------


def test_parse_year_range_two_part():
    assert _parse_year_range("2056-2113") == (2056, 2113)


def test_parse_year_range_single_year():
    assert _parse_year_range("2056") == (2056, 2056)


def test_parse_year_range_handles_missing_and_empty():
    assert _parse_year_range(None) == (None, None)
    assert _parse_year_range("") == (None, None)


def test_parse_year_range_handles_garbage():
    a, b = _parse_year_range("not-a-year")
    # First half doesn't parse, second is "a-year" which also doesn't
    assert a is None
    assert b is None


# ---------------------------------------------------------------------------
# Risk-class bucketing
# ---------------------------------------------------------------------------


def test_risk_class_returns_torino_label_for_elevated_score():
    assert _risk_class_for_sentry({"ts_max": "2"}) == "torino_2"


def test_risk_class_treats_torino_zero_as_background():
    assert _risk_class_for_sentry({"ts_max": "0", "ps_cum": "-3.5"}) == "background"


def test_risk_class_palermo_elevated_when_above_minus_two():
    # Palermo cum -1.8 → "palermo_elevated"
    assert _risk_class_for_sentry({"ts_max": "0", "ps_cum": "-1.8"}) == "palermo_elevated"


def test_risk_class_background_when_palermo_well_negative():
    assert _risk_class_for_sentry({"ts_max": "0", "ps_cum": "-6.0"}) == "background"


# ---------------------------------------------------------------------------
# normalize_sentry_assessment — full shape against the real fixture
# ---------------------------------------------------------------------------


def test_normalize_returns_risk_assessments_row_shape(sentry_payload):
    record = sentry_rows(sentry_payload)[0]
    row = normalize_sentry_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    assert row["agency"] == AGENCY_NASA_SENTRY
    assert row["assessment_date"] == SNAPSHOT_DATE
    assert row["source_url"] == SENTRY_URL
    assert row["source_retrieved_at"] == RETRIEVED_AT
    assert row["raw_row"] is record
    assert isinstance(row["designation"], str) and row["designation"]
    assert row["torino_scale"] is not None or row["torino_scale"] == 0


def test_normalize_coerces_numeric_strings(sentry_payload):
    record = sentry_rows(sentry_payload)[0]
    row = normalize_sentry_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    if row["palermo_scale"] is not None:
        assert isinstance(row["palermo_scale"], float)
    if row["impact_probability"] is not None:
        assert isinstance(row["impact_probability"], float)
        assert 0 <= row["impact_probability"] < 1  # IP is a probability


def test_normalize_carries_supplied_spkid():
    record = {"des": "99942", "h": "19.7", "ip": "0", "ts_max": "0", "ps_cum": "-10"}
    row = normalize_sentry_assessment(
        record,
        snapshot_date=SNAPSHOT_DATE,
        source_retrieved_at=RETRIEVED_AT,
        spkid="20099942",
    )
    assert row["spkid"] == "20099942"


def test_normalize_leaves_spkid_none_when_not_supplied():
    record = {"des": "1979 XB", "h": "18.5"}
    row = normalize_sentry_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    assert row["spkid"] is None


def test_normalize_parses_year_range_into_min_max(sentry_payload):
    record = sentry_rows(sentry_payload)[0]
    row = normalize_sentry_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    if record.get("range"):
        assert row["potential_impact_year_min"] is not None
        assert row["potential_impact_year_max"] is not None
        assert row["potential_impact_year_min"] <= row["potential_impact_year_max"]


# ---------------------------------------------------------------------------
# End-to-end: gather_snapshot wires Sentry through to risk_rows + manifest
# ---------------------------------------------------------------------------


def test_gather_snapshot_with_sentry_produces_risk_rows():
    from etl.extract import gather_snapshot

    cneos_payload = {
        "signature": {"version": "1.5", "source": "fake"},
        "count": 0,
        "fields": ["des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max", "v_rel", "v_inf", "t_sigma_f", "h"],
        "data": [],
    }
    sentry_payload = {
        "signature": {"source": "NASA/JPL Sentry Data API", "version": "2.0"},
        "count": 2,
        "data": [
            {"des": "1979 XB", "id": "x1", "h": "18.5", "diameter": "0.66",
             "n_imp": 4, "ip": "8.5e-7", "ps_max": "-2.99", "ps_cum": "-2.69",
             "ts_max": "0", "v_inf": "23.76", "range": "2056-2113",
             "last_obs": "1979-12-15", "fullname": "(1979 XB)"},
            {"des": "2024 YR4", "id": "x2", "h": "23.0", "diameter": "0.05",
             "n_imp": 1, "ip": "1.0e-3", "ps_max": "-3.5", "ps_cum": "-3.5",
             "ts_max": "3", "v_inf": "16.0", "range": "2032",
             "last_obs": "2024-02-22", "fullname": "(2024 YR4)"},
        ],
    }

    uploads: list[tuple[str, bytes]] = []
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=lambda **_: cneos_payload,
        sbdb_fetch=lambda _: {"object": {}, "orbit": {}},  # unused since no CNEOS rows
        sentry_fetch=lambda: sentry_payload,
        put_raw=lambda k, b: uploads.append((k, b)),
        sbdb_delay_sec=0.0,
    )
    assert len(snap.risk_rows) == 2
    assert {r["designation"] for r in snap.risk_rows} == {"1979 XB", "2024 YR4"}
    assert any(k.endswith("/sentry.json") for k, _ in uploads)
    # Manifest should list sentry as a source
    kinds = [s["kind"] for s in snap.manifest_entry["sources"]]
    assert "sentry" in kinds


def test_gather_snapshot_without_sentry_fetch_emits_no_risk_rows():
    from etl.extract import gather_snapshot

    cneos_payload = {
        "signature": {}, "count": 0, "fields": [
            "des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max",
            "v_rel", "v_inf", "t_sigma_f", "h",
        ], "data": [],
    }
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=lambda **_: cneos_payload,
        sbdb_fetch=lambda _: {"object": {}, "orbit": {}},
        sentry_fetch=None,
        put_raw=lambda k, b: None,
        sbdb_delay_sec=0.0,
    )
    assert snap.risk_rows == []
    assert all(s["kind"] != "sentry" for s in snap.manifest_entry["sources"])


# ---------------------------------------------------------------------------
# Load adapter: risk row with dates must survive psycopg's JSON adapter path
# (same regression coverage we added in test_load.py)
# ---------------------------------------------------------------------------


def test_normalized_risk_row_survives_json_adapter():
    """raw_row contains the original Sentry record, which has no dates.
    But the row itself has assessment_date and last_observed (date objects).
    Only raw_row is JSONB; the date fields are stored as DATE. So no JSON
    serialization should choke. This test asserts the row is well-shaped
    for the existing _adapt path."""
    import json as _json

    from etl.load import _adapt

    record = {"des": "1979 XB", "h": "18.5", "ts_max": "0",
              "ps_cum": "-2.69", "ip": "8.5e-7", "range": "2056-2113",
              "last_obs": "1979-12-15"}
    row = normalize_sentry_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    # raw_row is the JSONB column — adapt it and serialize with bare dumps
    adapted = _adapt(row["raw_row"])
    out = _json.dumps(adapted.obj)
    assert "1979 XB" in out
