"""Smoke tests for the FastAPI app.

Uses FastAPI dependency overrides to inject a fake DB connection that
returns hardcoded rows. Verifies routing, response shapes, query
parameter validation, and 404 handling. Real SQL is integration-tested
separately against docker-compose Postgres.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.index import app, get_conn

SNAPSHOT_DATE = date(2026, 5, 12)
APPROACH = datetime(2026, 6, 1, 12, 27, tzinfo=UTC)
FIRED_AT = datetime(2026, 5, 12, 6, 31, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fake DB plumbing
# ---------------------------------------------------------------------------


class FakeConn:
    """One scripted list of results, shared across all cursors opened on
    this connection. Each execute() advances the shared index by one."""

    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = scripted
        self._idx = -1

    def cursor(self, row_factory: Any = None) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        pass


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_a) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn._idx += 1
        self.executed.append((sql, params))

    def fetchone(self) -> Any:
        result = self._conn._scripted[self._conn._idx]
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def fetchall(self) -> list[Any]:
        result = self._conn._scripted[self._conn._idx]
        if isinstance(result, list):
            return result
        return [result] if result else []


def make_client(scripted: list[Any]) -> TestClient:
    """Override the get_conn dependency with a fake that scripts result sets."""

    def fake_get_conn():
        yield FakeConn(scripted)

    app.dependency_overrides[get_conn] = fake_get_conn
    return TestClient(app)


def teardown_function(_func) -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_returns_latest_snapshot_date():
    client = make_client([(SNAPSHOT_DATE,)])
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["latest_snapshot_date"] == "2026-05-12"


def test_health_handles_empty_db():
    client = make_client([(None,)])
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["latest_snapshot_date"] is None


# ---------------------------------------------------------------------------
# /api/approaches/upcoming
# ---------------------------------------------------------------------------


def approach_row(**overrides) -> dict[str, Any]:
    base = {
        "spkid": "20099942",
        "designation": "99942",
        "full_name": "99942 Apophis (2004 MN4)",
        "approach_date": APPROACH,
        "body": "Earth",
        "distance_au": 0.045,
        "distance_ld": 17.5,
        "distance_min_au": 0.044,
        "distance_max_au": 0.046,
        "v_rel_km_s": 10.7,
        "v_inf_km_s": 10.6,
        "orbit_id": "42",
        "diameter_estimate_km": 0.340,
        "absolute_magnitude_h": 19.7,
        "orbit_class": "ATE",
    }
    base.update(overrides)
    return base


def test_upcoming_returns_list_with_count_and_snapshot():
    scripted = [
        {"d": SNAPSHOT_DATE},                            # MAX(snapshot_date)
        [approach_row(), approach_row(designation="X")], # the main query
    ]
    client = make_client(scripted)
    resp = client.get("/api/approaches/upcoming?days=60&limit=200")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["window_days"] == 60
    assert body["snapshot_date"] == "2026-05-12"
    assert body["items"][0]["designation"] == "99942"
    assert body["items"][0]["distance_ld"] == 17.5


def test_upcoming_returns_empty_when_no_snapshot():
    scripted = [{"d": None}]
    client = make_client(scripted)
    resp = client.get("/api/approaches/upcoming")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["snapshot_date"] is None


def test_upcoming_rejects_out_of_range_days():
    client = make_client([])
    resp = client.get("/api/approaches/upcoming?days=400")
    assert resp.status_code == 422


def test_upcoming_rejects_out_of_range_limit():
    client = make_client([])
    resp = client.get("/api/approaches/upcoming?limit=0")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/approaches/recent
# ---------------------------------------------------------------------------


def test_recent_uses_default_window():
    scripted = [{"d": SNAPSHOT_DATE}, [approach_row()]]
    client = make_client(scripted)
    resp = client.get("/api/approaches/recent")
    assert resp.status_code == 200
    assert resp.json()["window_days"] == 30


# ---------------------------------------------------------------------------
# /api/objects/{designation}
# ---------------------------------------------------------------------------


def object_row(**overrides) -> dict[str, Any]:
    base = {
        "snapshot_date": SNAPSHOT_DATE,
        "spkid": "20099942",
        "designation": "99942",
        "full_name": "99942 Apophis (2004 MN4)",
        "neo": True,
        "pha": True,
        "orbit_class": "ATE",
        "absolute_magnitude_h": 19.7,
        "diameter_km": 0.340,
        "diameter_estimate_km": 0.340,
        "albedo": 0.23,
        "rotation_period_h": 30.4,
        "spec_class": "Sq",
        "first_observed": date(2004, 6, 19),
        "last_observed": date(2024, 3, 1),
        "observation_arc_days": 7196,
        "n_observations": 7370,
        "solution_date": date(2024, 6, 25),
    }
    base.update(overrides)
    return base


def test_get_object_returns_detail():
    scripted = [object_row()]
    client = make_client(scripted)
    resp = client.get("/api/objects/99942")
    assert resp.status_code == 200
    body = resp.json()
    assert body["spkid"] == "20099942"
    assert body["neo"] is True
    assert body["orbit_class"] == "ATE"


def test_get_object_404_when_not_found():
    scripted = [None]
    client = make_client(scripted)
    resp = client.get("/api/objects/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/objects/{designation}/approaches
# ---------------------------------------------------------------------------


def test_get_object_approaches_404_when_object_missing():
    scripted = [None]  # _fetch_object returns nothing
    client = make_client(scripted)
    resp = client.get("/api/objects/missing/approaches")
    assert resp.status_code == 404


def test_get_object_approaches_returns_list():
    # 1) _fetch_object lookup, 2) the approaches query
    scripted = [object_row(), [approach_row(), approach_row(distance_ld=12.0)]]
    client = make_client(scripted)
    resp = client.get("/api/objects/99942/approaches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["snapshot_date"] == "2026-05-12"


# ---------------------------------------------------------------------------
# /api/alerts
# ---------------------------------------------------------------------------


def alert_row(**overrides) -> dict[str, Any]:
    base = {
        "alert_id": 1,
        "fired_at": FIRED_AT,
        "rule_id": "size_and_distance",
        "spkid": "20099942",
        "designation": "(99942) Apophis",
        "approach_date": APPROACH,
        "rationale": "diameter ~340m, distance 0.80 LD on 2026-06-01",
        "payload": {"diameter_km": 0.340, "distance_ld": 0.80},
    }
    base.update(overrides)
    return base


def test_alerts_returns_list_default_limit():
    scripted = [[alert_row(), alert_row(alert_id=2, rule_id="very_close_any_size")]]
    client = make_client(scripted)
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    rule_ids = [item["rule_id"] for item in body["items"]]
    assert "size_and_distance" in rule_ids
    assert "very_close_any_size" in rule_ids


def test_alerts_with_rule_filter():
    scripted = [[alert_row()]]
    client = make_client(scripted)
    resp = client.get("/api/alerts?rule_id=size_and_distance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["rule_id"] == "size_and_distance"


def test_alerts_handles_empty():
    scripted = [[]]
    client = make_client(scripted)
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
