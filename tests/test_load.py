"""Tests for the load layer that don't require a live DB.

Specifically targets serialization edge cases — psycopg's default JSON
encoder can't handle date/datetime objects, and our row dicts have plenty
of both. This test asserts that the Json wrapper we hand to psycopg uses
a dumps function that converts those to ISO strings.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from etl.load import _adapt, _json_dumps


def test_json_dumps_handles_date():
    out = _json_dumps({"d": date(2026, 5, 18)})
    assert out == '{"d": "2026-05-18"}'


def test_json_dumps_handles_datetime():
    dt = datetime(2026, 5, 18, 6, 30, tzinfo=UTC)
    out = _json_dumps({"t": dt})
    assert "2026-05-18 06:30:00+00:00" in out


def test_json_dumps_handles_nested_dates():
    payload = {
        "outer": {"inner_date": date(2026, 5, 18), "name": "Apophis"},
        "list": [date(2026, 6, 1), date(2026, 6, 2)],
    }
    out = _json_dumps(payload)
    assert "2026-05-18" in out
    assert "2026-06-01" in out
    assert "Apophis" in out


def test_adapt_wraps_dict_with_date_safe_dumps():
    """A dict containing a date must round-trip through psycopg's Json
    adapter without raising. We exercise the adapter's dumps callable
    directly because we don't want to require a live DB connection."""
    payload = {"solution_date": date(2026, 5, 18), "spkid": "20099942"}
    adapted = _adapt(payload)
    # psycopg.types.json.Json exposes the wrapped object via the public
    # `.obj` attribute; serializing through the dumps we installed must
    # succeed and emit an ISO date.
    serialized = adapted.dumps(adapted.obj)
    assert "2026-05-18" in serialized


def test_adapt_passes_through_non_json_values():
    assert _adapt(None) is None
    assert _adapt("hello") == "hello"
    assert _adapt(42) == 42
    assert _adapt(date(2026, 5, 18)) == date(2026, 5, 18)
