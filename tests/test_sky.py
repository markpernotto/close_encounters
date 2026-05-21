"""Tests for Phase 4 sky-position math + the /api/sky endpoint.

The orbital-element extraction and orbit construction are pure (orbit
construction needs only skyfield's bundled timescale, no ephemeris
download). The alt/az computation needs the DE421 ephemeris; those tests
skip gracefully when the file isn't present locally (e.g. in CI without
the cache). The endpoint test monkeypatches the heavy math so it always
runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import sky as sky_math
from api.index import app, get_conn
from api.sky import _DATA_DIR, EPHEMERIS_FILE, _extract_elements, build_orbit

FIXTURES = Path(__file__).parent / "fixtures"
WHEN = datetime(2026, 5, 20, 8, 0, 0, tzinfo=UTC)


def _ephemeris_present() -> bool:
    # Check for the file on disk WITHOUT triggering a 17MB download.
    return (_DATA_DIR / EPHEMERIS_FILE).exists()


requires_ephemeris = pytest.mark.skipif(
    not _ephemeris_present(),
    reason="DE421 ephemeris not cached locally",
)


# Apophis osculating elements (from the committed SBDB fixture)
def _apophis_elements() -> dict[str, float]:
    sbdb = json.loads((FIXTURES / "sbdb_apophis.json").read_text())
    els = {e["name"]: float(e["value"]) for e in sbdb["orbit"]["elements"]}
    return {
        "a_au": els["a"],
        "e": els["e"],
        "i_deg": els["i"],
        "om_deg": els["om"],
        "w_deg": els["w"],
        "ma_deg": els["ma"],
        "epoch_jd": float(sbdb["orbit"]["epoch"]),
    }


# ---------------------------------------------------------------------------
# _extract_elements — pure
# ---------------------------------------------------------------------------


def test_extract_elements_pulls_all_seven():
    row = {
        "semi_major_axis_au": 0.92,
        "eccentricity": 0.19,
        "inclination_deg": 3.34,
        "longitude_ascending_node_deg": 203.9,
        "argument_perihelion_deg": 126.7,
        "mean_anomaly_deg": 312.8,
        "latest_epoch_jd": 2461000.5,
    }
    out = _extract_elements(row)
    assert out == {
        "a_au": 0.92,
        "e": 0.19,
        "i_deg": 3.34,
        "om_deg": 203.9,
        "w_deg": 126.7,
        "ma_deg": 312.8,
        "epoch_jd": 2461000.5,
    }


def test_extract_elements_returns_none_when_any_missing():
    row = {
        "semi_major_axis_au": 0.92,
        "eccentricity": 0.19,
        "inclination_deg": 3.34,
        "longitude_ascending_node_deg": 203.9,
        "argument_perihelion_deg": 126.7,
        "mean_anomaly_deg": None,  # missing
        "latest_epoch_jd": 2461000.5,
    }
    assert _extract_elements(row) is None


# ---------------------------------------------------------------------------
# build_orbit — pure (timescale only, no ephemeris)
# ---------------------------------------------------------------------------


def test_build_orbit_returns_orbit_object():
    orbit = build_orbit(**_apophis_elements(), name="Apophis")
    # The orbit should expose an `at()` method (skyfield VectorFunction)
    assert hasattr(orbit, "at")


# ---------------------------------------------------------------------------
# compute_altaz — needs ephemeris
# ---------------------------------------------------------------------------


@requires_ephemeris
def test_compute_altaz_returns_valid_ranges():
    pos = sky_math.compute_altaz(
        **_apophis_elements(), lat=31.96, lon=-111.60, when=WHEN, name="Apophis"
    )
    assert -90.0 <= pos["altitude_deg"] <= 90.0
    assert 0.0 <= pos["azimuth_deg"] < 360.0
    assert pos["distance_au"] > 0
    assert pos["above_horizon"] == (pos["altitude_deg"] > 0)


@requires_ephemeris
def test_compute_altaz_is_deterministic():
    args = dict(**_apophis_elements(), lat=31.96, lon=-111.60, when=WHEN)
    a = sky_math.compute_altaz(**args)
    b = sky_math.compute_altaz(**args)
    assert a == b


@requires_ephemeris
def test_compute_altaz_differs_by_location():
    """Same object + time, different hemisphere → different altitude.
    A southern-hemisphere observer sees a different sky."""
    els = _apophis_elements()
    north = sky_math.compute_altaz(**els, lat=51.5, lon=0.0, when=WHEN)  # London
    south = sky_math.compute_altaz(**els, lat=-33.9, lon=151.2, when=WHEN)  # Sydney
    assert north["altitude_deg"] != south["altitude_deg"]


@requires_ephemeris
def test_objects_above_horizon_skips_incomplete_and_sorts():
    full = {
        "spkid": "20099942",
        "designation": "99942",
        "semi_major_axis_au": _apophis_elements()["a_au"],
        "eccentricity": _apophis_elements()["e"],
        "inclination_deg": _apophis_elements()["i_deg"],
        "longitude_ascending_node_deg": _apophis_elements()["om_deg"],
        "argument_perihelion_deg": _apophis_elements()["w_deg"],
        "mean_anomaly_deg": _apophis_elements()["ma_deg"],
        "latest_epoch_jd": _apophis_elements()["epoch_jd"],
    }
    incomplete = {"spkid": "X", "designation": "incomplete", "eccentricity": 0.5}
    out = sky_math.objects_above_horizon(
        [full, incomplete], lat=31.96, lon=-111.6, when=WHEN, min_altitude_deg=-90
    )
    # Incomplete object is skipped; full object is placed
    assert len(out) == 1
    assert out[0]["spkid"] == "20099942"
    assert "altitude_deg" in out[0]


# ---------------------------------------------------------------------------
# /api/sky endpoint — monkeypatch the math so it runs without an ephemeris
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, row_factory=None):
        return _FakeCursor(self._rows)

    def close(self):
        pass


def teardown_function(_func):
    app.dependency_overrides.clear()


def test_sky_endpoint_returns_placed_objects(monkeypatch):
    placed = [
        {
            "spkid": "20099942",
            "designation": "99942",
            "full_name": "99942 Apophis",
            "orbit_class": "ATE",
            "neo": True,
            "pha": True,
            "diameter_km": 0.34,
            "altitude_deg": 42.5,
            "azimuth_deg": 180.0,
            "distance_au": 0.5,
            "above_horizon": True,
        }
    ]
    monkeypatch.setattr(sky_math, "objects_above_horizon", lambda *a, **k: placed)

    def gen():
        yield _FakeConn([{"spkid": "20099942"}])

    app.dependency_overrides[get_conn] = gen
    client = TestClient(app)
    resp = client.get("/api/sky?lat=31.96&lon=-111.60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latitude"] == 31.96
    assert body["count"] == 1
    assert body["objects"][0]["designation"] == "99942"
    assert body["objects"][0]["altitude_deg"] == 42.5


def test_sky_endpoint_rejects_bad_latitude():
    def gen():
        yield _FakeConn([])

    app.dependency_overrides[get_conn] = gen
    client = TestClient(app)
    resp = client.get("/api/sky?lat=200&lon=0")
    assert resp.status_code == 422


def test_sky_endpoint_rejects_bad_time(monkeypatch):
    monkeypatch.setattr(sky_math, "objects_above_horizon", lambda *a, **k: [])

    def gen():
        yield _FakeConn([])

    app.dependency_overrides[get_conn] = gen
    client = TestClient(app)
    resp = client.get("/api/sky?lat=0&lon=0&time=not-a-time")
    assert resp.status_code == 422
