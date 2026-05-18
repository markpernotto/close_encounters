"""Tests for the load layer that don't require a live DB.

Specifically targets serialization edge cases — psycopg's default JSON
encoder can't handle date/datetime objects, and our row dicts have plenty
of both. This test asserts that the Json wrapper we hand to psycopg uses
a dumps function that converts those to ISO strings.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import psycopg.types.json as psy_json

import etl.load  # noqa: F401 — import side-effect registers our dumps globally
from etl.load import _adapt, _json_dumps, _scrub_dates


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
    """A dict containing a date must round-trip through psycopg's actual
    Json adapter path without raising. We instantiate psycopg's own
    _JsonDumper to exercise the same flow CI hit — the global
    set_json_dumps() call inside etl.load must be in effect by import time."""
    payload = {"solution_date": date(2026, 5, 18), "spkid": "20099942"}
    adapted = _adapt(payload)
    dumper = psy_json._JsonDumper(dict, None)
    serialized = dumper.dump(adapted)
    assert b"2026-05-18" in serialized


def test_adapt_passes_through_non_json_values():
    assert _adapt(None) is None
    assert _adapt("hello") == "hello"
    assert _adapt(42) == 42
    assert _adapt(date(2026, 5, 18)) == date(2026, 5, 18)


# ---------------------------------------------------------------------------
# _scrub_dates — the suspenders path that works without set_json_dumps
# ---------------------------------------------------------------------------


def test_scrub_dates_converts_date_at_top_level():
    assert _scrub_dates(date(2026, 5, 18)) == "2026-05-18"


def test_scrub_dates_converts_datetime_at_top_level():
    assert _scrub_dates(datetime(2026, 5, 18, 6, 30, tzinfo=UTC)) == "2026-05-18T06:30:00+00:00"


def test_scrub_dates_walks_nested_dicts_and_lists():
    payload = {
        "outer": {"inner_date": date(2026, 5, 18), "name": "Apophis"},
        "list": [date(2026, 6, 1), datetime(2026, 6, 2, 12, 0, tzinfo=UTC)],
    }
    out = _scrub_dates(payload)
    assert out == {
        "outer": {"inner_date": "2026-05-18", "name": "Apophis"},
        "list": ["2026-06-01", "2026-06-02T12:00:00+00:00"],
    }


def test_scrub_dates_leaves_primitives_alone():
    assert _scrub_dates("hello") == "hello"
    assert _scrub_dates(42) == 42
    assert _scrub_dates(None) is None
    assert _scrub_dates(True) is True


def test_adapted_payload_is_json_safe_without_custom_dumps():
    """The critical guarantee: even if psycopg's encoder has zero awareness
    of dates, the adapted payload can be serialized by stock json.dumps.
    This is exactly the CI failure path — psycopg ends up calling the
    bare json.dumps (no default=). With _scrub_dates run beforehand, that
    call must succeed."""
    payload = {
        "solution_date": date(2026, 5, 18),
        "snapshot_date": date(2026, 5, 18),
        "first_observed": date(2004, 6, 19),
        "spkid": "20099942",
        "n_observations": 7370,
    }
    adapted = _adapt(payload)
    # Stock json.dumps with no kwargs — exactly what CI's psycopg hit
    out = json.dumps(adapted.obj)
    assert "2026-05-18" in out
    assert "2004-06-19" in out
    assert "20099942" in out
