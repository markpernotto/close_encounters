"""End-to-end nightly orchestrator.

Pull CNEOS for the next 60 days, look up each unique designation in SBDB,
snapshot raw JSON to Cloudflare R2 with provenance (sha256 + bytes + key),
normalize via etl.transform, UPSERT into Postgres via etl.load, and append
or replace today's line in data/MANIFEST.jsonl.

Design notes:

- Idempotent. Re-running on the same UTC date overwrites the same R2 keys,
  UPSERTs the same primary keys, and replaces the MANIFEST line for that
  date. No duplicate rows, no duplicate manifest entries.
- Dependency-injected. `cneos_fetch`, `sbdb_fetch`, `put_raw`, `db_conn`,
  and `now` are all parameterizable. Defaults wire up the real JPL APIs,
  R2 client, and Postgres connection. Unit tests pass in fakes.
- The pure work (gather + normalize + manifest assembly) is in
  `gather_snapshot()`; `run()` is the thin glue that adds DB writes and
  manifest persistence.
- SBDB failures for individual objects are recorded, not raised. One bad
  designation should not abort the whole night.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from etl import load
from etl import r2 as r2_module
from etl import transform
from etl.sources import jpl_cneos, jpl_sbdb

DEFAULT_WINDOW_DAYS = 60
DEFAULT_DIST_MAX_AU = 0.05  # ~19.5 LD
SBDB_REQUEST_DELAY_SEC = 0.5
MANIFEST_PATH = Path("data/MANIFEST.jsonl")


@dataclass
class GatheredSnapshot:
    snapshot_date: date
    retrieved_at: datetime
    object_rows: list[dict[str, Any]]
    orbit_rows: list[dict[str, Any]]
    approach_rows: list[dict[str, Any]]
    manifest_entry: dict[str, Any]
    sbdb_pulls: int
    sbdb_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def unique_designations(cneos_rows: Iterable[dict[str, Any]]) -> list[str]:
    """Dedupe designations from CNEOS rows, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for row in cneos_rows:
        d = row.get("des")
        if d and d not in seen:
            seen.add(d)
            out.append(str(d))
    return out


def r2_key_for_cneos(snapshot_date: date) -> str:
    return f"snapshots/{snapshot_date.isoformat()}/cneos.json"


def r2_key_for_sbdb(snapshot_date: date, spkid: str) -> str:
    return f"snapshots/{snapshot_date.isoformat()}/sbdb/{spkid}.json"


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def merge_manifest(existing_lines: Iterable[str], new_entry: dict[str, Any]) -> list[str]:
    """Replace any manifest line whose snapshot_date matches new_entry's;
    preserve everything else; append if no match. Idempotent.
    """
    target = new_entry["snapshot_date"]
    out: list[str] = []
    replaced = False
    for raw in existing_lines:
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        if parsed.get("snapshot_date") == target:
            if not replaced:
                out.append(json.dumps(new_entry, sort_keys=True))
                replaced = True
            # subsequent matches (shouldn't exist, defensive) are dropped
        else:
            out.append(line)
    if not replaced:
        out.append(json.dumps(new_entry, sort_keys=True))
    return out


def write_manifest(path: Path, new_entry: dict[str, Any]) -> None:
    existing = path.read_text().splitlines() if path.exists() else []
    merged = merge_manifest(existing, new_entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(merged) + "\n")


# ---------------------------------------------------------------------------
# Gather — pulls + uploads + normalization, no DB
# ---------------------------------------------------------------------------


