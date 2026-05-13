"""Tests for etl.extract.

Pure helpers tested directly. gather_snapshot tested with fake
cneos_fetch / sbdb_fetch / put_raw — no R2, no DB, no network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from etl.extract import (
    gather_snapshot,
    merge_manifest,
    r2_key_for_cneos,
    r2_key_for_sbdb,
    sha256_hex,
    unique_designations,
    write_manifest,
)

SNAPSHOT_DATE = date(2026, 5, 10)
RETRIEVED_AT = datetime(2026, 5, 10, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_unique_designations_dedupes_preserving_order():
    rows = [
        {"des": "2024 ABC"},
        {"des": "2025 XYZ"},
        {"des": "2024 ABC"},  # dup
        {"des": "1 Ceres"},
        {"des": "2025 XYZ"},  # dup
    ]
    assert unique_designations(rows) == ["2024 ABC", "2025 XYZ", "1 Ceres"]


def test_unique_designations_skips_missing_or_empty():
    rows = [{"des": "X"}, {}, {"des": ""}, {"des": None}, {"des": "Y"}]
    assert unique_designations(rows) == ["X", "Y"]


def test_r2_key_formats():
    assert r2_key_for_cneos(SNAPSHOT_DATE) == "snapshots/2026-05-10/cneos.json"
    assert r2_key_for_sbdb(SNAPSHOT_DATE, "20099942") == "snapshots/2026-05-10/sbdb/20099942.json"


def test_sha256_hex_is_deterministic_and_64_chars():
    h = sha256_hex(b"hello world")
    assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert len(h) == 64


def test_merge_manifest_appends_when_date_is_new():
    existing = [json.dumps({"snapshot_date": "2026-05-09", "x": 1})]
    new = {"snapshot_date": "2026-05-10", "x": 2}
    out = merge_manifest(existing, new)
    assert len(out) == 2
    assert json.loads(out[0])["snapshot_date"] == "2026-05-09"
    assert json.loads(out[1])["snapshot_date"] == "2026-05-10"


def test_merge_manifest_replaces_when_date_matches():
    existing = [
        json.dumps({"snapshot_date": "2026-05-09", "x": 1}),
        json.dumps({"snapshot_date": "2026-05-10", "x": 2}),
    ]
    new = {"snapshot_date": "2026-05-10", "x": 99}
    out = merge_manifest(existing, new)
    assert len(out) == 2
    assert json.loads(out[1])["x"] == 99


def test_merge_manifest_preserves_order_of_other_entries():
    existing = [
        json.dumps({"snapshot_date": "2026-05-08", "n": 1}),
        json.dumps({"snapshot_date": "2026-05-09", "n": 2}),
        json.dumps({"snapshot_date": "2026-05-10", "n": 3}),
    ]
    new = {"snapshot_date": "2026-05-09", "n": 99}
    out = merge_manifest(existing, new)
    dates = [json.loads(line)["snapshot_date"] for line in out]
    assert dates == ["2026-05-08", "2026-05-09", "2026-05-10"]
    assert json.loads(out[1])["n"] == 99


def test_merge_manifest_ignores_blank_and_unparseable_lines():
    existing = ["", "  ", "not-json", json.dumps({"snapshot_date": "2026-05-09"})]
    new = {"snapshot_date": "2026-05-10"}
    out = merge_manifest(existing, new)
    assert "not-json" in out
    assert any('"snapshot_date": "2026-05-10"' in line for line in out)


def test_write_manifest_round_trip(tmp_path: Path):
    path = tmp_path / "MANIFEST.jsonl"
    write_manifest(path, {"snapshot_date": "2026-05-09", "x": 1})
    write_manifest(path, {"snapshot_date": "2026-05-10", "x": 2})
    write_manifest(path, {"snapshot_date": "2026-05-10", "x": 99})  # replace
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["snapshot_date"] == "2026-05-09"
    assert parsed[1]["snapshot_date"] == "2026-05-10"
    assert parsed[1]["x"] == 99


# ---------------------------------------------------------------------------
# gather_snapshot with fakes
# ---------------------------------------------------------------------------


def fake_cneos_payload(designations: list[str]) -> dict[str, Any]:
    """Build a minimal CNEOS-shaped response with the given designations."""
    fields = [
        "des", "orbit_id", "jd", "cd", "dist", "dist_min", "dist_max",
        "v_rel", "v_inf", "t_sigma_f", "h",
    ]
    data = []
    for i, des in enumerate(designations):
        data.append(
            [
                des,
                str(i + 1),
                "2461100.0",
                f"2026-Jun-{15 + i:02d} 12:00",
                "0.04",
                "0.039",
                "0.041",
                "10.5",
                "10.4",
                "00:05",
                "23.0",
            ]
        )
    return {
        "signature": {"version": "1.5", "source": "fake-cneos"},
        "count": len(data),
        "fields": fields,
        "data": data,
    }


def fake_sbdb_payload(designation: str, spkid: str) -> dict[str, Any]:
    return {
        "object": {
            "spkid": spkid,
            "des": designation,
            "fullname": designation,
            "neo": True,
            "pha": False,
            "orbit_class": {"code": "APO", "name": "Apollo"},
        },
        "orbit": {
            "soln_date": "2024-06-25 10:48:08",
            "epoch": 2461000.5,
            "n_obs_used": 100,
            "data_arc": 365,
            "first_obs": "2024-01-01",
            "last_obs": "2024-12-31",
            "elements": [
                {"name": "e", "value": "0.5", "sigma": "1e-9"},
                {"name": "a", "value": "1.5", "sigma": "1e-9"},
                {"name": "i", "value": "10.0", "sigma": "1e-9"},
            ],
        },
        "phys_par": [{"name": "H", "value": "20.0"}],
        "discovery": {},
    }


def make_fakes(designations: list[str], *, sbdb_failures: set[str] | None = None):
    """Return (cneos_fetch, sbdb_fetch, uploads_list) wired for tests."""
    sbdb_failures = sbdb_failures or set()
    uploads: list[tuple[str, bytes]] = []

    def cneos_fetch(**_kw):
        return fake_cneos_payload(designations)

    def sbdb_fetch(designation: str):
        if designation in sbdb_failures:
            raise RuntimeError(f"simulated SBDB outage for {designation}")
        spkid = f"spkid-{designation.replace(' ', '_')}"
        return fake_sbdb_payload(designation, spkid)

    def put_raw(key: str, body: bytes) -> None:
        uploads.append((key, body))

    return cneos_fetch, sbdb_fetch, put_raw, uploads


def test_gather_uploads_one_cneos_plus_one_sbdb_per_unique_designation():
    cneos_fetch, sbdb_fetch, put_raw, uploads = make_fakes(["A", "B", "C", "B"])
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    keys = [k for k, _ in uploads]
    assert keys[0] == "snapshots/2026-05-10/cneos.json"
    # Three unique designations → three SBDB uploads
    sbdb_keys = [k for k in keys if "/sbdb/" in k]
    assert len(sbdb_keys) == 3
    assert all(k.startswith("snapshots/2026-05-10/sbdb/") for k in sbdb_keys)
    assert snap.sbdb_pulls == 3


def test_gather_records_sbdb_errors_without_aborting():
    cneos_fetch, sbdb_fetch, put_raw, uploads = make_fakes(
        ["A", "B", "C"], sbdb_failures={"B"}
    )
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    assert snap.sbdb_pulls == 2
    assert any("B" in e for e in snap.sbdb_errors)
    # Two SBDB uploads (A and C); B is skipped
    sbdb_keys = [k for k, _ in uploads if "/sbdb/" in k]
    assert len(sbdb_keys) == 2


def test_gather_produces_normalized_rows_for_all_three_tables():
    cneos_fetch, sbdb_fetch, put_raw, _ = make_fakes(["A", "B"])
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    assert len(snap.object_rows) == 2
    assert len(snap.orbit_rows) == 2
    assert len(snap.approach_rows) == 2
    # Approach rows should have spkids resolved in-process
    spkids = {r["spkid"] for r in snap.approach_rows}
    assert spkids == {"spkid-A", "spkid-B"}
    # Snapshot date threaded through
    assert all(r["snapshot_date"] == SNAPSHOT_DATE for r in snap.object_rows)
    assert all(r["snapshot_date"] == SNAPSHOT_DATE for r in snap.approach_rows)


def test_gather_approach_rows_carry_none_spkid_when_sbdb_failed():
    """If SBDB fails for a designation, the CNEOS row still flows through
    but with spkid=None. load.load_close_approaches will skip it then."""
    cneos_fetch, sbdb_fetch, put_raw, _ = make_fakes(
        ["A", "B"], sbdb_failures={"B"}
    )
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    by_des = {r["designation"]: r for r in snap.approach_rows}
    assert by_des["A"]["spkid"] == "spkid-A"
    assert by_des["B"]["spkid"] is None


def test_gather_manifest_entry_lists_every_source_with_provenance():
    cneos_fetch, sbdb_fetch, put_raw, _ = make_fakes(["A", "B"])
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    entry = snap.manifest_entry
    assert entry["snapshot_date"] == "2026-05-10"
    assert entry["retrieved_at"] == RETRIEVED_AT.isoformat()
    kinds = [s["kind"] for s in entry["sources"]]
    assert kinds == ["cneos", "sbdb", "sbdb"]
    for source in entry["sources"]:
        assert len(source["sha256"]) == 64
        assert source["bytes"] > 0
        assert source["r2_key"].startswith("snapshots/2026-05-10/")


def test_gather_handles_zero_cneos_rows():
    cneos_fetch, sbdb_fetch, put_raw, uploads = make_fakes([])
    snap = gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw,
        sbdb_delay_sec=0.0,
    )
    # We still uploaded the (empty) CNEOS envelope
    assert len(uploads) == 1
    assert uploads[0][0] == "snapshots/2026-05-10/cneos.json"
    assert snap.object_rows == []
    assert snap.approach_rows == []
    assert snap.sbdb_pulls == 0


def test_gather_is_byte_stable_for_same_input(monkeypatch):
    """Re-running with the same fakes should produce identical R2 payloads
    so the deterministic-key model holds: re-uploads overwrite to the same
    bytes."""
    cneos_fetch, sbdb_fetch, put_raw_1, uploads_1 = make_fakes(["A", "B"])
    _, _, put_raw_2, uploads_2 = make_fakes(["A", "B"])
    gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch,
        sbdb_fetch=sbdb_fetch,
        put_raw=put_raw_1,
        sbdb_delay_sec=0.0,
    )
    # Build fresh fakes so the second run is independent
    cneos_fetch_2, sbdb_fetch_2, _, _ = make_fakes(["A", "B"])
    gather_snapshot(
        snapshot_date=SNAPSHOT_DATE,
        retrieved_at=RETRIEVED_AT,
        cneos_fetch=cneos_fetch_2,
        sbdb_fetch=sbdb_fetch_2,
        put_raw=put_raw_2,
        sbdb_delay_sec=0.0,
    )
    keys_1 = sorted(k for k, _ in uploads_1)
    keys_2 = sorted(k for k, _ in uploads_2)
    bodies_1 = {k: b for k, b in uploads_1}
    bodies_2 = {k: b for k, b in uploads_2}
    assert keys_1 == keys_2
    for k in keys_1:
        assert bodies_1[k] == bodies_2[k]
