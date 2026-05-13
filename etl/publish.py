"""Render the public feeds and write them to the public/ directory.

Three artifacts:
  - public/upcoming.{rss,json}     — every close approach in the next 60 days
  - public/noteworthy.{rss,json}   — alerts that crossed threshold rules
  - public/health.json             — last-run timestamp + record counts

Renderers are pure functions of (rows, generated_at, base_url) so the
trickiest part (XML escaping, date formatting) is unit-testable without a
DB. The DB-facing fetch functions are thin SELECTs against the raw landing
tables; once Phase 2 lands its dbt marts, those queries can switch to
mart_upcoming_approaches.

Idempotency: writing the same input on the same UTC second yields
byte-identical output. The lastBuildDate field uses the supplied
generated_at, so callers control reproducibility.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import psycopg

from etl.load import connect

DEFAULT_BASE_URL = "https://close-encounters.vercel.app"
UPCOMING_WINDOW_DAYS = 60
NOTEWORTHY_LIMIT = 100


# ---------------------------------------------------------------------------
# Renderers — pure functions
# ---------------------------------------------------------------------------


def render_upcoming_json(rows: Iterable[dict[str, Any]], *, generated_at: datetime) -> str:
    payload = {
        "generated_at": _iso(generated_at),
        "window_days": UPCOMING_WINDOW_DAYS,
        "count": 0,
        "items": [],
    }
    items = []
    for row in rows:
        items.append(
            {
                "designation": row.get("designation"),
                "spkid": row.get("spkid"),
                "full_name": row.get("full_name"),
                "approach_date": _iso(row["approach_date"]),
                "distance_au": _maybe_float(row.get("distance_au")),
                "distance_ld": _maybe_float(row.get("distance_ld")),
                "v_rel_km_s": _maybe_float(row.get("v_rel_km_s")),
                "diameter_estimate_km": _maybe_float(row.get("diameter_estimate_km")),
                "absolute_magnitude_h": _maybe_float(row.get("absolute_magnitude_h")),
                "orbit_class": row.get("orbit_class"),
            }
        )
    payload["items"] = items
    payload["count"] = len(items)
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def render_noteworthy_json(rows: Iterable[dict[str, Any]], *, generated_at: datetime) -> str:
    payload = {
        "generated_at": _iso(generated_at),
        "count": 0,
        "items": [],
    }
    items = []
    for row in rows:
        items.append(
            {
                "alert_id": row.get("alert_id"),
                "fired_at": _iso(row["fired_at"]),
                "rule_id": row.get("rule_id"),
                "spkid": row.get("spkid"),
                "designation": row.get("designation"),
                "approach_date": _iso(row["approach_date"]),
                "rationale": row.get("rationale"),
                "payload": row.get("payload"),
            }
        )
    payload["items"] = items
    payload["count"] = len(items)
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def render_upcoming_rss(
    rows: Iterable[dict[str, Any]],
    *,
    generated_at: datetime,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    rows = list(rows)
    items_xml = "\n".join(_upcoming_rss_item(row, base_url) for row in rows)
    return _rss_envelope(
        title="close encounters — upcoming approaches",
        link=base_url,
        description=(
            "Near-Earth objects forecast to pass close to Earth in the next "
            f"{UPCOMING_WINDOW_DAYS} days. Sourced from NASA JPL CNEOS."
        ),
        generated_at=generated_at,
        items_xml=items_xml,
    )


def render_noteworthy_rss(
    rows: Iterable[dict[str, Any]],
    *,
    generated_at: datetime,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    rows = list(rows)
    items_xml = "\n".join(_noteworthy_rss_item(row, base_url) for row in rows)
    return _rss_envelope(
        title="close encounters — noteworthy alerts",
        link=f"{base_url}/alerts",
        description=(
            "Threshold-rule alerts: sizeable objects inside the lunar "
            "distance, very-close approaches, late-warning new objects. "
            "Append-only — corrections are emitted as new alerts."
        ),
        generated_at=generated_at,
        items_xml=items_xml,
    )


def render_health_json(
    *,
    generated_at: datetime,
    upcoming_count: int,
    noteworthy_count: int,
    latest_snapshot_date: date | None,
) -> str:
    payload = {
        "status": "ok",
        "generated_at": _iso(generated_at),
        "latest_snapshot_date": (
            latest_snapshot_date.isoformat() if latest_snapshot_date else None
        ),
        "upcoming_count": upcoming_count,
        "noteworthy_count": noteworthy_count,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# DB-facing fetchers
# ---------------------------------------------------------------------------


def fetch_upcoming(conn: psycopg.Connection, *, window_days: int = UPCOMING_WINDOW_DAYS, now: datetime | None = None) -> list[dict[str, Any]]:
    """All approaches in the latest snapshot that fall within [now, now+window]."""
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=window_days)
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT MAX(snapshot_date) AS d FROM close_approaches_snapshots
            )
            SELECT
                ca.designation,
                ca.spkid,
                os.full_name,
                ca.approach_date,
                ca.body,
                ca.distance_au,
                ca.distance_ld,
                ca.v_rel_km_s,
                ca.v_inf_km_s,
                os.diameter_estimate_km,
                os.absolute_magnitude_h,
                os.orbit_class
            FROM close_approaches_snapshots ca
            LEFT JOIN objects_snapshots os
                   ON os.spkid = ca.spkid
                  AND os.snapshot_date = ca.snapshot_date
            WHERE ca.snapshot_date = (SELECT d FROM latest)
              AND ca.body = 'Earth'
              AND ca.approach_date >= %s
              AND ca.approach_date <= %s
            ORDER BY ca.approach_date ASC
            """,
            (now, end),
        )
        return list(cur.fetchall())


