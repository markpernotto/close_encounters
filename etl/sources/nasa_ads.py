"""NASA Astrophysics Data System (ADS) API client.

Endpoint: https://api.adsabs.harvard.edu/v1
Docs:     https://ui.adsabs.harvard.edu/help/api/api-docs.html

ADS holds astronomy and physics bibliography. We use it to find journal
papers that mention a specific NEO designation — the science follow-up
side of the citation graph that complements the discovery side (MPECs).

Auth: ADS_API_TOKEN bearer. Rate limit: 5000 queries/day per token. We
cache aggressively and only resolve new discoveries, not the full catalog
on every run.

Each search result is a "doc" with fields like bibcode, title, author,
year, pub (journal), and doi. The bibcode is a 19-character stable
identifier used throughout the astronomy community — it's what we key
discovery_publications on for ADS-resolved rows.
"""

from __future__ import annotations

import os
from typing import Any

from etl._http import get_json

ADS_BASE_URL = "https://api.adsabs.harvard.edu/v1"
ADS_SEARCH_URL = f"{ADS_BASE_URL}/search/query"

DEFAULT_SEARCH_FIELDS = "bibcode,title,author,year,pub,doi,abstract"
DEFAULT_SEARCH_LIMIT = 10


class AdsAuthError(RuntimeError):
    """Raised when ADS_API_TOKEN isn't configured."""


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("ADS_API_TOKEN")
    if not token:
        raise AdsAuthError(
            "ADS_API_TOKEN not set; ADS resolution requires an API token "
            "from https://ui.adsabs.harvard.edu/user/settings/token"
        )
    return {"Authorization": f"Bearer {token}"}


def search_by_designation(
    designation: str,
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    fields: str = DEFAULT_SEARCH_FIELDS,
) -> list[dict[str, Any]]:
    """Search ADS for papers mentioning a given designation.

    Returns the `docs` array from the ADS response, or an empty list when
    nothing matched. The caller is responsible for filtering / scoring
    the results — we leave that judgment to normalize_ads_publication
    + the resolver's confidence-scoring.
    """
    # Quote-wrap to force exact-phrase match in ADS's search syntax.
    # Without quotes "2024 YR4" tokenizes into "2024" + "YR4" separately.
    payload = _search(
        q=f'full:"{designation}"',
        fl=fields,
        rows=limit,
    )
    return payload.get("response", {}).get("docs", [])


def fetch_bibcode(
    bibcode: str,
    *,
    fields: str = DEFAULT_SEARCH_FIELDS,
) -> dict[str, Any] | None:
    """Fetch a single bibcode's full record. Returns the doc dict or None
    when the bibcode doesn't resolve."""
    payload = _search(q=f"bibcode:{bibcode}", fl=fields, rows=1)
    docs = payload.get("response", {}).get("docs", [])
    return docs[0] if docs else None


def _search(*, q: str, fl: str, rows: int) -> dict[str, Any]:
    """Low-level search call. Returns the parsed JSON payload."""
    return get_json(
        ADS_SEARCH_URL,
        params={"q": q, "fl": fl, "rows": rows},
        headers=_auth_headers(),
    )
