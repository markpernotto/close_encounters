"""Thin Cloudflare R2 helper. Wraps boto3 with env-based config."""

from __future__ import annotations

import os

import boto3


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def get_bucket() -> str:
    return os.environ["R2_BUCKET_NAME"]


def upload_object(client, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    client.put_object(Bucket=get_bucket(), Key=key, Body=body, ContentType=content_type)


def download_object(client, key: str) -> bytes:
    resp = client.get_object(Bucket=get_bucket(), Key=key)
    return resp["Body"].read()
