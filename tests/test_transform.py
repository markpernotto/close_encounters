"""Tests for etl.transform — runs against committed fixtures, no network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etl.sources.jpl_cneos import _flatten
from etl.transform import (
    AU_IN_LD,
    normalize_close_approach,
    normalize_sbdb_object,
    normalize_sbdb_orbit_elements,
)

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT_DATE = date(2026, 5, 8)
RETRIEVED_AT = datetime(2026, 5, 8, 6, 30, tzinfo=UTC)


@pytest.fixture
def cneos_rows() -> list[dict]:
    payload = json.loads((FIXTURES / "cneos_sample.json").read_text())
    return _flatten(payload)


@pytest.fixture
def sbdb_apophis() -> dict:
    return json.loads((FIXTURES / "sbdb_apophis.json").read_text())


# ---------------------------------------------------------------------------
# CNEOS close-approach normalization
# ---------------------------------------------------------------------------


def test_cneos_flatten_produces_row_dicts(cneos_rows):
    assert len(cneos_rows) >= 1
    first = cneos_rows[0]
    assert {"des", "cd", "dist", "v_rel", "h"} <= first.keys()


def test_cneos_normalize_first_row_shape(cneos_rows):
    row = normalize_close_approach(
        cneos_rows[0],
        snapshot_date=SNAPSHOT_DATE,
        spkid=None,
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["snapshot_date"] == SNAPSHOT_DATE
    assert row["spkid"] is None  # caller fills this in via objects_snapshots
    assert row["body"] == "Earth"
    assert isinstance(row["approach_date"], datetime)
    assert row["approach_date"].tzinfo is UTC
    assert isinstance(row["distance_au"], float)
    assert row["distance_au"] > 0
    # distance_ld must be derived from distance_au by AU_IN_LD
    assert row["distance_ld"] == pytest.approx(row["distance_au"] * AU_IN_LD)
    assert row["raw_row"] is cneos_rows[0]
    assert row["source_retrieved_at"] == RETRIEVED_AT
    # orbit_id is captured for revision detection in etl.diff
    assert row["orbit_id"] == cneos_rows[0]["orbit_id"]


def test_cneos_normalize_handles_missing_optional_fields():
    minimal_row = {"des": "TEST", "cd": "2026-Jun-01 00:00", "dist": "0.0123"}
    row = normalize_close_approach(
        minimal_row,
        snapshot_date=SNAPSHOT_DATE,
        spkid="20099942",
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["distance_min_au"] is None
    assert row["distance_max_au"] is None
    assert row["v_rel_km_s"] is None
    assert row["v_inf_km_s"] is None
    assert row["spkid"] == "20099942"


def test_cneos_normalize_parses_cad_datetime():
    row = normalize_close_approach(
        {"des": "X", "cd": "2026-May-08 12:27", "dist": "0.045"},
        snapshot_date=SNAPSHOT_DATE,
        spkid=None,
        source_retrieved_at=RETRIEVED_AT,
    )
    assert row["approach_date"] == datetime(2026, 5, 8, 12, 27, tzinfo=UTC)


# ---------------------------------------------------------------------------
# SBDB object + orbit-elements normalization
# ---------------------------------------------------------------------------


def test_sbdb_object_normalizes_apophis_identifiers(sbdb_apophis):
    row = normalize_sbdb_object(sbdb_apophis, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT)
    assert row["spkid"] == "20099942"
    assert row["designation"] == "99942"
    assert "Apophis" in row["full_name"]
    assert row["neo"] is True
    assert row["pha"] is True
    assert row["orbit_class"] == "ATE"


def test_sbdb_object_carries_provenance(sbdb_apophis):
    row = normalize_sbdb_object(sbdb_apophis, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT)
    assert row["source_url"].endswith("sbdb.api")
    assert row["source_retrieved_at"] == RETRIEVED_AT
    assert len(row["source_checksum"]) == 64  # sha256 hex
    assert row["extraction_version"]


def test_sbdb_object_extracts_observation_arc(sbdb_apophis):
    row = normalize_sbdb_object(sbdb_apophis, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT)
    assert isinstance(row["observation_arc_days"], int)
    assert row["observation_arc_days"] > 1000  # Apophis has been tracked since 2004
    assert isinstance(row["n_observations"], int)
    assert row["n_observations"] > 1000


def test_sbdb_orbit_elements_indexes_apophis_e_a_i(sbdb_apophis):
    row = normalize_sbdb_orbit_elements(sbdb_apophis, source_retrieved_at=RETRIEVED_AT)
    assert row["spkid"] == "20099942"
    # Apophis's eccentricity is ~0.19; semi-major axis ~0.92 AU; inclination ~3.3°
    assert row["e"] == pytest.approx(0.19, abs=0.05)
    assert row["a"] == pytest.approx(0.92, abs=0.05)
    assert row["i"] == pytest.approx(3.3, abs=0.5)
    # Sigmas should be positive and very small for a well-tracked object
    assert row["sigma_e"] is not None and row["sigma_e"] > 0
    assert row["sigma_a"] is not None and row["sigma_a"] > 0


def test_sbdb_solution_date_is_a_date(sbdb_apophis):
    obj_row = normalize_sbdb_object(sbdb_apophis, snapshot_date=SNAPSHOT_DATE, source_retrieved_at=RETRIEVED_AT)
    orb_row = normalize_sbdb_orbit_elements(sbdb_apophis, source_retrieved_at=RETRIEVED_AT)
    assert isinstance(obj_row["solution_date"], date)
    assert obj_row["solution_date"] == orb_row["solution_date"]
