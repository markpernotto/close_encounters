"""Threshold rules that decide which approach_events become public alerts.

Each rule is a pure function of (event, object_row, approach_row, observed_at)
returning an Alert dict if it fires, or None. Rules are documented in plain
English in vocabularies/alert_rule.yaml and (Phase 1 ship) in
docs/ALERT_RULES.md.

False-alarm policy: alerts are NEVER retracted. If new data invalidates a
prior alert, a correcting alert is appended. Alerts persist via the alerts
table (etl.load.load_alerts), keyed by a deterministic dedup_key so
re-running this module against the same events is idempotent.

Diameter handling: many newly-discovered NEOs only have an absolute
magnitude (H), not a measured diameter. We derive an estimate from H using
a default albedo of 0.14 (typical NEO). Conservative — if neither H nor
diameter is known, the size-gated rule does not fire.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import psycopg

from etl.diff import EVENT_NEW_OBJECT
from etl.load import connect, load_alerts

# Rule ids — must match vocabularies/alert_rule.yaml
RULE_SIZE_AND_DISTANCE = "size_and_distance"
RULE_VERY_CLOSE_ANY_SIZE = "very_close_any_size"
RULE_SHORT_ARC_LATE_WARNING = "short_arc_late_warning"

# Thresholds
SIZE_THRESHOLD_KM = 0.050  # 50 m
SIZE_RULE_DISTANCE_LD = 1.0  # inside the lunar distance
VERY_CLOSE_DISTANCE_LD = 0.5  # half the Earth-Moon distance
SHORT_ARC_DAYS = 14
LATE_WARNING_WINDOW_DAYS = 30

# Standard NEO photometric defaults for diameter estimation when only H is
# available. (1329 km / sqrt(albedo)) * 10^(-H/5).
DIAMETER_FORMULA_CONSTANT_KM = 1329.0
DEFAULT_ALBEDO = 0.14


# ---------------------------------------------------------------------------
# Diameter derivation
# ---------------------------------------------------------------------------


def derive_diameter_km(h_magnitude: float | None, albedo: float | None = None) -> float | None:
    """Estimate NEO diameter from absolute magnitude H using a standard formula.

    Returns None if H is missing or albedo is non-positive.
    """
    if h_magnitude is None:
        return None
    a = albedo if albedo and albedo > 0 else DEFAULT_ALBEDO
    return (DIAMETER_FORMULA_CONSTANT_KM / math.sqrt(a)) * (10.0 ** (-h_magnitude / 5.0))


def best_diameter_km(object_row: dict[str, Any]) -> float | None:
    """Pick the most authoritative diameter we have for this object.

    Order: measured diameter > pre-computed estimate > derived from H.
    """
    measured = object_row.get("diameter_km")
    if measured:
        return float(measured)
    estimate = object_row.get("diameter_estimate_km")
    if estimate:
        return float(estimate)
    return derive_diameter_km(
        object_row.get("absolute_magnitude_h"),
        object_row.get("albedo"),
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_size_and_distance(
    event: dict[str, Any],
    object_row: dict[str, Any],
    approach_row: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Sizeable object inside the lunar distance.

    Threshold: estimated diameter ≥ 50 m AND distance ≤ 1 LD.
    Conservative on missing data: if we can't establish diameter at all,
    rule does not fire.
    """
    diameter = best_diameter_km(object_row)
    if diameter is None:
        return None
    distance_ld = approach_row.get("distance_ld")
    if distance_ld is None:
        return None
    if diameter < SIZE_THRESHOLD_KM or distance_ld > SIZE_RULE_DISTANCE_LD:
        return None
    rationale = (
        f"diameter ~{int(round(diameter * 1000))}m, "
        f"distance {distance_ld:.2f} LD on "
        f"{approach_row['approach_date'].date().isoformat()}"
    )
    return _make_alert(
        rule_id=RULE_SIZE_AND_DISTANCE,
        event=event,
        approach_row=approach_row,
        observed_at=observed_at,
        rationale=rationale,
        payload={"diameter_km": diameter, "distance_ld": distance_ld},
    )


