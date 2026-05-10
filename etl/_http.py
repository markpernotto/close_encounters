"""Shared httpx config for outbound source-API calls.

Constructs a User-Agent string from env vars (USER_AGENT_PROJECT,
USER_AGENT_EMAIL) so JPL/MPC/ADS request logs can identify us. Wraps GET
calls with tenacity retries (exponential backoff, jitter) for transient
network failures.
"""

from __future__ import annotations

import os

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter


def user_agent() -> str:
    project = os.getenv("USER_AGENT_PROJECT", "neo_citation/0.1")
    email = os.getenv("USER_AGENT_EMAIL")
    return f"{project} (mailto:{email})" if email else project


def default_headers() -> dict[str, str]:
    return {"User-Agent": user_agent(), "Accept": "application/json"}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1.0, max=10.0),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
)
def get_json(url: str, *, params: dict[str, str | int | float] | None = None, timeout: float = 30.0) -> dict:
    """GET a URL, raise on 4xx/5xx, return parsed JSON. Retries transient errors."""
    with httpx.Client(headers=default_headers(), timeout=timeout) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
