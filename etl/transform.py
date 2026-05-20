"""Normalize raw source records into our schema's row shape.

Pure functions, no I/O. Input: parsed JSON from etl.sources.*. Output:
dicts whose keys match columns in etl/schema.sql. The load layer is
responsible for inserting these into Postgres.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Any

from etl.sources.esa_neocc import NEOCC_RISK_LIST_URL
from etl.sources.jpl_sbdb import SBDB_URL
from etl.sources.jpl_sentry import SENTRY_URL
from etl.sources.mpc_mpec import mpec_url

AGENCY_NASA_SENTRY = "NASA_SENTRY"
AGENCY_ESA_NEOCC = "ESA_NEOCC"

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


# ---------------------------------------------------------------------------
# NASA Sentry summary row → risk_assessments
# ---------------------------------------------------------------------------


def normalize_sentry_assessment(
    record: dict[str, Any],
    *,
    snapshot_date: date,
    source_retrieved_at: datetime,
    spkid: str | None = None,
) -> dict[str, Any]:
    """Map a Sentry summary record to a risk_assessments row.

    The Sentry summary record has keys: des, fullname, id, h, diameter,
    n_imp, ip, ps_max, ps_cum, ts_max, v_inf, range, last_obs, last_obs_jd.

    spkid is optional: the Sentry summary doesn't carry one, but if a
    caller can resolve it via objects_snapshots they can pass it in.
    """
    designation = str(record.get("des") or "")
    year_min, year_max = _parse_year_range(record.get("range"))
    return {
        "agency": AGENCY_NASA_SENTRY,
        "designation": designation,
        "assessment_date": snapshot_date,
        "spkid": spkid,
        "risk_class": _risk_class_for_sentry(record),
        "torino_scale": _maybe_int(record.get("ts_max")),
        "palermo_scale": _maybe_float(record.get("ps_cum")),
        "palermo_scale_max": _maybe_float(record.get("ps_max")),
        "impact_probability": _maybe_float(record.get("ip")),
        "n_impacts": _maybe_int(record.get("n_imp")),
        "potential_impact_year_min": year_min,
        "potential_impact_year_max": year_max,
        "energy_mt": None,  # Sentry summary doesn't surface this; per-object endpoint does
        "diameter_km": _maybe_float(record.get("diameter")),
        "absolute_magnitude_h": _maybe_float(record.get("h")),
        "v_inf_km_s": _maybe_float(record.get("v_inf")),
        "last_observed": _maybe_date(record.get("last_obs")),
        "raw_row": record,
        "source_url": SENTRY_URL,
        "source_retrieved_at": source_retrieved_at,
        "extraction_version": EXTRACTION_VERSION,
    }


def _parse_year_range(value: Any) -> tuple[int | None, int | None]:
    """Sentry's `range` field is 'YYYY-YYYY' or 'YYYY'. Parse into a pair."""
    if not value:
        return None, None
    s = str(value)
    if "-" in s:
        a, _, b = s.partition("-")
        return _maybe_int(a), _maybe_int(b)
    only = _maybe_int(s)
    return only, only


# ---------------------------------------------------------------------------
# ESA NEOCC risk-list row → risk_assessments
# ---------------------------------------------------------------------------


def normalize_neocc_assessment(
    record: dict[str, Any],
    *,
    snapshot_date: date,
    source_retrieved_at: datetime,
    spkid: str | None = None,
) -> dict[str, Any]:
    """Map a parsed ESA NEOCC risk-list row to a risk_assessments row.

    NEOCC fields are pipe-delimited text; etl.sources.esa_neocc parses
    them into strings. We coerce types here and normalize designation
    formatting so cross-agency joins on (designation) work.
    """
    designation = str(record.get("designation") or "")
    diameter_m = _maybe_float(record.get("diameter_m"))
    year_min, year_max = _parse_year_range(record.get("years"))
    return {
        "agency": AGENCY_ESA_NEOCC,
        "designation": designation,
        "assessment_date": snapshot_date,
        "spkid": spkid,
        "risk_class": _risk_class_for_neocc(record),
        "torino_scale": _maybe_int(record.get("ts")),
        "palermo_scale": _maybe_float(record.get("ps_cum")),
        "palermo_scale_max": _maybe_float(record.get("ps_max")),
        "impact_probability": _maybe_float(record.get("ip_cum")),
        "n_impacts": None,  # NEOCC risk list doesn't surface a count directly
        "potential_impact_year_min": year_min,
        "potential_impact_year_max": year_max,
        "energy_mt": None,
        "diameter_km": diameter_m / 1000.0 if diameter_m is not None else None,
        "absolute_magnitude_h": None,  # not in the summary
        "v_inf_km_s": _maybe_float(record.get("v_inf")),
        "last_observed": None,  # not in the summary
        "raw_row": record,
        "source_url": NEOCC_RISK_LIST_URL,
        "source_retrieved_at": source_retrieved_at,
        "extraction_version": EXTRACTION_VERSION,
    }


