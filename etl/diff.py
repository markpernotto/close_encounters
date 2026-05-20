"""Diff successive snapshots into approach_events.

Pure functions: compute_events takes two in-memory snapshots and returns
event dicts. The orchestrator (etl.diff.run) is responsible for fetching
the previous and current snapshots from Postgres and writing the events
back via etl.load.load_events.

Idempotent: dedup_key is deterministic for the same (event_type, spkid,
approach_date, new_value) tuple, so re-running the same diff is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import psycopg

from etl.load import connect, load_events

EVENT_NEW_OBJECT = "NEW_OBJECT"
EVENT_NEW_APPROACH = "NEW_APPROACH"
EVENT_REVISED_APPROACH = "REVISED_APPROACH"
EVENT_RISK_CLASS_CHANGE = "RISK_CLASS_CHANGE"

# Risk-assessment fields whose change between snapshots triggers a
# RISK_CLASS_CHANGE event. Other columns (diameter, v_inf, year range)
# can shift slightly without changing the risk picture; these four do.
_RISK_TRACKED_FIELDS = (
    "torino_scale",
    "palermo_scale",
    "impact_probability",
    "risk_class",
)


def compute_dedup_key(
    *,
    event_type: str,
    spkid: str | None = None,
    approach_date: datetime | None = None,
    new_value: Any = None,
    designation: str | None = None,
    agency: str | None = None,
) -> str:
    """Deterministic key. Same inputs → same key, regardless of when computed.

    Approach events only pass spkid + approach_date + new_value (legacy
    behavior). Risk events also pass designation + agency. Optional
    fields are only included in the hash payload when set, so existing
    approach-event keys remain stable after this extension.
    """
    payload_dict: dict[str, Any] = {
        "event_type": event_type,
        "spkid": spkid,
        "approach_date": approach_date.isoformat() if approach_date else None,
        "new_value": new_value,
    }
    if designation is not None:
        payload_dict["designation"] = designation
    if agency is not None:
        payload_dict["agency"] = agency
    payload = json.dumps(payload_dict, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_events(
    *,
    prev_objects: Iterable[dict[str, Any]],
    curr_objects: Iterable[dict[str, Any]],
    prev_approaches: Iterable[dict[str, Any]],
    curr_approaches: Iterable[dict[str, Any]],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Compute event rows from two consecutive snapshots.

    Each snapshot is a list of dicts whose keys match the columns of
    objects_snapshots / close_approaches_snapshots respectively. Order does
    not matter; we index by primary-key columns.

    Emitted event types:
      - NEW_OBJECT: an spkid present in curr_objects but not in prev_objects.
        approach_date is the soonest upcoming close approach for that spkid in
        curr_approaches; if the new object has no approach in curr_approaches
        we fall back to the snapshot date so the event still has a timestamp.
      - NEW_APPROACH: an (spkid, approach_date, body) tuple present in
        curr_approaches but not in prev_approaches, AND the spkid was already
        in prev_objects (otherwise it would double-fire with NEW_OBJECT).
      - REVISED_APPROACH: an (spkid, approach_date, body) tuple present in
        both prev_approaches and curr_approaches whose distance_au or v_rel_km_s
        or orbit_id has changed.
    """
    prev_obj_keys = {o["spkid"] for o in prev_objects}
    curr_obj_by_spkid = {o["spkid"]: o for o in curr_objects}

    prev_app_index = _index_approaches(prev_approaches)
    curr_app_index = _index_approaches(curr_approaches)

    events: list[dict[str, Any]] = []

    # NEW_OBJECT — spkids in curr that weren't in prev.
    new_object_spkids = set(curr_obj_by_spkid) - prev_obj_keys
    for spkid in sorted(new_object_spkids):
        first_approach = _first_upcoming_approach(spkid, curr_app_index)
        approach_date = first_approach["approach_date"] if first_approach else observed_at
        new_value = curr_obj_by_spkid[spkid]
        events.append(
            _make_event(
                event_type=EVENT_NEW_OBJECT,
                spkid=spkid,
                approach_date=approach_date,
                prev_value=None,
                new_value=new_value,
                diff_summary=f"New object {new_value.get('designation') or spkid}",
                observed_at=observed_at,
            )
        )

    # NEW_APPROACH — approach keys in curr that weren't in prev, and the spkid
    # is not itself a new object (those are folded into NEW_OBJECT instead).
    for key, curr_row in curr_app_index.items():
        if key in prev_app_index:
            continue
        spkid = curr_row["spkid"]
        if spkid in new_object_spkids:
            continue
        events.append(
            _make_event(
                event_type=EVENT_NEW_APPROACH,
                spkid=spkid,
                approach_date=curr_row["approach_date"],
                prev_value=None,
                new_value=curr_row,
                diff_summary=(
                    f"New approach for {curr_row.get('designation') or spkid} on "
                    f"{curr_row['approach_date'].date().isoformat()}"
                ),
                observed_at=observed_at,
            )
        )

    # REVISED_APPROACH — same approach key in both, but a tracked field changed.
    for key, curr_row in curr_app_index.items():
        prev_row = prev_app_index.get(key)
        if prev_row is None:
            continue
        if not _is_revised(prev_row, curr_row):
            continue
        events.append(
            _make_event(
                event_type=EVENT_REVISED_APPROACH,
                spkid=curr_row["spkid"],
                approach_date=curr_row["approach_date"],
                prev_value=_revision_signature(prev_row),
                new_value=_revision_signature(curr_row),
                diff_summary=_revision_summary(prev_row, curr_row),
                observed_at=observed_at,
            )
        )

    return events


