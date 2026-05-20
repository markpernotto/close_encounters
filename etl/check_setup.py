"""One-shot connectivity check for Neon (Postgres) and the snapshot backend.

Run with the venv active and .env populated:
    python -m etl.check_setup

Exit code 0 = all backends reachable and the Phase 1 schema is applied.

The snapshot backend is either Cloudflare R2 (default when all R2_* vars
are present) or the local filesystem (auto-fallback or STORAGE_BACKEND=local).
See etl/r2.py for backend selection rules.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from etl import r2 as r2_module


def _ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _info(msg: str) -> None:
    print(f"  • {msg}")


def _section(name: str) -> None:
    print(f"\n{name}")
    print("-" * len(name))


def check_env() -> list[str]:
    required = ["DATABASE_URL"]
    if r2_module.backend() == "r2":
        required.extend(
            [
                "R2_ACCOUNT_ID",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET_NAME",
                "R2_ENDPOINT_URL",
            ]
        )
    return [v for v in required if not os.getenv(v)]


def check_postgres() -> bool:
    url = os.environ["DATABASE_URL"]
    try:
        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            _ok(f"connected: {version.split(',')[0]}")

            expected = {
                "objects_snapshots",
                "orbit_elements_snapshots",
                "close_approaches_snapshots",
                "approach_events",
                "alerts",
                "risk_assessments",
                "discovery_attributions",
            }
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                ORDER BY table_name
                """,
                (sorted(expected),),
            )
            tables = {row[0] for row in cur.fetchall()}
            missing = expected - tables
            if missing:
                _fail(f"schema not fully applied — missing tables: {sorted(missing)}")
                print('    Run:  psql "$DATABASE_URL" -f etl/schema.sql')
                return False
            _ok(f"schema applied: tables {sorted(tables)} present")
            return True
    except psycopg.OperationalError as e:
        _fail(f"connection failed: {e}")
        return False


def check_storage() -> bool:
    """Verify the snapshot backend (R2 or local) is reachable + writable."""
    backend = r2_module.backend()
    bucket = r2_module.get_bucket()
    if backend == "local":
        local_dir = os.getenv("LOCAL_R2_DIR") or r2_module.DEFAULT_LOCAL_DIR
        _info(f"backend: local-filesystem at {local_dir}/{bucket}")
    else:
        _info(f"backend: Cloudflare R2 bucket {bucket!r}")

    client = r2_module.get_client()

    try:
        client.head_bucket(Bucket=bucket)
        _ok(f"bucket reachable: {bucket}")
    except (BotoCoreError, ClientError, OSError) as e:
        _fail(f"head_bucket failed: {e}")
        return False

    test_key = f"_setup_check/{datetime.now(UTC).isoformat()}.txt"
    payload = b"connectivity-check"

    try:
        client.put_object(Bucket=bucket, Key=test_key, Body=payload)
        _ok(f"write: put {test_key}")
    except (BotoCoreError, ClientError, OSError) as e:
        _fail(f"put_object failed: {e}")
        return False

    try:
        resp = client.get_object(Bucket=bucket, Key=test_key)
        body = resp["Body"].read()
        if body != payload:
            _fail(f"read mismatch: got {body!r}, expected {payload!r}")
            return False
        _ok("read: payload matches")
    except (BotoCoreError, ClientError, FileNotFoundError, OSError) as e:
        _fail(f"get_object failed: {e}")
        return False

    try:
        client.delete_object(Bucket=bucket, Key=test_key)
        _ok(f"delete: removed {test_key}")
    except (BotoCoreError, ClientError, OSError) as e:
        _fail(f"delete_object failed: {e}")
        return False

    return True


def main() -> int:
    load_dotenv()

    _section("Environment")
    missing = check_env()
    if missing:
        for var in missing:
            _fail(f"missing: {var}")
        print("\nFill these in your .env file, then re-run.")
        return 1
    _ok("all required vars present")

    _section("Postgres (Neon)")
    pg_ok = check_postgres()

    _section("Snapshot storage")
    storage_ok = check_storage()

    print()
    if pg_ok and storage_ok:
        print("\033[32mAll checks passed. Ready to write the extractor.\033[0m")
        return 0
    print("\033[31mOne or more checks failed. See above.\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
