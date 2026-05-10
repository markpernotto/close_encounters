"""Normalize raw source records into our schema's row shape.

Pure functions, no I/O. Input: parsed JSON from etl.sources.*. Output:
dicts whose keys match columns in etl/schema.sql. The load layer is
responsible for inserting these into Postgres.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from etl.sources.jpl_sbdb import SBDB_URL

EXTRACTION_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# CNEOS close-approach rows → close_approaches_snapshots
# ---------------------------------------------------------------------------

# 1 AU expressed in lunar distances (mean Earth-Moon distance = 384,400 km;
# 1 AU = 149,597,870.7 km), used to derive distance_ld from distance_au.
AU_IN_LD = 149_597_870.7 / 384_400.0


def normalize_close_approach(
    cneos_row: dict[str, Any],
    *,
    snapshot_date: date,
    spkid: str | None,
    source_retrieved_at: datetime,
) -> dict[str, Any]:
    """Map a CNEOS row dict to a close_approaches_snapshots record.

    spkid is required by the table's primary key but CNEOS only returns the
    designation; load.py is responsible for joining to objects_snapshots to
    fill it in. Here we accept None and let the caller resolve it.
    """
    designation = str(cneos_row["des"])
    distance_au = float(cneos_row["dist"])
    return {
        "snapshot_date": snapshot_date,
        "spkid": spkid,
        "designation": designation,
        "approach_date": _parse_cad_datetime(cneos_row["cd"]),
        "body": "Earth",  # CAD `body` param is request-side; rows don't echo it
        "distance_au": distance_au,
        "distance_ld": distance_au * AU_IN_LD,
        "distance_min_au": _maybe_float(cneos_row.get("dist_min")),
        "distance_max_au": _maybe_float(cneos_row.get("dist_max")),
        "v_rel_km_s": _maybe_float(cneos_row.get("v_rel")),
        "v_inf_km_s": _maybe_float(cneos_row.get("v_inf")),
        "orbit_id": cneos_row.get("orbit_id"),
        # CNEOS rows don't carry their own solution_date; we use the snapshot
        # as a stand-in. SBDB lookup gives the real solution_date for the
        # underlying orbit determination.
        "solution_date": snapshot_date,
        "raw_row": cneos_row,
        "source_retrieved_at": source_retrieved_at,
    }


# ---------------------------------------------------------------------------
# SBDB response → objects_snapshots + orbit_elements_snapshots
# ---------------------------------------------------------------------------


def normalize_sbdb_object(
    sbdb: dict[str, Any],
    *,
    snapshot_date: date,
    source_retrieved_at: datetime,
) -> dict[str, Any]:
    """Map an SBDB response to an objects_snapshots record."""
    obj = sbdb["object"]
    orbit = sbdb["orbit"]
    phys = _index_phys_par(sbdb.get("phys_par") or [])

    raw_serialized = json.dumps(sbdb, sort_keys=True, default=str).encode("utf-8")
    return {
        "snapshot_date": snapshot_date,
        "designation": obj.get("des") or obj.get("fullname") or "",
        "spkid": str(obj["spkid"]),
        "full_name": obj.get("fullname"),
        "neo": _maybe_bool(obj.get("neo")),
        "pha": _maybe_bool(obj.get("pha")),
        "orbit_class": (obj.get("orbit_class") or {}).get("code"),
        "absolute_magnitude_h": _maybe_float(phys.get("H")),
        "diameter_km": _maybe_float(phys.get("diameter")),
        "diameter_estimate_km": _maybe_float(phys.get("diameter")),
        "albedo": _maybe_float(phys.get("albedo")),
        "rotation_period_h": _maybe_float(phys.get("rot_per")),
        "spec_class": phys.get("spec_T") or phys.get("spec_B"),
        "first_observed": _maybe_date(orbit.get("first_obs")),
        "last_observed": _maybe_date(orbit.get("last_obs")),
        "observation_arc_days": _maybe_int(orbit.get("data_arc")),
        "n_observations": _maybe_int(orbit.get("n_obs_used")),
        "solution_date": _parse_soln_date(orbit["soln_date"]),
        "raw_row": sbdb,
        "source_url": SBDB_URL,
        "source_retrieved_at": source_retrieved_at,
        "source_checksum": hashlib.sha256(raw_serialized).hexdigest(),
        "extraction_version": EXTRACTION_VERSION,
    }


def normalize_sbdb_orbit_elements(
    sbdb: dict[str, Any],
    *,
    source_retrieved_at: datetime,
) -> dict[str, Any]:
    """Map an SBDB response to an orbit_elements_snapshots record."""
    obj = sbdb["object"]
    orbit = sbdb["orbit"]
    elements = _index_orbit_elements(orbit.get("elements") or [])
    return {
        "spkid": str(obj["spkid"]),
        "solution_date": _parse_soln_date(orbit["soln_date"]),
        "epoch": _maybe_float(orbit.get("epoch")),
        "e": _maybe_float(elements.get("e", {}).get("value")),
        "a": _maybe_float(elements.get("a", {}).get("value")),
        "i": _maybe_float(elements.get("i", {}).get("value")),
        "om": _maybe_float(elements.get("om", {}).get("value")),
        "w": _maybe_float(elements.get("w", {}).get("value")),
        "ma": _maybe_float(elements.get("ma", {}).get("value")),
        "sigma_e": _maybe_float(elements.get("e", {}).get("sigma")),
        "sigma_a": _maybe_float(elements.get("a", {}).get("sigma")),
        "sigma_i": _maybe_float(elements.get("i", {}).get("sigma")),
        "covariance": None,  # SBDB returns covariance separately when requested
        "raw_row": orbit,
        "source_retrieved_at": source_retrieved_at,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_phys_par(phys_par: list[dict[str, Any]]) -> dict[str, Any]:
    """phys_par is an array of dicts keyed by `name`. Index for lookup."""
    out: dict[str, Any] = {}
    for entry in phys_par:
        name = entry.get("name")
        if name:
            out[name] = entry.get("value")
    return out


def _index_orbit_elements(elements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Orbit elements come as an array; index by `name` (e, a, i, etc.)."""
    return {entry["name"]: entry for entry in elements if entry.get("name")}


def _parse_cad_datetime(cd: str) -> datetime:
    """CAD format is 'YYYY-Mon-DD HH:MM' UTC, e.g. '2026-May-08 12:27'."""
    return datetime.strptime(cd, "%Y-%b-%d %H:%M").replace(tzinfo=UTC)


def _parse_soln_date(s: str) -> date:
    """SBDB soln_date is 'YYYY-MM-DD HH:MM:SS' UTC."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").date()


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _maybe_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _maybe_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "y", "1")
    return bool(v)


def _maybe_date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except ValueError:
        return None


__all__ = [
    "AU_IN_LD",
    "EXTRACTION_VERSION",
    "SBDB_URL",
    "normalize_close_approach",
    "normalize_sbdb_object",
    "normalize_sbdb_orbit_elements",
]
