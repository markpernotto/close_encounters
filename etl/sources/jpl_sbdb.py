"""JPL Small-Body Database (SBDB) API client.

Endpoint: https://ssd-api.jpl.nasa.gov/sbdb.api  (single-object lookup)
Docs:     https://ssd-api.jpl.nasa.gov/doc/sbdb.html

Public, no auth. Single-object lookup is the path used to enrich CNEOS
close-approach rows with physical and orbital metadata. The Query API
(sbdb_query.api) is a separate batch endpoint, added later.
"""

from __future__ import annotations

from typing import Any

from etl._http import get_json

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"


def lookup_object(
    designation: str,
    *,
    full_precision: bool = True,
    physical_parameters: bool = True,
    discovery: bool = True,
) -> dict[str, Any]:
    """Fetch full SBDB record for a single object.

    Args:
        designation: e.g. "99942" or "Apophis" or "2024 YR4". SBDB resolves
            most natural designations including SPK-IDs.
        full_precision: include full-precision orbital elements.
        physical_parameters: include phys_par array.
        discovery: include discovery dict.

    Returns:
        The full SBDB JSON response with top-level keys
        {object, signature, orbit, phys_par, discovery}.
    """
    params: dict[str, str | int | float] = {"des": designation}
    if full_precision:
        params["full-prec"] = "true"
    if physical_parameters:
        params["phys-par"] = "true"
    if discovery:
        params["discovery"] = "true"
    return get_json(SBDB_URL, params=params)
