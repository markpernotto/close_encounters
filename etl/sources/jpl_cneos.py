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


def fetch_close_approaches(
    *,
    date_min: str,
    date_max: str,
    dist_max_au: float = 0.05,
    body: str = "Earth",
) -> list[dict[str, Any]]:
    """Fetch close approaches in [date_min, date_max] within dist_max AU of body.

    Args:
        date_min: ISO date or "now".
        date_max: ISO date.
        dist_max_au: maximum approach distance in AU. 0.05 AU ≈ 19.5 LD.
        body: target body, default "Earth". CNEOS supports Mars, Moon, etc.

    Returns:
        A list of row dicts with keys matching CNEOS field names: des,
        orbit_id, jd, cd, dist, dist_min, dist_max, v_rel, v_inf,
        t_sigma_f, h.
    """
    params: dict[str, str | int | float] = {
        "date-min": date_min,
        "date-max": date_max,
        "dist-max": dist_max_au,
        "body": body,
    }
    payload = get_json(CAD_URL, params=params)
    return _flatten(payload)


def _flatten(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert CNEOS's column-oriented response into row dicts."""
    fields: list[str] = payload.get("fields") or []
    rows: list[list[Any]] = payload.get("data") or []
    return [dict(zip(fields, row, strict=True)) for row in rows]
