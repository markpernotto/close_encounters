"""Load normalized rows into Postgres. Idempotent: re-running on the same
snapshot is a no-op (UPSERTs by primary key, events deduped on dedup_key).

All functions take an open psycopg connection; the caller manages
transaction boundaries.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Json


def connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or os.environ["DATABASE_URL"])


# ---------------------------------------------------------------------------
# objects_snapshots
# ---------------------------------------------------------------------------

_OBJECT_COLS = (
    "snapshot_date", "designation", "spkid", "full_name", "neo", "pha",
    "orbit_class", "absolute_magnitude_h", "diameter_km", "diameter_estimate_km",
    "albedo", "rotation_period_h", "spec_class", "first_observed", "last_observed",
    "observation_arc_days", "n_observations", "solution_date", "raw_row",
    "source_url", "source_retrieved_at", "source_checksum", "extraction_version",
)


def load_objects(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> int:
    sql = f"""
        INSERT INTO objects_snapshots ({", ".join(_OBJECT_COLS)})
        VALUES ({", ".join("%s" for _ in _OBJECT_COLS)})
        ON CONFLICT (snapshot_date, spkid) DO UPDATE SET
            designation = EXCLUDED.designation,
            full_name = EXCLUDED.full_name,
            neo = EXCLUDED.neo,
            pha = EXCLUDED.pha,
            orbit_class = EXCLUDED.orbit_class,
            absolute_magnitude_h = EXCLUDED.absolute_magnitude_h,
            diameter_km = EXCLUDED.diameter_km,
            diameter_estimate_km = EXCLUDED.diameter_estimate_km,
            albedo = EXCLUDED.albedo,
            rotation_period_h = EXCLUDED.rotation_period_h,
            spec_class = EXCLUDED.spec_class,
            first_observed = EXCLUDED.first_observed,
            last_observed = EXCLUDED.last_observed,
            observation_arc_days = EXCLUDED.observation_arc_days,
            n_observations = EXCLUDED.n_observations,
            solution_date = EXCLUDED.solution_date,
            raw_row = EXCLUDED.raw_row,
            source_url = EXCLUDED.source_url,
            source_retrieved_at = EXCLUDED.source_retrieved_at,
            source_checksum = EXCLUDED.source_checksum,
            extraction_version = EXCLUDED.extraction_version
    """
    return _execute_many(conn, sql, rows, _OBJECT_COLS)


# ---------------------------------------------------------------------------
# orbit_elements_snapshots
# ---------------------------------------------------------------------------

_ORBIT_COLS = (
    "spkid", "solution_date", "epoch", "e", "a", "i", "om", "w", "ma",
    "sigma_e", "sigma_a", "sigma_i", "covariance", "raw_row", "source_retrieved_at",
)


def load_orbit_elements(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> int:
    sql = f"""
        INSERT INTO orbit_elements_snapshots ({", ".join(_ORBIT_COLS)})
        VALUES ({", ".join("%s" for _ in _ORBIT_COLS)})
        ON CONFLICT (spkid, solution_date) DO UPDATE SET
            epoch = EXCLUDED.epoch,
            e = EXCLUDED.e,
            a = EXCLUDED.a,
            i = EXCLUDED.i,
            om = EXCLUDED.om,
            w = EXCLUDED.w,
            ma = EXCLUDED.ma,
            sigma_e = EXCLUDED.sigma_e,
            sigma_a = EXCLUDED.sigma_a,
            sigma_i = EXCLUDED.sigma_i,
            covariance = EXCLUDED.covariance,
            raw_row = EXCLUDED.raw_row,
            source_retrieved_at = EXCLUDED.source_retrieved_at
    """
    return _execute_many(conn, sql, rows, _ORBIT_COLS)


# ---------------------------------------------------------------------------
# close_approaches_snapshots
# ---------------------------------------------------------------------------

_APPROACH_COLS = (
    "snapshot_date", "spkid", "designation", "approach_date", "body",
    "distance_au", "distance_ld", "distance_min_au", "distance_max_au",
    "v_rel_km_s", "v_inf_km_s", "orbit_id", "solution_date", "raw_row",
    "source_retrieved_at",
)


def resolve_spkids(
    conn: psycopg.Connection, snapshot_date: date, designations: Iterable[str]
) -> dict[str, str]:
    """Look up designation → spkid for a given snapshot from objects_snapshots.

    CNEOS rows only carry designations; close_approaches_snapshots requires
    spkid as part of the primary key. Call this after objects have loaded.
    """
    desigs = list(set(designations))
    if not desigs:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT designation, spkid FROM objects_snapshots "
            "WHERE snapshot_date = %s AND designation = ANY(%s)",
            (snapshot_date, desigs),
        )
        return {desig: spkid for desig, spkid in cur.fetchall()}


def load_close_approaches(
    conn: psycopg.Connection,
    rows: Iterable[dict[str, Any]],
    *,
    designation_to_spkid: dict[str, str],
) -> tuple[int, int]:
    """UPSERT close-approach rows. Returns (inserted_or_updated, skipped_no_spkid).

    Rows whose designation is not present in designation_to_spkid are skipped
    and the count is returned for diagnostics.
    """
    sql = f"""
        INSERT INTO close_approaches_snapshots ({", ".join(_APPROACH_COLS)})
        VALUES ({", ".join("%s" for _ in _APPROACH_COLS)})
        ON CONFLICT (snapshot_date, spkid, approach_date, body) DO UPDATE SET
            designation = EXCLUDED.designation,
            distance_au = EXCLUDED.distance_au,
            distance_ld = EXCLUDED.distance_ld,
            distance_min_au = EXCLUDED.distance_min_au,
            distance_max_au = EXCLUDED.distance_max_au,
            v_rel_km_s = EXCLUDED.v_rel_km_s,
            v_inf_km_s = EXCLUDED.v_inf_km_s,
            orbit_id = EXCLUDED.orbit_id,
            solution_date = EXCLUDED.solution_date,
            raw_row = EXCLUDED.raw_row,
            source_retrieved_at = EXCLUDED.source_retrieved_at
    """
    written = 0
    skipped = 0
    resolved_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("spkid"):
            resolved_rows.append(row)
            continue
        spkid = designation_to_spkid.get(row["designation"])
        if not spkid:
            skipped += 1
            continue
        resolved_rows.append({**row, "spkid": spkid})
    written = _execute_many(conn, sql, resolved_rows, _APPROACH_COLS)
    return written, skipped


# ---------------------------------------------------------------------------
# approach_events
# ---------------------------------------------------------------------------

_EVENT_COLS = (
    "observed_at", "spkid", "approach_date", "event_type",
    "prev_value", "new_value", "diff_summary", "dedup_key",
)


def load_events(conn: psycopg.Connection, events: Iterable[dict[str, Any]]) -> int:
    """Insert approach_events. ON CONFLICT on dedup_key → no-op (idempotent)."""
    sql = f"""
        INSERT INTO approach_events ({", ".join(_EVENT_COLS)})
        VALUES ({", ".join("%s" for _ in _EVENT_COLS)})
        ON CONFLICT (dedup_key) DO NOTHING
    """
    return _execute_many(conn, sql, events, _EVENT_COLS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _execute_many(
    conn: psycopg.Connection,
    sql: str,
    rows: Iterable[dict[str, Any]],
    cols: tuple[str, ...],
) -> int:
    """Run executemany over rows. JSON-typed columns are wrapped with Json."""
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        params = [tuple(_adapt(row.get(c)) for c in cols) for row in rows]
        cur.executemany(sql, params)
    return len(rows)


def _adapt(value: Any) -> Any:
    """Wrap dict/list values as Json so psycopg can pass them as JSONB."""
    if isinstance(value, (dict, list)):
        return Json(value)
    return value


__all__ = [
    "connect",
    "load_close_approaches",
    "load_events",
    "load_objects",
    "load_orbit_elements",
    "resolve_spkids",
]
