"""NASA Sentry Impact Risk API client.

Endpoint: https://ssd-api.jpl.nasa.gov/sentry.api
Docs:     https://ssd-api.jpl.nasa.gov/doc/sentry.html

Public, no auth. The summary call returns the full Sentry list (~2000
objects) in one response — small enough to pull nightly without paging.

Each row carries: designation, internal Sentry id, Torino + Palermo scales,
cumulative impact probability, projected-impact year range, count of
impact scenarios, estimated diameter, velocity at infinity, last-observation
date. Most Sentry-tracked objects will not be in our 60-day CNEOS pull —
that is fine; the risk_assessments table is designation-keyed and the dbt
mart layer joins to dim_object where the spkid is known.
"""

from __future__ import annotations

from typing import Any

from etl._http import get_json

SENTRY_URL = "https://ssd-api.jpl.nasa.gov/sentry.api"


def fetch_sentry_summary_raw() -> dict[str, Any]:
    """Fetch the full Sentry summary payload (used by etl.extract for the
    R2 snapshot). Returns the raw JSON dict as JPL serves it."""
    return get_json(SENTRY_URL)


def fetch_sentry_summary() -> list[dict[str, Any]]:
    """Fetch the Sentry summary as a list of row dicts (the `data` array).

    Unlike CNEOS, Sentry rows are already dicts — no flatten step needed.
    """
    return _rows(fetch_sentry_summary_raw())


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or []
    # API returns data as a list of dicts directly when `fields` is empty
    # (which is the current default). Defensive: handle the legacy
    # column-oriented response as well, in case JPL switches formats.
    fields = payload.get("fields") or []
    if fields and data and isinstance(data[0], list):
        return [dict(zip(fields, row, strict=True)) for row in data]
    return list(data)
