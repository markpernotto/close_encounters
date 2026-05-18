"""Tests for etl.r2 — backend selection and the LocalR2Client fallback."""

from __future__ import annotations

import pytest

from etl.r2 import (
    DEFAULT_LOCAL_DIR,
    LocalR2Client,
    backend,
    download_object,
    get_bucket,
    get_client,
    upload_object,
)

_R2_ENV_VARS = (
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)


def _clear_r2_env(monkeypatch) -> None:
    for v in _R2_ENV_VARS + ("STORAGE_BACKEND", "LOCAL_R2_DIR"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_backend_explicit_local_wins(monkeypatch):
    _clear_r2_env(monkeypatch)
    for v in _R2_ENV_VARS:
        monkeypatch.setenv(v, "set")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    assert backend() == "local"


def test_backend_explicit_r2_wins(monkeypatch):
    _clear_r2_env(monkeypatch)
    monkeypatch.setenv("STORAGE_BACKEND", "r2")
    assert backend() == "r2"


def test_backend_auto_local_when_r2_vars_missing(monkeypatch):
    _clear_r2_env(monkeypatch)
    assert backend() == "local"


def test_backend_auto_r2_when_all_vars_present(monkeypatch):
    _clear_r2_env(monkeypatch)
    for v in _R2_ENV_VARS:
        monkeypatch.setenv(v, "non-empty")
    assert backend() == "r2"


def test_backend_auto_local_when_one_var_missing(monkeypatch):
    _clear_r2_env(monkeypatch)
    for v in _R2_ENV_VARS[:-1]:
        monkeypatch.setenv(v, "non-empty")
    # Final var is missing → should fall back to local
    assert backend() == "local"


# ---------------------------------------------------------------------------
# Bucket default
# ---------------------------------------------------------------------------


def test_get_bucket_uses_env_when_set(monkeypatch):
    monkeypatch.setenv("R2_BUCKET_NAME", "my-bucket")
    assert get_bucket() == "my-bucket"


def test_get_bucket_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("R2_BUCKET_NAME", raising=False)
    assert get_bucket() == "close-encounters-snapshots"


# ---------------------------------------------------------------------------
# get_client returns local client when backend is local
# ---------------------------------------------------------------------------


def test_get_client_returns_local_when_no_r2_env(monkeypatch, tmp_path):
    _clear_r2_env(monkeypatch)
    monkeypatch.setenv("LOCAL_R2_DIR", str(tmp_path / "local-r2"))
    client = get_client()
    assert isinstance(client, LocalR2Client)
    assert client.base_dir == tmp_path / "local-r2"


def test_get_client_creates_local_dir(monkeypatch, tmp_path):
    _clear_r2_env(monkeypatch)
    target = tmp_path / "fresh-local-r2"
    assert not target.exists()
    monkeypatch.setenv("LOCAL_R2_DIR", str(target))
    get_client()
    assert target.exists() and target.is_dir()


# ---------------------------------------------------------------------------
# LocalR2Client behavior
# ---------------------------------------------------------------------------


def test_local_put_and_get_round_trip(tmp_path):
    client = LocalR2Client(tmp_path)
    client.put_object(Bucket="b", Key="k.json", Body=b"hello", ContentType="application/json")
    resp = client.get_object(Bucket="b", Key="k.json")
    assert resp["Body"].read() == b"hello"


def test_local_put_creates_nested_directories(tmp_path):
    client = LocalR2Client(tmp_path)
    client.put_object(Bucket="b", Key="a/b/c/file.json", Body=b"x")
    assert (tmp_path / "b" / "a" / "b" / "c" / "file.json").read_bytes() == b"x"


def test_local_put_accepts_str_body(tmp_path):
    client = LocalR2Client(tmp_path)
    client.put_object(Bucket="b", Key="k", Body="hello")  # type: ignore[arg-type]
    assert (tmp_path / "b" / "k").read_bytes() == b"hello"


def test_local_get_raises_filenotfound_for_missing_key(tmp_path):
    client = LocalR2Client(tmp_path)
    with pytest.raises(FileNotFoundError):
        client.get_object(Bucket="b", Key="missing")


def test_local_head_bucket_creates_bucket_dir(tmp_path):
    client = LocalR2Client(tmp_path)
    client.head_bucket(Bucket="brand-new")
    assert (tmp_path / "brand-new").is_dir()


def test_local_delete_removes_object(tmp_path):
    client = LocalR2Client(tmp_path)
    client.put_object(Bucket="b", Key="goner", Body=b"x")
    assert (tmp_path / "b" / "goner").exists()
    client.delete_object(Bucket="b", Key="goner")
    assert not (tmp_path / "b" / "goner").exists()


def test_local_delete_missing_key_is_noop(tmp_path):
    client = LocalR2Client(tmp_path)
    # Should not raise
    client.delete_object(Bucket="b", Key="never-existed")


# ---------------------------------------------------------------------------
# upload_object / download_object end-to-end against LocalR2Client
# ---------------------------------------------------------------------------


def test_upload_download_round_trip_through_module_api(monkeypatch, tmp_path):
    _clear_r2_env(monkeypatch)
    monkeypatch.setenv("LOCAL_R2_DIR", str(tmp_path))
    monkeypatch.setenv("R2_BUCKET_NAME", "my-bucket")
    client = get_client()
    upload_object(client, "snapshots/2026-05-13/cneos.json", b'{"hello":"world"}')
    body = download_object(client, "snapshots/2026-05-13/cneos.json")
    assert body == b'{"hello":"world"}'
    # And the file is on disk at the expected location
    expected = tmp_path / "my-bucket" / "snapshots" / "2026-05-13" / "cneos.json"
    assert expected.exists()


# ---------------------------------------------------------------------------
# DEFAULT_LOCAL_DIR exists as a string and points to data/snapshots
# ---------------------------------------------------------------------------


def test_default_local_dir_is_under_data_snapshots():
    assert "data/snapshots" in DEFAULT_LOCAL_DIR
