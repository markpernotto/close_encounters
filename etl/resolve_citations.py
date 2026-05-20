"""Citation-graph resolver — Phase 3.

Connects objects to their discovery announcements (and follow-up
publications) via fetched MPECs. Today this is MPEC-only; Phase 3 Commit 3
will layer ADS bibcode resolution for journal papers on top.

Design:
  1. Find every spkid in discovery_attributions that has a known mpec_id
     but no row yet in object_publications.
  2. Fetch each MPEC's HTML once, parse it, UPSERT a discovery_publications
     row keyed on mpec_id.
  3. From the parsed MPEC, build object_publications links: featured
     designations get relationship='discovery' (high confidence); other
     mentioned designations get 'follow_up' (medium).
  4. Politely rate-limit the MPC fetches.

The resolver is idempotent — re-running over the same data UPSERTs into
the same rows and produces zero net inserts.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg

from etl import load, transform
from etl.sources import mpc_mpec

MPEC_REQUEST_DELAY_SEC = 1.0


@dataclass
class ResolveResult:
    mpec_ids_attempted: int = 0
    publications_loaded: int = 0
    object_publications_loaded: int = 0
    fetch_errors: list[str] = field(default_factory=list)


def run(
    database_url: str | None = None,
    *,
    mpec_fetch: Callable[[str], str] | None = None,
    mpec_request_delay_sec: float = MPEC_REQUEST_DELAY_SEC,
    now: datetime | None = None,
) -> ResolveResult:
    """Resolve MPEC citations for any discovery_attributions row that
    surfaces an mpec_id."""
    url = database_url or os.environ["DATABASE_URL"]
    resolved_at = now or datetime.now(UTC)
    if mpec_fetch is None:
        mpec_fetch = mpc_mpec.fetch_mpec_raw

    result = ResolveResult()
    with load.connect(url) as conn:
        rows = _fetch_attributions_with_mpec_ids(conn)
        # Dedupe to one fetch per unique mpec_id — many objects can share
        # an MPEC (a single announcement can list many discoveries).
        by_mpec: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_mpec.setdefault(r["mpec_id"], []).append(r)

        designation_to_spkid = {
            r["designation"]: r["spkid"]
            for r in _fetch_designation_spkid_map(conn)
            if r.get("spkid")
        }

        for i, (mpec_id, members) in enumerate(by_mpec.items()):
            if i > 0 and mpec_request_delay_sec > 0:
                time.sleep(mpec_request_delay_sec)
            result.mpec_ids_attempted += 1
            try:
                html = mpec_fetch(mpec_id)
            except Exception as exc:  # noqa: BLE001 — record and continue
                result.fetch_errors.append(f"{mpec_id}: {exc!r}")
                continue
            parsed = mpc_mpec.parse_mpec_html(html)
            # Parser might find a different mpec_id than what we queried
            # for (rare; e.g., the page redirected). Stick with what the
            # parser actually extracted so cross-references stay accurate.
            publication = transform.normalize_mpec_publication(
                parsed, resolved_at=resolved_at
            )
            if publication is None:
                result.fetch_errors.append(f"{mpec_id}: no parseable mpec_id in HTML")
                continue

            with conn.transaction():
                publication_id = load.load_publication(conn, publication)
                links = transform.mpec_object_links(
                    parsed,
                    publication_id=publication_id,
                    extracted_at=resolved_at,
                    designation_to_spkid=designation_to_spkid,
                )
                # Seed an explicit "this attribution row produced this
                # link" entry even if the parser didn't surface the
                # designation — the SBDB attribution itself is evidence.
                for member in members:
                    if member["designation"] not in {link["designation"] for link in links}:
                        links.append(
                            transform._object_publication_row(
                                designation=member["designation"],
                                publication_id=publication_id,
                                relationship=transform.RELATIONSHIP_DISCOVERY,
                                confidence=transform.CONFIDENCE_HIGH,
                                confidence_reason="SBDB discovery block referenced this MPEC",
                                extracted_from="sbdb_ref",
                                extracted_at=resolved_at,
                                spkid=member.get("spkid"),
                            )
                        )
                n = load.load_object_publications(conn, links)
            result.publications_loaded += 1
            result.object_publications_loaded += n

    return result


def _fetch_attributions_with_mpec_ids(
    conn: psycopg.Connection,
) -> list[dict[str, Any]]:
    """All discovery_attributions rows that have an mpec_id, joined to
    designation. Filters to those that don't already have a corresponding
    object_publications row, but only loosely — we use UPSERT downstream
    so over-selecting is harmless."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT da.spkid, da.mpec_id, os.designation
            FROM discovery_attributions da
            LEFT JOIN LATERAL (
                SELECT designation FROM objects_snapshots
                WHERE spkid = da.spkid
                ORDER BY snapshot_date DESC LIMIT 1
            ) os ON TRUE
            WHERE da.mpec_id IS NOT NULL
            """
        )
        return list(cur.fetchall())


def _fetch_designation_spkid_map(
    conn: psycopg.Connection,
) -> list[dict[str, Any]]:
    """Designation → spkid mapping across all snapshots, latest wins."""
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (designation) designation, spkid
            FROM objects_snapshots
            ORDER BY designation, snapshot_date DESC
            """
        )
        return list(cur.fetchall())


def main() -> None:
    result = run()
    summary = {
        "mpec_ids_attempted": result.mpec_ids_attempted,
        "publications_loaded": result.publications_loaded,
        "object_publications_loaded": result.object_publications_loaded,
        "fetch_errors": result.fetch_errors,
    }
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