def _risk_class_for_neocc(record: dict[str, Any]) -> str:
    """Bucket NEOCC records into the same label scheme as Sentry so the
    risk_class column reads consistently across agencies."""
    torino = _maybe_int(record.get("ts"))
    if torino is not None and torino > 0:
        return f"torino_{torino}"
    palermo = _maybe_float(record.get("ps_cum"))
    if palermo is not None and palermo >= -2:
        return "palermo_elevated"
    return "background"


# ---------------------------------------------------------------------------
# SBDB discovery block → discovery_attributions
# ---------------------------------------------------------------------------


# Patterns for survey-program detection. Matched (case-insensitive) against
# the combined `who` + `discovery` prose. First match wins, so order matters
# (longer / more-specific names first).
_DISCOVERY_PROGRAM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Mt. Lemmon Survey", "CSS"),
    ("Mount Lemmon Survey", "CSS"),
    ("Catalina Sky Survey", "CSS"),
    ("Catalina", "CSS"),
    ("Pan-STARRS", "PS1"),
    ("PanSTARRS", "PS1"),
    ("ATLAS", "ATLAS"),
    ("NEOWISE", "NEOWISE"),
    ("LINEAR", "LINEAR"),
    ("Spacewatch", "SPACEWATCH"),
    ("LONEOS", "LONEOS"),
    ("LSST", "RUBIN_SSP"),
    ("Rubin", "RUBIN_SSP"),
    ("Vera C. Rubin", "RUBIN_SSP"),
)


_MPEC_ID = re.compile(r"MPEC\s+(\d{4}-[A-Z]\d{1,3})", re.IGNORECASE)
_DISCOVERY_DATE = re.compile(r"(\d{4})[-\s]([A-Za-z]{3})[\.\-\s](\d{1,2})")


def normalize_discovery_attribution(
    sbdb: dict[str, Any],
    *,
    source_retrieved_at: datetime,
) -> dict[str, Any] | None:
    """Map the SBDB `discovery` block into a discovery_attributions row.

    Returns None if SBDB returned no discovery info (rare; some recently-
    added objects lack the block). Otherwise emits one row keyed by spkid
    with best-effort parsing of discovery_date and discovery_program; the
    full raw block is preserved in raw_record for later re-parsing.
    """
    obj = sbdb.get("object") or {}
    spkid = str(obj.get("spkid") or "")
    if not spkid:
        return None
    block = sbdb.get("discovery") or {}
    if not block:
        return None

    who = block.get("who") or ""
    prose = block.get("discovery") or ""
    return {
        "spkid": spkid,
        "discoverer": (who or None),
        "discovery_facility": (block.get("location") or None),
        "discovery_program": _extract_discovery_program(who, prose),
        "discovery_date": _parse_discovery_date(block.get("date") or prose),
        "mpec_id": _extract_mpec_id(block.get("ref") or "", prose),
        "site_code": (block.get("site") or None),
        "citation_text": (block.get("citation") or None),
        "raw_record": block,
        "source_url": SBDB_URL,
        "captured_at": source_retrieved_at,
    }


def _extract_discovery_program(who: str, prose: str) -> str | None:
    """Survey-name match. `who` is the structured "team" field from SBDB
    and is the authoritative source — we scan it first. Prose is the
    fallback for older records where `who` is just an individual's name."""
    for source in (who, prose):
        if not source:
            continue
        lowered = source.lower()
        for needle, code in _DISCOVERY_PROGRAM_PATTERNS:
            if needle.lower() in lowered:
                return code
    return None


def _extract_mpec_id(ref: str, prose: str) -> str | None:
    for source in (ref, prose):
        m = _MPEC_ID.search(source or "")
        if m:
            return f"MPEC {m.group(1)}"
    return None