def gather_snapshot(
    *,
    snapshot_date: date,
    retrieved_at: datetime,
    cneos_fetch: Callable[..., dict[str, Any]],
    sbdb_fetch: Callable[[str], dict[str, Any]],
    put_raw: Callable[[str, bytes], None],
    window_days: int = DEFAULT_WINDOW_DAYS,
    dist_max_au: float = DEFAULT_DIST_MAX_AU,
    sbdb_delay_sec: float = SBDB_REQUEST_DELAY_SEC,
) -> GatheredSnapshot:
    """Pull CNEOS + SBDB, upload raw to R2 via put_raw, return normalized rows."""
    date_min = snapshot_date.isoformat()
    date_max = (snapshot_date + timedelta(days=window_days)).isoformat()

    # 1. CNEOS — single request for the entire window.
    cneos_payload = cneos_fetch(date_min=date_min, date_max=date_max, dist_max_au=dist_max_au)
    cneos_bytes = json.dumps(cneos_payload, sort_keys=True, default=str).encode("utf-8")
    cneos_key = r2_key_for_cneos(snapshot_date)
    put_raw(cneos_key, cneos_bytes)
    cneos_rows = jpl_cneos._flatten(cneos_payload)

    # 2. SBDB — one request per unique designation, politely paced.
    designations = unique_designations(cneos_rows)
    sbdb_pulls = 0
    sbdb_errors: list[str] = []
    object_rows: list[dict[str, Any]] = []
    orbit_rows: list[dict[str, Any]] = []
    desig_to_spkid: dict[str, str] = {}
    sbdb_sources: list[dict[str, Any]] = []

    for i, designation in enumerate(designations):
        if i > 0 and sbdb_delay_sec > 0:
            time.sleep(sbdb_delay_sec)
        try:
            sbdb_payload = sbdb_fetch(designation)
            sbdb_pulls += 1
        except Exception as exc:  # noqa: BLE001 — record and continue
            sbdb_errors.append(f"{designation}: {exc!r}")
            continue
        spkid = str((sbdb_payload.get("object") or {}).get("spkid") or "")
        if not spkid:
            sbdb_errors.append(f"{designation}: no spkid in response")
            continue
        sbdb_bytes = json.dumps(sbdb_payload, sort_keys=True, default=str).encode("utf-8")
        sbdb_key = r2_key_for_sbdb(snapshot_date, spkid)
        put_raw(sbdb_key, sbdb_bytes)
        sbdb_sources.append(
            {
                "kind": "sbdb",
                "r2_key": sbdb_key,
                "sha256": sha256_hex(sbdb_bytes),
                "bytes": len(sbdb_bytes),
                "designation": designation,
                "spkid": spkid,
            }
        )
        desig_to_spkid[designation] = spkid
        object_rows.append(
            transform.normalize_sbdb_object(
                sbdb_payload,
                snapshot_date=snapshot_date,
                source_retrieved_at=retrieved_at,
            )
        )
        orbit_rows.append(
            transform.normalize_sbdb_orbit_elements(
                sbdb_payload, source_retrieved_at=retrieved_at
            )
        )

    # 3. Normalize close approaches with spkids resolved in-process.
    approach_rows: list[dict[str, Any]] = []
    for cneos_row in cneos_rows:
        spkid = desig_to_spkid.get(str(cneos_row.get("des") or ""))
        approach_rows.append(
            transform.normalize_close_approach(
                cneos_row,
                snapshot_date=snapshot_date,
                spkid=spkid,
                source_retrieved_at=retrieved_at,
            )
        )

    # 4. Manifest entry.
    cneos_source = {
        "kind": "cneos",
        "r2_key": cneos_key,
        "sha256": sha256_hex(cneos_bytes),
        "bytes": len(cneos_bytes),
        "rows": len(cneos_rows),
    }
    manifest_entry = {
        "snapshot_date": snapshot_date.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "extraction_version": transform.EXTRACTION_VERSION,
        "sources": [cneos_source, *sbdb_sources],
        "sbdb_pulls": sbdb_pulls,
        "sbdb_errors": sbdb_errors,
    }

    return GatheredSnapshot(
        snapshot_date=snapshot_date,
        retrieved_at=retrieved_at,
        object_rows=object_rows,
        orbit_rows=orbit_rows,
        approach_rows=approach_rows,
        manifest_entry=manifest_entry,
        sbdb_pulls=sbdb_pulls,
        sbdb_errors=sbdb_errors,
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def run(
    *,
    snapshot_date: date | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    dist_max_au: float = DEFAULT_DIST_MAX_AU,
    sbdb_delay_sec: float = SBDB_REQUEST_DELAY_SEC,
    cneos_fetch: Callable[..., dict[str, Any]] | None = None,
    sbdb_fetch: Callable[[str], dict[str, Any]] | None = None,
    put_raw: Callable[[str, bytes], None] | None = None,
    db_conn: Any | None = None,
    database_url: str | None = None,
    manifest_path: Path = MANIFEST_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one nightly extract. Returns a summary dict (used as CLI output)."""
    retrieved_at = now or datetime.now(timezone.utc)
    snapshot_date = snapshot_date or retrieved_at.date()

    if cneos_fetch is None:
        cneos_fetch = jpl_cneos.fetch_close_approaches_raw
    if sbdb_fetch is None:
        sbdb_fetch = jpl_sbdb.lookup_object
    if put_raw is None:
        client = r2_module.get_client()

        def put_raw(key: str, body: bytes) -> None:
            r2_module.upload_object(client, key, body, content_type="application/json")

    gathered = gather_snapshot(
        snapshot_date=snapshot_date,
        retrieved_at=retrieved_at,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        window_days=window_days,
        dist_max_au=dist_max_au,
        sbdb_delay_sec=sbdb_delay_sec,
    )

    own_conn = False
    if db_conn is None:
        db_conn = load.connect(database_url)
        own_conn = True
    try:
        with db_conn.transaction():
            n_obj = load.load_objects(db_conn, gathered.object_rows)
            n_orb = load.load_orbit_elements(db_conn, gathered.orbit_rows)
            n_app, n_skip = load.load_close_approaches(
                db_conn, gathered.approach_rows, designation_to_spkid={}
            )
    finally:
        if own_conn:
            db_conn.close()

    write_manifest(manifest_path, gathered.manifest_entry)

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "cneos_rows": len(gathered.approach_rows),
        "sbdb_pulls": gathered.sbdb_pulls,
        "sbdb_errors": gathered.sbdb_errors,
        "objects_loaded": n_obj,
        "orbit_elements_loaded": n_orb,
        "close_approaches_loaded": n_app,
        "close_approaches_skipped": n_skip,
    }


def main() -> None:
    summary = run()
    json.dump(summary, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_DIST_MAX_AU",
    "DEFAULT_WINDOW_DAYS",
    "MANIFEST_PATH",
    "SBDB_REQUEST_DELAY_SEC",
    "GatheredSnapshot",
    "gather_snapshot",
    "merge_manifest",
    "r2_key_for_cneos",
    "r2_key_for_sbdb",
    "run",
    "sha256_hex",
    "unique_designations",
    "write_manifest",
]