def fetch_noteworthy(conn: psycopg.Connection, *, limit: int = NOTEWORTHY_LIMIT) -> list[dict[str, Any]]:
    """Most recent N alerts joined to designation for display."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
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
                ORDER BY snapshot_date DESC
                LIMIT 1
            ) os ON TRUE
            ORDER BY a.fired_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def fetch_latest_snapshot_date(conn: psycopg.Connection):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(snapshot_date) FROM close_approaches_snapshots")
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run(
    database_url: str | None = None,
    *,
    output_dir: str | os.PathLike = "public",
    base_url: str = DEFAULT_BASE_URL,
    now: datetime | None = None,
) -> dict[str, int]:
    """Read the latest snapshot, render all five public artifacts, write them."""
    url = database_url or os.environ["DATABASE_URL"]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated_at = now or datetime.now(timezone.utc)

    with connect(url) as conn:
        upcoming = fetch_upcoming(conn, now=generated_at)
        noteworthy = fetch_noteworthy(conn)
        latest_snap = fetch_latest_snapshot_date(conn)

    (out / "upcoming.json").write_text(render_upcoming_json(upcoming, generated_at=generated_at))
    (out / "upcoming.rss").write_text(
        render_upcoming_rss(upcoming, generated_at=generated_at, base_url=base_url)
    )
    (out / "noteworthy.json").write_text(render_noteworthy_json(noteworthy, generated_at=generated_at))
    (out / "noteworthy.rss").write_text(
        render_noteworthy_rss(noteworthy, generated_at=generated_at, base_url=base_url)
    )
    (out / "health.json").write_text(
        render_health_json(
            generated_at=generated_at,
            upcoming_count=len(upcoming),
            noteworthy_count=len(noteworthy),
            latest_snapshot_date=latest_snap,
        )
    )

    return {
        "upcoming": len(upcoming),
        "noteworthy": len(noteworthy),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rss_envelope(
    *,
    title: str,
    link: str,
    description: str,
    generated_at: datetime,
    items_xml: str,
) -> str:
    pubdate = format_datetime(generated_at)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{xml_escape(title)}</title>\n"
        f"    <link>{xml_escape(link)}</link>\n"
        f"    <description>{xml_escape(description)}</description>\n"
        '    <language>en-us</language>\n'
        f"    <lastBuildDate>{pubdate}</lastBuildDate>\n"
        f"    <pubDate>{pubdate}</pubDate>\n"
        f"{items_xml}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def _upcoming_rss_item(row: dict[str, Any], base_url: str) -> str:
    designation = row.get("designation") or row.get("spkid") or "?"
    approach_date = row["approach_date"]
    distance_ld = row.get("distance_ld")
    distance_str = f"{distance_ld:.2f} LD" if distance_ld is not None else "unknown distance"
    title = f"{designation} — {approach_date.strftime('%Y-%m-%d')} — {distance_str}"

    description_pieces = [f"Approach: {_iso(approach_date)}"]
    if distance_ld is not None:
        description_pieces.append(f"distance {distance_ld:.3f} LD")
    if row.get("v_rel_km_s") is not None:
        description_pieces.append(f"velocity {row['v_rel_km_s']:.1f} km/s")
    if row.get("diameter_estimate_km") is not None:
        description_pieces.append(
            f"estimated diameter {row['diameter_estimate_km'] * 1000:.0f} m"
        )
    if row.get("orbit_class"):
        description_pieces.append(f"orbit class {row['orbit_class']}")
    description = "; ".join(description_pieces)

    guid = f"{base_url}/objects/{row.get('spkid') or designation}#{_iso(approach_date)}"
    return (
        "    <item>\n"
        f"      <title>{xml_escape(title)}</title>\n"
        f"      <link>{xml_escape(base_url)}/objects/{xml_escape(str(row.get('spkid') or designation))}</link>\n"
        f"      <guid isPermaLink=\"false\">{xml_escape(guid)}</guid>\n"
        f"      <pubDate>{format_datetime(approach_date)}</pubDate>\n"
        f"      <description>{xml_escape(description)}</description>\n"
        "    </item>"
    )


def _noteworthy_rss_item(row: dict[str, Any], base_url: str) -> str:
    designation = row.get("designation") or row.get("spkid") or "?"
    approach_date = row["approach_date"]
    fired_at = row["fired_at"]
    rule_id = row.get("rule_id") or "?"
    title = f"Alert ({rule_id}): {designation} — {approach_date.strftime('%Y-%m-%d')}"
    description = row.get("rationale") or ""
    guid = f"{base_url}/alerts/{row.get('alert_id') or row.get('dedup_key') or fired_at.isoformat()}"
    return (
        "    <item>\n"
        f"      <title>{xml_escape(title)}</title>\n"
        f"      <link>{xml_escape(base_url)}/objects/{xml_escape(str(row.get('spkid') or designation))}</link>\n"
        f"      <guid isPermaLink=\"false\">{xml_escape(guid)}</guid>\n"
        f"      <pubDate>{format_datetime(fired_at)}</pubDate>\n"
        f"      <category>{xml_escape(rule_id)}</category>\n"
        f"      <description>{xml_escape(description)}</description>\n"
        "    </item>"
    )


def _iso(d: datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    import sys

    summary = run()
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_BASE_URL",
    "NOTEWORTHY_LIMIT",
    "UPCOMING_WINDOW_DAYS",
    "fetch_latest_snapshot_date",
    "fetch_noteworthy",
    "fetch_upcoming",
    "render_health_json",
    "render_noteworthy_json",
    "render_noteworthy_rss",
    "render_upcoming_json",
    "render_upcoming_rss",
    "run",
]
