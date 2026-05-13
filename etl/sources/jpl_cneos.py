"""JPL CNEOS Close-Approach Data API client.

Endpoint: https://ssd-api.jpl.nasa.gov/cad.api
Docs:     https://ssd-api.jpl.nasa.gov/doc/cad.html

Public, no auth. We send a polite User-Agent. Single request per day in the
nightly pipeline; the API supports paginated date ranges so we do not need
to hammer it.
"""

from __future__ import annotations

from typing import Any

from etl._http import get_json

CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"


def fetch_close_approaches_raw(
    *,
    date_min: str,
    date_max: str,
    dist_max_au: float = 0.05,
    body: str = "Earth",
) -> dict[str, Any]:
    """Fetch the full CNEOS payload (signature + fields + data + count).

    Used by etl.extract to snapshot the raw response to R2 with provenance.
    Other callers should prefer fetch_close_approaches() which returns
    flattened row dicts.
    """
    params: dict[str, str | int | float] = {
        "date-min": date_min,
        "date-max": date_max,
        "dist-max": dist_max_au,
        "body": body,
    }
    return get_json(CAD_URL, params=params)


def fetch_close_approaches(
    *,
    date_min: str,
    date_max: str,
    dist_max_au: float = 0.05,
    body: str = "Earth",
) -> list[dict[str, Any]]:
    """Fetch close approaches in [date_min, date_max] within dist_max AU of body.

    Returns row dicts with keys matching CNEOS field names: des, orbit_id,
    jd, cd, dist, dist_min, dist_max, v_rel, v_inf, t_sigma_f, h.
    """
    return _flatten(
        fetch_close_approaches_raw(
            date_min=date_min, date_max=date_max, dist_max_au=dist_max_au, body=body
        )
    )


def _flatten(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert CNEOS's column-oriented response into row dicts."""
    fields: list[str] = payload.get("fields") or []
    rows: list[list[Any]] = payload.get("data") or []
    return [dict(zip(fields, row, strict=True)) for row in rows]