def _parse_discovery_date(value: Any) -> date | None:
    """SBDB serves discovery dates as 'YYYY-Mon-DD' (e.g. '2004-Jun-19').
    Some older records use 'YYYY Mon. DD' in the prose. Both are handled;
    anything else returns None."""
    if not value:
        return None
    s = str(value).strip()
    # Try the structured forms first
    for fmt in ("%Y-%b-%d", "%Y %b %d", "%Y %b. %d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Last resort: regex search inside arbitrary prose
    m = _DISCOVERY_DATE.search(s)
    if m:
        year, mon, day = m.groups()
        try:
            return datetime.strptime(f"{year} {mon} {day}", "%Y %b %d").date()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Parsed MPEC → discovery_publications + object_publications
# ---------------------------------------------------------------------------

RESOLVED_VIA_MPEC = "mpec"
RELATIONSHIP_DISCOVERY = "discovery"
RELATIONSHIP_FOLLOW_UP = "follow_up"
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"


def normalize_mpec_publication(
    parsed: dict[str, Any],
    *,
    resolved_at: datetime,
) -> dict[str, Any] | None:
    """Map a parse_mpec_html() result into a discovery_publications row.

    Returns None when the parse didn't surface an MPEC id — without an id
    we can't dedupe against future re-fetches, so we'd rather skip the
    row than load it unkeyed.
    """
    mpec_id = parsed.get("mpec_id")
    if not mpec_id:
        return None
    title = parsed.get("title") or f"Minor Planet Electronic Circular {mpec_id}"
    issued = parsed.get("issued_at")
    publication_date = issued.date() if isinstance(issued, datetime) else None
    return {
        "doi": None,
        "mpec_id": mpec_id,
        "ads_bibcode": None,
        "arxiv_id": None,
        "title": title,
        "authors": None,
        "publication_date": publication_date,
        "source_url": mpec_url(mpec_id),
        "resolved_via": RESOLVED_VIA_MPEC,
        "resolved_at": resolved_at,
        "raw_record": parsed,
    }


def mpec_object_links(
    parsed: dict[str, Any],
    *,
    publication_id: int,
    extracted_at: datetime,
    designation_to_spkid: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build object_publications rows from a parsed MPEC.

    Featured designations (bolded in the MPEC body) get
    relationship='discovery' at confidence=high. Other mentioned
    designations get relationship='follow_up' at confidence=medium —
    they're discussed but the MPEC isn't announcing them.
    """
    desig_to_spkid = designation_to_spkid or {}
    rows: list[dict[str, Any]] = []
    featured = set(parsed.get("featured_designations") or [])
    mentioned = set(parsed.get("mentioned_designations") or [])

    for des in featured:
        rows.append(
            _object_publication_row(
                designation=des,
                publication_id=publication_id,
                relationship=RELATIONSHIP_DISCOVERY,
                confidence=CONFIDENCE_HIGH,
                confidence_reason="featured (bolded) designation in MPEC body",
                extracted_from="mpec_featured",
                extracted_at=extracted_at,
                spkid=desig_to_spkid.get(des),
            )
        )
    for des in mentioned - featured:
        rows.append(
            _object_publication_row(
                designation=des,
                publication_id=publication_id,
                relationship=RELATIONSHIP_FOLLOW_UP,
                confidence=CONFIDENCE_MEDIUM,
                confidence_reason="designation appears in MPEC body but not featured",
                extracted_from="mpec_body",
                extracted_at=extracted_at,
                spkid=desig_to_spkid.get(des),
            )
        )
    return rows


def _object_publication_row(
    *,
    designation: str,
    publication_id: int,
    relationship: str,
    confidence: str,
    confidence_reason: str,
    extracted_from: str,
    extracted_at: datetime,
    spkid: str | None,
) -> dict[str, Any]:
    return {
        "designation": designation,
        "publication_id": publication_id,
        "relationship": relationship,
        "spkid": spkid,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "extracted_from": extracted_from,
        "extracted_at": extracted_at,
    }


def _risk_class_for_sentry(record: dict[str, Any]) -> str:
    """Bucket Sentry records into a human-readable risk tier label.

    Most objects on Sentry are Torino 0 / Palermo well below 0. The label
    is informational; the precise scores live in their own columns.
    """
    torino = _maybe_int(record.get("ts_max"))
    if torino is not None and torino > 0:
        return f"torino_{torino}"
    palermo = _maybe_float(record.get("ps_cum"))
    if palermo is not None and palermo >= -2:
        return "palermo_elevated"
    return "background"


__all__ = [
    "AGENCY_ESA_NEOCC",
    "AGENCY_NASA_SENTRY",
    "AU_IN_LD",
    "EXTRACTION_VERSION",
    "NEOCC_RISK_LIST_URL",
    "SBDB_URL",
    "SENTRY_URL",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "RELATIONSHIP_DISCOVERY",
    "RELATIONSHIP_FOLLOW_UP",
    "RESOLVED_VIA_MPEC",
    "mpec_object_links",
    "normalize_close_approach",
    "normalize_discovery_attribution",
    "normalize_mpec_publication",
    "normalize_neocc_assessment",
    "normalize_sbdb_object",
    "normalize_sbdb_orbit_elements",
    "normalize_sentry_assessment",
]
