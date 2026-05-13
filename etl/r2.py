"""Cloudflare R2 (S3-compatible) helper, with a local-filesystem fallback.

Backend selection:
  - If STORAGE_BACKEND=local in the environment, use the local-filesystem
    backend.
  - If STORAGE_BACKEND=r2, require all R2_* env vars and use boto3.
  - If STORAGE_BACKEND is unset: auto-fallback to local when the four R2_*
    vars (ENDPOINT_URL, ACCESS_KEY_ID, SECRET_ACCESS_KEY, BUCKET_NAME) are
    missing or empty. Otherwise use boto3.

The local backend writes objects to LOCAL_R2_DIR (default
data/snapshots/local-r2). It mimics just enough of the boto3 S3 client
surface that etl.extract, etl.check_setup, and the test fakes don't need
to know which backend is in use.

This file exists because Cloudflare's current R2 token UI is a moving
target around when it surfaces S3-style Access Key + Secret. Running
without R2 is fine for local development; the R2 keys can be filled in
later when you have a working Access Key ID + Secret pair.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import boto3

DEFAULT_LOCAL_DIR = "data/snapshots/local-r2"
DEFAULT_BUCKET = "close-encounters-snapshots"

_R2_ENV_VARS = (
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def backend() -> str:
    """Return 'r2' or 'local'. Caller-overridable via STORAGE_BACKEND."""
    explicit = os.getenv("STORAGE_BACKEND", "").strip().lower()
    if explicit == "local":
        return "local"
    if explicit == "r2":
        return "r2"
    # Auto: pick local if any R2 var is missing.
    if all(os.getenv(v) for v in _R2_ENV_VARS):
        return "r2"
    return "local"


def get_bucket() -> str:
    return os.getenv("R2_BUCKET_NAME") or DEFAULT_BUCKET


def get_client():
    """Return a client object compatible with the boto3 S3 client interface
    for put_object / get_object / head_bucket / delete_object."""
    if backend() == "local":
        base = Path(os.getenv("LOCAL_R2_DIR") or DEFAULT_LOCAL_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return LocalR2Client(base)
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


# ---------------------------------------------------------------------------
# Public upload/download helpers — work against either backend
# ---------------------------------------------------------------------------


def upload_object(
    client: Any,
    key: str,
    body: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    client.put_object(Bucket=get_bucket(), Key=key, Body=body, ContentType=content_type)


def download_object(client: Any, key: str) -> bytes:
    resp = client.get_object(Bucket=get_bucket(), Key=key)
    return resp["Body"].read()


# ---------------------------------------------------------------------------
# Local-filesystem backend (S3 client lookalike)
# ---------------------------------------------------------------------------


class LocalR2Client:
    """File-system backed substitute for boto3's S3 client.

    Implements only the methods etl.r2 and etl.check_setup call:
    put_object, get_object, head_bucket, delete_object. Objects live at
    `<base_dir>/<bucket>/<key>` so multiple buckets can coexist.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def _path(self, bucket: str, key: str) -> Path:
        return self.base_dir / bucket / key

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        p = self._path(Bucket, Key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        p.write_bytes(Body)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:
        p = self._path(Bucket, Key)
        if not p.exists():
            raise FileNotFoundError(f"Key not found in local backend: {Bucket}/{Key}")
        return {"Body": io.BytesIO(p.read_bytes())}

    def head_bucket(self, *, Bucket: str, **_: Any) -> dict[str, Any]:
        (self.base_dir / Bucket).mkdir(parents=True, exist_ok=True)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def delete_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:
        p = self._path(Bucket, Key)
        if p.exists():
            p.unlink()
        return {"ResponseMetadata": {"HTTPStatusCode": 204}}


__all__ = [
    "DEFAULT_BUCKET",
    "DEFAULT_LOCAL_DIR",
    "LocalR2Client",
    "backend",
    "download_object",
    "get_bucket",
    "get_client",
    "upload_object",
]