def compute_risk_events(
    *,
    prev_risks: Iterable[dict[str, Any]],
    curr_risks: Iterable[dict[str, Any]],
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Compute RISK_CLASS_CHANGE events from two consecutive snapshots of
    risk_assessments.

    Three sub-cases emit:
      - **added**:    (agency, designation) present in curr_risks but not prev.
                      prev_value=None, new_value=<the tracked fields>.
      - **changed**:  present in both, any of _RISK_TRACKED_FIELDS differs.
      - **retracted**: present in prev_risks but not curr. new_value=None.

    Agency + designation are first-class on the event so a NASA-published
    change and an ESA-published change for the same body produce two
    distinct events.
    """
    prev_idx = {(r["agency"], r["designation"]): r for r in prev_risks}
    curr_idx = {(r["agency"], r["designation"]): r for r in curr_risks}

    events: list[dict[str, Any]] = []

    # Newly added — present in curr only.
    for key in curr_idx.keys() - prev_idx.keys():
        agency, designation = key
        curr_row = curr_idx[key]
        new_value = _risk_signature(curr_row)
        events.append(
            _make_event(
                event_type=EVENT_RISK_CLASS_CHANGE,
                spkid=_maybe_spkid(curr_row),
                approach_date=None,
                prev_value=None,
                new_value=new_value,
                diff_summary=_risk_added_summary(agency, designation, new_value),
                observed_at=observed_at,
                designation=designation,
                agency=agency,
            )
        )

    # Changed — present in both, any tracked field differs.
    for key in curr_idx.keys() & prev_idx.keys():
        agency, designation = key
        prev_row = prev_idx[key]
        curr_row = curr_idx[key]
        if not _risk_is_changed(prev_row, curr_row):
            continue
        prev_value = _risk_signature(prev_row)
        new_value = _risk_signature(curr_row)
        events.append(
            _make_event(
                event_type=EVENT_RISK_CLASS_CHANGE,
                spkid=_maybe_spkid(curr_row) or _maybe_spkid(prev_row),
                approach_date=None,
                prev_value=prev_value,
                new_value=new_value,
                diff_summary=_risk_changed_summary(agency, designation, prev_value, new_value),
                observed_at=observed_at,
                designation=designation,
                agency=agency,
            )
        )

    # Retracted — present in prev only.
    for key in prev_idx.keys() - curr_idx.keys():
        agency, designation = key
        prev_row = prev_idx[key]
        prev_value = _risk_signature(prev_row)
        events.append(
            _make_event(
                event_type=EVENT_RISK_CLASS_CHANGE,
                spkid=_maybe_spkid(prev_row),
                approach_date=None,
                prev_value=prev_value,
                new_value=None,
                diff_summary=_risk_retracted_summary(agency, designation),
                observed_at=observed_at,
                designation=designation,
                agency=agency,
            )
        )

    return events


def _risk_signature(row: dict[str, Any]) -> dict[str, Any]:
    """The canonical risk-event payload — only the fields whose change we
    care about. Stable across reruns (no dates, no source URLs)."""
    return {f: row.get(f) for f in _RISK_TRACKED_FIELDS}


def _risk_is_changed(prev: dict[str, Any], curr: dict[str, Any]) -> bool:
    return any(prev.get(f) != curr.get(f) for f in _RISK_TRACKED_FIELDS)


def _maybe_spkid(row: dict[str, Any]) -> str | None:
    spkid = row.get("spkid")
    return str(spkid) if spkid else None


def _risk_added_summary(agency: str, designation: str, new_value: dict[str, Any]) -> str:
    ps = new_value.get("palermo_scale")
    ts = new_value.get("torino_scale")
    bits = [f"added to {agency}"]
    if ps is not None:
        bits.append(f"Palermo {ps}")
    if ts is not None and ts > 0:
        bits.append(f"Torino {ts}")
    return f"{designation}: {', '.join(bits)}"


def _risk_changed_summary(
    agency: str,
    designation: str,
    prev: dict[str, Any],
    curr: dict[str, Any],
) -> str:
    pieces = []
    for f in _RISK_TRACKED_FIELDS:
        if prev.get(f) != curr.get(f):
            pieces.append(f"{f}: {prev.get(f)} → {curr.get(f)}")
    return f"{designation} ({agency}): {'; '.join(pieces)}"


def _risk_retracted_summary(agency: str, designation: str) -> str:
    return f"{designation}: removed from {agency} risk list"


def run(database_url: str | None = None) -> int:
    """Fetch the latest two snapshots, compute events, write to approach_events.

    Returns the number of NEW events actually inserted (excluding dedup hits).
    First-ever run (only one snapshot) emits zero events without erroring.
    """
    url = database_url or os.environ["DATABASE_URL"]
    with connect(url) as conn:
        snapshots = _two_latest_snapshot_dates(conn)
        if len(snapshots) < 2:
            return 0
        prev_date, curr_date = snapshots
        prev_objects = _fetch_objects(conn, prev_date)
        curr_objects = _fetch_objects(conn, curr_date)
        prev_approaches = _fetch_approaches(conn, prev_date)
        curr_approaches = _fetch_approaches(conn, curr_date)
        observed_at = datetime.now().astimezone()
        events = compute_events(
            prev_objects=prev_objects,
            curr_objects=curr_objects,
            prev_approaches=prev_approaches,
            curr_approaches=curr_approaches,
            observed_at=observed_at,
        )
        # Risk-class-change events come from a parallel diff against the
        # most recent two distinct assessment_dates in risk_assessments.
        # Independent of the close-approach snapshot dates because the
        # Sentry/NEOCC pulls happen alongside but on their own schedule.
        risk_dates = _two_latest_risk_assessment_dates(conn)
        if len(risk_dates) >= 2:
            prev_risks = _fetch_risk_assessments(conn, risk_dates[0])
            curr_risks = _fetch_risk_assessments(conn, risk_dates[1])
            events.extend(
                compute_risk_events(
                    prev_risks=prev_risks,
                    curr_risks=curr_risks,
                    observed_at=observed_at,
                )
            )
        with conn.transaction():
            written = load_events(conn, events)
        return written


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index_approaches(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, datetime, str], dict[str, Any]]:
    return {(r["spkid"], r["approach_date"], r["body"]): r for r in rows}


def _first_upcoming_approach(spkid: str, index: dict) -> dict[str, Any] | None:
    candidates = [row for key, row in index.items() if key[0] == spkid]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r["approach_date"])


_REVISION_FIELDS = ("distance_au", "v_rel_km_s", "orbit_id")


def _is_revised(prev: dict[str, Any], curr: dict[str, Any]) -> bool:
    return any(prev.get(f) != curr.get(f) for f in _REVISION_FIELDS)


def _revision_signature(row: dict[str, Any]) -> dict[str, Any]:
    return {f: row.get(f) for f in _REVISION_FIELDS}


def _revision_summary(prev: dict[str, Any], curr: dict[str, Any]) -> str:
    pieces = []
    for f in _REVISION_FIELDS:
        if prev.get(f) != curr.get(f):
            pieces.append(f"{f}: {prev.get(f)} → {curr.get(f)}")
    return "; ".join(pieces)


def _make_event(
    *,
    event_type: str,
    spkid: str | None,
    approach_date: datetime | None,
    prev_value: Any,
    new_value: Any,
    diff_summary: str,
    observed_at: datetime,
    designation: str | None = None,
    agency: str | None = None,
) -> dict[str, Any]:
    return {
        "observed_at": observed_at,
        "spkid": spkid,
        "designation": designation,
        "agency": agency,
        "approach_date": approach_date,
        "event_type": event_type,
        "prev_value": prev_value,
        "new_value": new_value,
        "diff_summary": diff_summary,
        "dedup_key": compute_dedup_key(
            event_type=event_type,
            spkid=spkid,
            approach_date=approach_date,
            new_value=new_value,
            designation=designation,
            agency=agency,
        ),
    }


def _two_latest_snapshot_dates(conn: psycopg.Connection) -> list:
    """Return the two most recent snapshot_dates that exist in BOTH tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_date FROM (
                SELECT DISTINCT snapshot_date FROM objects_snapshots
                INTERSECT
                SELECT DISTINCT snapshot_date FROM close_approaches_snapshots
            ) s
            ORDER BY snapshot_date DESC
            LIMIT 2
            """
        )
        rows = [r[0] for r in cur.fetchall()]
    return list(reversed(rows))  # oldest first → [prev, curr]


def _fetch_objects(conn: psycopg.Connection, snapshot_date) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT * FROM objects_snapshots WHERE snapshot_date = %s",
            (snapshot_date,),
        )
        return list(cur.fetchall())


def _fetch_approaches(conn: psycopg.Connection, snapshot_date) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT * FROM close_approaches_snapshots WHERE snapshot_date = %s",
            (snapshot_date,),
        )
        return list(cur.fetchall())


def _two_latest_risk_assessment_dates(conn: psycopg.Connection) -> list:
    """Most recent two distinct assessment_dates in risk_assessments. Returns
    [prev_date, curr_date] (oldest first) so the diff treats them in temporal
    order."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT assessment_date
            FROM risk_assessments
            ORDER BY assessment_date DESC
            LIMIT 2
            """
        )
        rows = [r[0] for r in cur.fetchall()]
    return list(reversed(rows))


def _fetch_risk_assessments(conn: psycopg.Connection, assessment_date) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT * FROM risk_assessments WHERE assessment_date = %s",
            (assessment_date,),
        )
        return list(cur.fetchall())


def main() -> None:
    import json
    import sys

    written = run()
    json.dump({"events_written": written}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


__all__ = [
    "EVENT_NEW_APPROACH",
    "EVENT_NEW_OBJECT",
    "EVENT_REVISED_APPROACH",
    "EVENT_RISK_CLASS_CHANGE",
    "compute_dedup_key",
    "compute_events",
    "compute_risk_events",
    "run",
]
