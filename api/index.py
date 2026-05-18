"""FastAPI app for close_encounters / neo_citation.

Local dev:
    make api       # uvicorn at :8551

Production:
    Vercel routes /api/* and /docs and /openapi.json here via vercel.json.
    DATABASE_URL must be set as a Vercel project env var.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query

from api.models import (
    AlertItem,
    AlertListResponse,
    ApproachItem,
    ApproachListResponse,
    HealthResponse,
    ObjectDetail,
)

load_dotenv()

API_VERSION = "0.1.0"
DEFAULT_UPCOMING_DAYS = 60
DEFAULT_RECENT_DAYS = 30
DEFAULT_LIMIT = 200
DEFAULT_ALERTS_LIMIT = 50

app = FastAPI(
    title="neo_citation",
    description="Public near-Earth object close-approach + citation warehouse.",
    version=API_VERSION,
)


# ---------------------------------------------------------------------------
# DB connection — per-request (cheap with Neon's pooler)
# ---------------------------------------------------------------------------


def get_conn() -> Generator[psycopg.Connection, None, None]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    conn = psycopg.connect(url)
    try:
        yield conn
    finally:
        conn.close()


# FastAPI-recommended pattern for shared dependencies — avoids B008 lint hits
# from calling `Depends()` directly in argument defaults.
ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health(conn: ConnDep) -> HealthResponse:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(snapshot_date) FROM close_approaches_snapshots")
        row = cur.fetchone()
        latest = row[0] if row else None
    return HealthResponse(status="ok", version=API_VERSION, latest_snapshot_date=latest)


# ---------------------------------------------------------------------------
# /api/approaches/upcoming
# ---------------------------------------------------------------------------


@app.get("/api/approaches/upcoming", response_model=ApproachListResponse)
def approaches_upcoming(
    conn: ConnDep,
    days: int = Query(default=DEFAULT_UPCOMING_DAYS, ge=1, le=365),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=1000),
) -> ApproachListResponse:
    now = datetime.now(UTC)
    end = now + timedelta(days=days)
    snapshot_date, rows = _fetch_approaches(
        conn,
        window_start=now,
        window_end=end,
        order="ASC",
        limit=limit,
    )
    return ApproachListResponse(
        count=len(rows),
        window_days=days,
        snapshot_date=snapshot_date,
        items=[_row_to_approach_item(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# /api/approaches/recent
# ---------------------------------------------------------------------------


@app.get("/api/approaches/recent", response_model=ApproachListResponse)
def approaches_recent(
    conn: ConnDep,
    days: int = Query(default=DEFAULT_RECENT_DAYS, ge=1, le=365),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=1000),
) -> ApproachListResponse:
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    snapshot_date, rows = _fetch_approaches(
        conn,
        window_start=start,
        window_end=now,
        order="DESC",
        limit=limit,
    )
    return ApproachListResponse(
        count=len(rows),
        window_days=days,
        snapshot_date=snapshot_date,
        items=[_row_to_approach_item(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# /api/objects/{designation}
# ---------------------------------------------------------------------------


@app.get("/api/objects/{designation}", response_model=ObjectDetail)
def get_object(
    designation: str,
    conn: ConnDep,
) -> ObjectDetail:
    row = _fetch_object(conn, designation)
    if not row:
        raise HTTPException(status_code=404, detail=f"object {designation!r} not found")
    return _row_to_object_detail(row)


# ---------------------------------------------------------------------------
# /api/objects/{designation}/approaches
# ---------------------------------------------------------------------------


@app.get("/api/objects/{designation}/approaches", response_model=ApproachListResponse)
def get_object_approaches(
    conn: ConnDep,
    designation: str,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=1000),
) -> ApproachListResponse:
    obj = _fetch_object(conn, designation)
    if not obj:
        raise HTTPException(status_code=404, detail=f"object {designation!r} not found")
    snapshot_date = obj["snapshot_date"]
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                ca.spkid,
                ca.designation,
                %s::text AS full_name,
                ca.approach_date,
                ca.body,
                ca.distance_au,
                ca.distance_ld,
                ca.distance_min_au,
                ca.distance_max_au,
                ca.v_rel_km_s,
                ca.v_inf_km_s,
                ca.orbit_id,
                %s::float8 AS diameter_estimate_km,
                %s::float8 AS absolute_magnitude_h,
                %s::text   AS orbit_class
            FROM close_approaches_snapshots ca
            WHERE ca.snapshot_date = %s
              AND ca.spkid = %s
            ORDER BY ca.approach_date ASC
            LIMIT %s
            """,
            (
                obj.get("full_name"),
                obj.get("diameter_estimate_km"),
                obj.get("absolute_magnitude_h"),
                obj.get("orbit_class"),
                snapshot_date,
                obj["spkid"],
                limit,
            ),
        )
        rows = list(cur.fetchall())
    return ApproachListResponse(
        count=len(rows),
        window_days=0,
        snapshot_date=snapshot_date,
        items=[_row_to_approach_item(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# /api/alerts
# ---------------------------------------------------------------------------


@app.get("/api/alerts", response_model=AlertListResponse)
def list_alerts(
    conn: ConnDep,
    limit: int = Query(default=DEFAULT_ALERTS_LIMIT, ge=1, le=500),
    rule_id: str | None = Query(default=None),
) -> AlertListResponse:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        if rule_id:
            cur.execute(
                """
                SELECT
                    a.alert_id,
                    a.fired_at,
                    a.rule_id,
                    a.spkid,
                    a.approach_date,
                    a.rationale,
                    a.payload,
                    os.designation
                FROM alerts a
                LEFT JOIN LATERAL (
                    SELECT designation FROM objects_snapshots
                    WHERE spkid = a.spkid
                    ORDER BY snapshot_date DESC LIMIT 1
                ) os ON TRUE
                WHERE a.rule_id = %s
                ORDER BY a.fired_at DESC
                LIMIT %s
                """,
                (rule_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT
                    a.alert_id,
                    a.fired_at,
                    a.rule_id,
                    a.spkid,
                    a.approach_date,
                    a.rationale,
                    a.payload,
                    os.designation
                FROM alerts a
                LEFT JOIN LATERAL (
                    SELECT designation FROM objects_snapshots
                    WHERE spkid = a.spkid
                    ORDER BY snapshot_date DESC LIMIT 1
                ) os ON TRUE
                ORDER BY a.fired_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        rows = list(cur.fetchall())
    items = [
        AlertItem(
            alert_id=r["alert_id"],
            fired_at=r["fired_at"],
            rule_id=r["rule_id"],
            spkid=r["spkid"],
            designation=r.get("designation"),
            approach_date=r["approach_date"],
            rationale=r["rationale"],
            payload=r["payload"] or {},
        )
        for r in rows
    ]
    return AlertListResponse(count=len(items), items=items)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_approaches(
    conn: psycopg.Connection,
    *,
    window_start: datetime,
    window_end: datetime,
    order: str,
    limit: int,
) -> tuple[Any, list[dict[str, Any]]]:
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("SELECT MAX(snapshot_date) AS d FROM close_approaches_snapshots")
        row = cur.fetchone()
        snapshot_date = row["d"] if row else None
        if snapshot_date is None:
            return None, []
        cur.execute(
            f"""
            SELECT
                ca.spkid,
                ca.designation,
                os.full_name,
                ca.approach_date,
                ca.body,
                ca.distance_au,
                ca.distance_ld,
                ca.distance_min_au,
                ca.distance_max_au,
                ca.v_rel_km_s,
                ca.v_inf_km_s,
                ca.orbit_id,
                os.diameter_estimate_km,
                os.absolute_magnitude_h,
                os.orbit_class
            FROM close_approaches_snapshots ca
            LEFT JOIN objects_snapshots os
                   ON os.spkid = ca.spkid
                  AND os.snapshot_date = ca.snapshot_date
            WHERE ca.snapshot_date = %s
              AND ca.body = 'Earth'
              AND ca.approach_date >= %s
              AND ca.approach_date <= %s
            ORDER BY ca.approach_date {direction}
            LIMIT %s
            """,
            (snapshot_date, window_start, window_end, limit),
        )
        rows = list(cur.fetchall())
    return snapshot_date, rows


def _fetch_object(conn: psycopg.Connection, designation: str) -> dict[str, Any] | None:
    """Match against either designation or spkid in the latest snapshot."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM objects_snapshots
            WHERE (designation = %s OR spkid = %s OR full_name = %s)
              AND snapshot_date = (
                  SELECT MAX(snapshot_date) FROM objects_snapshots
              )
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (designation, designation, designation),
        )
        return cur.fetchone()


def _row_to_approach_item(row: dict[str, Any]) -> ApproachItem:
    return ApproachItem(
        spkid=str(row.get("spkid") or ""),
        designation=str(row.get("designation") or ""),
        full_name=row.get("full_name"),
        approach_date=row["approach_date"],
        body=row.get("body") or "Earth",
        distance_au=float(row["distance_au"]),
        distance_ld=_maybe_float(row.get("distance_ld")),
        distance_min_au=_maybe_float(row.get("distance_min_au")),
        distance_max_au=_maybe_float(row.get("distance_max_au")),
        v_rel_km_s=_maybe_float(row.get("v_rel_km_s")),
        v_inf_km_s=_maybe_float(row.get("v_inf_km_s")),
        orbit_id=row.get("orbit_id"),
        diameter_estimate_km=_maybe_float(row.get("diameter_estimate_km")),
        absolute_magnitude_h=_maybe_float(row.get("absolute_magnitude_h")),
        orbit_class=row.get("orbit_class"),
    )


def _row_to_object_detail(row: dict[str, Any]) -> ObjectDetail:
    return ObjectDetail(
        spkid=str(row["spkid"]),
        designation=row["designation"],
        full_name=row.get("full_name"),
        neo=row.get("neo"),
        pha=row.get("pha"),
        orbit_class=row.get("orbit_class"),
        absolute_magnitude_h=_maybe_float(row.get("absolute_magnitude_h")),
        diameter_km=_maybe_float(row.get("diameter_km")),
        diameter_estimate_km=_maybe_float(row.get("diameter_estimate_km")),
        albedo=_maybe_float(row.get("albedo")),
        rotation_period_h=_maybe_float(row.get("rotation_period_h")),
        spec_class=row.get("spec_class"),
        first_observed=row.get("first_observed"),
        last_observed=row.get("last_observed"),
        observation_arc_days=row.get("observation_arc_days"),
        n_observations=row.get("n_observations"),
        solution_date=row["solution_date"],
        snapshot_date=row["snapshot_date"],
    )


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
