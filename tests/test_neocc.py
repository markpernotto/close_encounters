"""Tests for the ESA NEOCC source + transform path."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etl.sources.esa_neocc import (
    _normalize_designation,
    _split_designation_and_name,
    parse_risk_list_text,
)
from etl.transform import (
    AGENCY_ESA_NEOCC,
    NEOCC_RISK_LIST_URL,
    _risk_class_for_neocc,
    normalize_neocc_assessment,
)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_DATE = date(2026, 5, 19)
RETRIEVED_AT = datetime(2026, 5, 19, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Designation normalization — provisional designations get a space inserted
# ---------------------------------------------------------------------------


def test_normalize_inserts_space_in_provisional_designation():
    assert _normalize_designation("2023VD3") == "2023 VD3"
    assert _normalize_designation("1979XB") == "1979 XB"
    assert _normalize_designation("2024YR4") == "2024 YR4"


def test_normalize_leaves_numbered_asteroids_alone():
    assert _normalize_designation("99942") == "99942"
    assert _normalize_designation("101955") == "101955"


def test_normalize_handles_unknown_formats_unchanged():
    assert _normalize_designation("C/2023 A3") == "C/2023 A3"
    assert _normalize_designation("") == ""


def test_split_handles_designation_only_cell():
    assert _split_designation_and_name("2023VD3") == ("2023 VD3", "")


def test_split_handles_numbered_with_name():
    assert _split_designation_and_name("99942 Apophis") == ("99942", "Apophis")


def test_split_handles_parenthesized_numbered_with_name():
    assert _split_designation_and_name("(99942) Apophis") == ("99942", "Apophis")


def test_split_handles_empty_cell():
    assert _split_designation_and_name("") == ("", "")


# ---------------------------------------------------------------------------
# parse_risk_list_text — against the real fixture + a synthetic minimal case
# ---------------------------------------------------------------------------


@pytest.fixture
def neocc_text() -> str:
    return (FIXTURES / "neocc_risk_list.txt").read_text()


def test_parse_skips_four_header_lines_and_returns_rows(neocc_text):
    rows = parse_risk_list_text(neocc_text)
    # The fixture has ~1977 data rows; loose lower bound for stability
    assert len(rows) > 500
    first = rows[0]
    assert {"designation", "diameter_m", "ip_max", "ps_max", "ts",
            "v_inf", "years", "ip_cum", "ps_cum"} <= first.keys()


def test_parse_yields_normalized_designations(neocc_text):
    rows = parse_risk_list_text(neocc_text)
    designations = [r["designation"] for r in rows]
    # No provisional designations should be missing their space
    bad = [d for d in designations if len(d) >= 4 and d[:4].isdigit() and " " not in d and d[4:].isalpha()]
    assert bad == [], f"unnormalized designations: {bad[:5]}"


def test_parse_handles_minimal_synthetic_input():
    text = (
        "Last Update: 2026-05-19 14:54 UTC\n"
        "header line 1\n"
        "header line 2\n"
        "format placeholder line\n"
        "2023VD3                       |   14 |    *    | 2034-11-08 17:08 |  2.35E-3 |  -2.67 |  0 |   21.01  | 2034-2039 |  2.35E-3 |  -2.67 |\n"
        "1979XB                        |  500 |    *    | 2056-12-12 21:38 |  2.34E-7 |  -2.82 |  0 |   27.54  | 2056-2113 |  7.34E-7 |  -2.70 |\n"
    )
    rows = parse_risk_list_text(text)
    assert len(rows) == 2
    assert rows[0]["designation"] == "2023 VD3"
    assert rows[0]["diameter_m"] == "14"
    assert rows[0]["ts"] == "0"
    assert rows[0]["ip_cum"] == "2.35E-3"
    assert rows[1]["designation"] == "1979 XB"


def test_parse_skips_malformed_lines():
    text = (
        "Last Update: x\n"
        "h1\nh2\nh3\n"
        "good | data | here | with | enough | pipes | for | a | full | row | of | cells\n"
        "too short | only | a | few\n"
        "\n"
    )
    rows = parse_risk_list_text(text)
    # Only the row with ≥11 cells is kept
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# normalize_neocc_assessment — the row-shape contract
# ---------------------------------------------------------------------------


def _sample_record():
    return {
        "designation": "2023 VD3",
        "name": "",
        "diameter_m": "14",
        "sig": "*",
        "vi_max_date": "2034-11-08 17:08",
        "ip_max": "2.35E-3",
        "ps_max": "-2.67",
        "ts": "0",
        "v_inf": "21.01",
        "years": "2034-2039",
        "ip_cum": "2.35E-3",
        "ps_cum": "-2.67",
    }


def test_normalize_returns_risk_assessments_row():
    row = normalize_neocc_assessment(
        _sample_record(),
        snapshot_date=SNAPSHOT_DATE,
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["agency"] == AGENCY_ESA_NEOCC
    assert row["designation"] == "2023 VD3"
    assert row["assessment_date"] == SNAPSHOT_DATE
    assert row["source_url"] == NEOCC_RISK_LIST_URL
    assert row["source_retrieved_at"] == RETRIEVED_AT
    assert row["torino_scale"] == 0
    assert row["palermo_scale"] == -2.67
    assert row["palermo_scale_max"] == -2.67
    assert row["impact_probability"] == 2.35e-3
    assert row["v_inf_km_s"] == 21.01


def test_normalize_converts_diameter_meters_to_km():
    row = normalize_neocc_assessment(
        _sample_record(),
        snapshot_date=SNAPSHOT_DATE,
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["diameter_km"] == 0.014  # 14 m → 0.014 km


def test_normalize_parses_year_range_into_min_max():
    row = normalize_neocc_assessment(
        _sample_record(),
        snapshot_date=SNAPSHOT_DATE,
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["potential_impact_year_min"] == 2034
    assert row["potential_impact_year_max"] == 2039


def test_normalize_handles_missing_optional_fields():
    record = {"designation": "Test", "ts": "0", "ps_cum": "-10",
              "ip_cum": "0", "v_inf": ""}
    row = normalize_neocc_assessment(
        record, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT
    )
    assert row["diameter_km"] is None
    assert row["v_inf_km_s"] is None
    assert row["potential_impact_year_min"] is None
    assert row["potential_impact_year_max"] is None
    assert row["n_impacts"] is None
    assert row["energy_mt"] is None
    assert row["absolute_magnitude_h"] is None
    assert row["last_observed"] is None


def test_normalize_carries_supplied_spkid():
    row = normalize_neocc_assessment(
        _sample_record(),
        snapshot_date=SNAPSHOT_DATE,
        source_retrieved_at=RETRIEVED_AT,
        spkid="54123456",
    )
    assert row["spkid"] == "54123456"


# ---------------------------------------------------------------------------
# Risk-class bucketing parity with Sentry
# ---------------------------------------------------------------------------


def test_risk_class_torino_label_for_elevated():
    assert _risk_class_for_neocc({"ts": "2"}) == "torino_2"


def test_risk_class_palermo_elevated_when_above_minus_two():
    assert _risk_class_for_neocc({"ts": "0", "ps_cum": "-1.5"}) == "palermo_elevated"


def test_risk_class_background_when_palermo_well_negative():
    assert _risk_class_for_neocc({"ts": "0", "ps_cum": "-6.0"}) == "background"


# ---------------------------------------------------------------------------
# End-to-end: gather_snapshot wires NEOCC through alongside Sentry
# ---------------------------------------------------------------------------


def test_gather_snapshot_includes_neocc_rows_and_manifest():
    from etl.extract import gather_snapshot

    cneos_payload = {
        "signature": {}, "count": 0, "fields": [
            "des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max",
            "v_rel", "v_inf", "t_sigma_f", "h",
        ], "data": [],
    }
    neocc_text = (
        "Last Update: 2026-05-19 14:54 UTC\n"
        "h1\nh2\nh3\n"
        "2023VD3                       |   14 |    *    | 2034-11-08 17:08 |  2.35E-3 |  -2.67 |  0 |   21.01  | 2034-2039 |  2.35E-3 |  -2.67 |\n"
        "1979XB                        |  500 |    *    | 2056-12-12 21:38 |  2.34E-7 |  -2.82 |  0 |   27.54  | 2056-2113 |  7.34E-7 |  -2.70 |\n"
    )
    uploads: list[tuple[str, bytes]] = []
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=lambda **_: cneos_payload,
        sbdb_fetch=lambda _: {"object": {}, "orbit": {}},
        sentry_fetch=None,
        neocc_fetch=lambda: neocc_text,
        put_raw=lambda k, b: uploads.append((k, b)),
        sbdb_delay_sec=0.0,
    )
    assert len(snap.risk_rows) == 2
    assert all(r["agency"] == AGENCY_ESA_NEOCC for r in snap.risk_rows)
    assert any(k.endswith("/neocc_risk_list.txt") for k, _ in uploads)
    kinds = [s["kind"] for s in snap.manifest_entry["sources"]]
    assert "neocc" in kinds


def test_gather_snapshot_combines_sentry_and_neocc_risk_rows():
    """Both agencies populate risk_rows when both fetchers are wired."""
    from etl.extract import gather_snapshot
    from etl.transform import AGENCY_NASA_SENTRY

    cneos_payload = {
        "signature": {}, "count": 0, "fields": [
            "des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max",
            "v_rel", "v_inf", "t_sigma_f", "h",
        ], "data": [],
    }
    sentry_payload = {
        "signature": {"source": "NASA/JPL Sentry Data API"},
        "count": 1,
        "data": [{"des": "2023 VD3", "id": "x", "h": "26.5",
                  "diameter": "0.014", "n_imp": 1, "ip": "2.35e-3",
                  "ps_max": "-2.67", "ps_cum": "-2.67", "ts_max": "0",
                  "v_inf": "21.01", "range": "2034-2039",
                  "last_obs": "2024-01-01", "fullname": "(2023 VD3)"}],
    }
    neocc_text = (
        "Last Update: 2026-05-19 14:54 UTC\nh1\nh2\nh3\n"
        "2023VD3                       |   14 |    *    | 2034-11-08 17:08 |  2.35E-3 |  -2.67 |  0 |   21.01  | 2034-2039 |  2.35E-3 |  -2.67 |\n"
    )
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=lambda **_: cneos_payload,
        sbdb_fetch=lambda _: {"object": {}, "orbit": {}},
        sentry_fetch=lambda: sentry_payload,
        neocc_fetch=lambda: neocc_text,
        put_raw=lambda k, b: None,
        sbdb_delay_sec=0.0,
    )
    agencies = {r["agency"] for r in snap.risk_rows}
    assert agencies == {AGENCY_NASA_SENTRY, AGENCY_ESA_NEOCC}
    # Same designation appears under both agencies — the cross-agency
    # reconciliation story in microcosm
    by_des: dict[str, set[str]] = {}
    for r in snap.risk_rows:
        by_des.setdefault(r["designation"], set()).add(r["agency"])
    assert "2023 VD3" in by_des
    assert by_des["2023 VD3"] == {AGENCY_NASA_SENTRY, AGENCY_ESA_NEOCC}