def rule_very_close_any_size(
    event: dict[str, Any],
    _object_row: dict[str, Any],
    approach_row: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Very-close approach regardless of size.

    Threshold: distance ≤ 0.5 LD. Anything inside half the Earth-Moon
    distance is operationally interesting whatever its size.
    """
    distance_ld = approach_row.get("distance_ld")
    if distance_ld is None:
        return None
    if distance_ld > VERY_CLOSE_DISTANCE_LD:
        return None
    rationale = (
        f"distance {distance_ld:.2f} LD on "
        f"{approach_row['approach_date'].date().isoformat()} "
        f"(below {VERY_CLOSE_DISTANCE_LD} LD threshold)"
    )
    return _make_alert(
        rule_id=RULE_VERY_CLOSE_ANY_SIZE,
        event=event,
        approach_row=approach_row,
        observed_at=observed_at,
        rationale=rationale,
        payload={"distance_ld": distance_ld},
    )


def rule_short_arc_late_warning(
    event: dict[str, Any],
    object_row: dict[str, Any],
    approach_row: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any] | None:
    """Newly-discovered, short observation arc, near-term approach.

    Threshold: event_type == NEW_OBJECT AND first close approach within
    30 days AND observation arc < 14 days. These are the "found late"
    objects whose orbits are still uncertain.
    """
    if event.get("event_type") != EVENT_NEW_OBJECT:
        return None
    arc_days = object_row.get("observation_arc_days")
    if arc_days is None or arc_days >= SHORT_ARC_DAYS:
        return None
    approach_date = approach_row.get("approach_date")
    if approach_date is None:
        return None
    horizon = observed_at + timedelta(days=LATE_WARNING_WINDOW_DAYS)
    if approach_date < observed_at or approach_date > horizon:
        return None
    rationale = (
        f"new object with {arc_days}-day observation arc; "
        f"first close approach in "
        f"{(approach_date - observed_at).days} days"
    )
    return _make_alert(
        rule_id=RULE_SHORT_ARC_LATE_WARNING,
        event=event,
        approach_row=approach_row,
        observed_at=observed_at,
        rationale=rationale,
        payload={
            "observation_arc_days": arc_days,
            "days_until_approach": (approach_date - observed_at).days,
        },
    )


ALL_RULES = (
    rule_size_and_distance,
    rule_very_close_any_size,
    rule_short_arc_late_warning,
)


# ---------------------------------------------------------------------------
# Evaluator + orchestrator
# ---------------------------------------------------------------------------


def evaluate(
    event: dict[str, Any],
    object_row: dict[str, Any],
    approach_row: dict[str, Any],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Run every rule against one (event, object, approach) triple.

    A single event can fire multiple rules (e.g. very-close + size+distance).
    """
    fired = []
    for rule in ALL_RULES:
        alert = rule(event, object_row, approach_row, observed_at)
        if alert is not None:
            fired.append(alert)
    return fired


def evaluate_batch(
    events: Iterable[dict[str, Any]],
    objects_by_spkid: dict[str, dict[str, Any]],
    approaches_by_key: dict[tuple[str, datetime, str], dict[str, Any]],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Evaluate a batch of events against their associated context rows.

    `approaches_by_key` is indexed by (spkid, approach_date, body) — the
    same key used in etl.diff. Events without a matching approach or
    object are silently skipped; this is consistent with the conservative
    "don't fire on missing data" stance of the rules.
    """
    alerts: list[dict[str, Any]] = []
    for event in events:
        spkid = event.get("spkid")
        approach_date = event.get("approach_date")
        if not spkid or approach_date is None:
            continue
        obj = objects_by_spkid.get(spkid)
        approach = approaches_by_key.get((spkid, approach_date, "Earth"))
        if obj is None or approach is None:
            continue
        alerts.extend(evaluate(event, obj, approach, observed_at))
    return alerts


def run(database_url: str | None = None) -> int:
    """Fetch the latest approach_events + their context, evaluate rules,
    persist new alerts. Returns the count of alerts actually inserted
    (excluding dedup-key conflicts).
    """
    url = database_url or os.environ["DATABASE_URL"]
    with connect(url) as conn:
        observed_at = datetime.now().astimezone()
        events, objects_by_spkid, approaches_by_key = _fetch_latest_evaluation_context(conn)
        alerts = evaluate_batch(events, objects_by_spkid, approaches_by_key, observed_at)
        with conn.transaction():
            return load_alerts(conn, alerts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    rule_id: str,
    event: dict[str, Any],
    approach_row: dict[str, Any],
    observed_at: datetime,
    rationale: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event_dedup_key = event["dedup_key"]
    return {
        "fired_at": observed_at,
        "rule_id": rule_id,
        "spkid": str(event["spkid"]),
        "approach_date": approach_row["approach_date"],
        "event_dedup_key": event_dedup_key,
        "rationale": rationale,
        "payload": payload,
        "dedup_key": _alert_dedup_key(rule_id, event_dedup_key),
    }


def _alert_dedup_key(rule_id: str, event_dedup_key: str) -> str:
    payload = json.dumps(
        {"rule_id": rule_id, "event_dedup_key": event_dedup_key},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fetch_latest_evaluation_context(
    conn: psycopg.Connection,
) -> tuple[list[dict], dict[str, dict], dict[tuple, dict]]:
    """Pull the most recent snapshot's events and the rows they reference.

    Returns (events, objects_by_spkid, approaches_by_key). "Most recent
    snapshot" = the latest snapshot_date that has both objects and
    close_approaches loaded.
    """
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT snapshot_date FROM (
                SELECT DISTINCT snapshot_date FROM objects_snapshots
                INTERSECT
                SELECT DISTINCT snapshot_date FROM close_approaches_snapshots
            ) s
            ORDER BY snapshot_date DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return [], {}, {}
        snapshot_date = row["snapshot_date"]

        cur.execute(
            "SELECT * FROM objects_snapshots WHERE snapshot_date = %s",
            (snapshot_date,),
        )
        objects_by_spkid = {row["spkid"]: row for row in cur.fetchall()}

        cur.execute(
            "SELECT * FROM close_approaches_snapshots WHERE snapshot_date = %s",
            (snapshot_date,),
        )
        approaches_by_key = {
            (row["spkid"], row["approach_date"], row["body"]): row
            for row in cur.fetchall()
        }

        # Events emitted in this snapshot's diff. We use observed_at within
        # the same UTC day as snapshot_date to scope; alerts are idempotent
        # via dedup_key so over-broad selection is harmless.
        cur.execute(
            "SELECT * FROM approach_events "
            "WHERE observed_at::date = %s ORDER BY observed_at",
            (snapshot_date,),
        )
        events = list(cur.fetchall())

    return events, objects_by_spkid, approaches_by_key


__all__ = [
    "ALL_RULES",
    "DEFAULT_ALBEDO",
    "DIAMETER_FORMULA_CONSTANT_KM",
    "LATE_WARNING_WINDOW_DAYS",
    "RULE_SHORT_ARC_LATE_WARNING",
    "RULE_SIZE_AND_DISTANCE",
    "RULE_VERY_CLOSE_ANY_SIZE",
    "SHORT_ARC_DAYS",
    "SIZE_RULE_DISTANCE_LD",
    "SIZE_THRESHOLD_KM",
    "VERY_CLOSE_DISTANCE_LD",
    "best_diameter_km",
    "derive_diameter_km",
    "evaluate",
    "evaluate_batch",
    "rule_short_arc_late_warning",
    "rule_size_and_distance",
    "rule_very_close_any_size",
    "run",
]
