"""IAU Minor Planet Center MPEC archive client.

MPECs (Minor Planet Electronic Circulars) are the canonical "this is a
new object" notice for asteroids and comets. Each MPEC has a stable
human-readable ID like 'MPEC 2024-Y17' and lives at a predictable URL
under https://www.minorplanetcenter.net/mpec/<half-month>/<packed>.html.

We use them as the discovery side of the citation graph: for a given
designation, the MPEC that announced it is the primary "publication"
the object can be linked to.

This module fetches MPEC HTML and parses just enough structure to
populate discovery_publications: mpec_id, issued timestamp, prose title,
and the set of designations the MPEC mentions. Heavier parsing (full
observation tables, orbit elements) is out of scope — we already have
that data from SBDB.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from etl._http import get_text

MPC_BASE_URL = "https://www.minorplanetcenter.net"


# An MPEC ID looks like 'MPEC 2024-Y17'. The half-month letter (Y here)
# combined with the year and sequence number forms a stable identifier.
_MPEC_ID_RE = re.compile(r"MPEC\s+(\d{4})-([A-Z])(\d{1,3})", re.IGNORECASE)

# MPEC URL path uses a packed form: K{YY}{half-month}{seq-packed}.html
# where {YY} is the last two digits of the year and the seq is encoded
# in the trailing digits/letters. For sequence numbers under 100 the
# packed form is just zero-padded; we cover that common case.
def mpec_url(mpec_id: str) -> str:
    """Build the canonical URL for an MPEC given its 'MPEC YYYY-XNN' id.

    Examples:
      'MPEC 2024-Y17' → https://.../mpec/K24/K24Y17.html
      'MPEC 2004-O02' → https://.../mpec/K04/K04O02.html

    Raises ValueError if the id can't be parsed.
    """
    m = _MPEC_ID_RE.search(mpec_id)
    if not m:
        raise ValueError(f"Unrecognized MPEC id: {mpec_id!r}")
    year, half_month, seq = m.groups()
    yy = year[2:]  # last two digits
    seq_padded = seq.zfill(2)
    return f"{MPC_BASE_URL}/mpec/K{yy}/K{yy}{half_month}{seq_padded}.html"


def fetch_mpec_raw(mpec_id: str) -> str:
    """Fetch an MPEC's HTML body. Caller handles parsing + storage."""
    return get_text(mpec_url(mpec_id))


def parse_mpec_html(html: str) -> dict[str, Any]:
    """Extract the structured bits we care about from MPEC HTML.

    Returns a dict with keys: mpec_id, title, issued_at, featured_
    designations, mentioned_designations. None values when a field
    can't be found — never raises on shape variation across MPECs.
    """
    title = _extract_title(html)
    pre = _extract_pre_block(html)

    mpec_id = _extract_mpec_id(pre or title or "")
    issued_at = _extract_issued_at(pre or "")
    featured = _extract_featured_designations(pre or "")
    mentioned = _extract_mentioned_designations(pre or "")

    return {
        "mpec_id": mpec_id,
        "title": title,
        "issued_at": issued_at,
        "featured_designations": featured,
        "mentioned_designations": mentioned,
    }


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"<title>\s*([^<]+?)\s*</title>", re.IGNORECASE | re.DOTALL)
_PRE_RE = re.compile(r"<pre>(.*?)</pre>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ISSUED_RE = re.compile(
    r"Issued\s+(\d{4})\s+([A-Za-z]+\.?)\s+(\d{1,2}),?\s+(\d{1,2}):(\d{2})\s*UT",
    re.IGNORECASE,
)
# Featured designations are bolded inline. Match <b>...</b> where contents
# look like a designation (provisional 'YYYY XX[N]' or numbered '(N)').
_FEATURED_RE = re.compile(
    r"<b>\s*([A-Za-z0-9 /()]+?)\s*</b>",
    re.IGNORECASE | re.DOTALL,
)
_PROVISIONAL_RE = re.compile(r"\b(\d{4}\s+[A-Z]{1,2}\d*)\b")
_NUMBERED_RE = re.compile(r"\((\d{1,7})\)")


def _extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).strip()
    # Strip the leading 'MPEC YYYY-XXX : ' prefix to keep just the descriptive
    # part, since the MPEC id is captured separately.
    if " : " in raw:
        return raw.split(" : ", 1)[1].strip()
    return raw


def _extract_pre_block(html: str) -> str | None:
    m = _PRE_RE.search(html)
    return m.group(1) if m else None


def _extract_mpec_id(text: str) -> str | None:
    # MPEC headers vary between 'M.P.E.C. 2024-Y17' (with periods) and
    # 'MPEC 2024-Y17'. Strip periods before matching.
    normalized = text.replace("M.P.E.C.", "MPEC")
    m = _MPEC_ID_RE.search(normalized)
    if not m:
        return None
    return f"MPEC {m.group(1)}-{m.group(2)}{m.group(3)}"


def _extract_issued_at(text: str) -> datetime | None:
    m = _ISSUED_RE.search(text)
    if not m:
        return None
    year, month_str, day, hour, minute = m.groups()
    month_str = month_str.rstrip(".")
    for fmt in ("%Y %B %d %H %M", "%Y %b %d %H %M"):
        try:
            return datetime.strptime(
                f"{year} {month_str} {day} {hour} {minute}", fmt
            ).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_featured_designations(pre_text: str) -> list[str]:
    """Designations that the MPEC explicitly bolds in the body. These are
    the 'this MPEC is announcing X' targets — high-confidence discovery
    relationships."""
    candidates: list[str] = []
    for m in _FEATURED_RE.finditer(pre_text):
        inner = _strip_tags(m.group(1)).strip()
        if not inner:
            continue
        # Filter to only things that look like designations
        prov = _PROVISIONAL_RE.search(inner)
        numb = _NUMBERED_RE.search(inner)
        if prov:
            candidates.append(prov.group(1))
        elif numb:
            candidates.append(numb.group(1))
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _extract_mentioned_designations(pre_text: str) -> list[str]:
    """All designations mentioned anywhere in the body, dedup'd. Used as
    lower-confidence 'follow_up' relationships — the MPEC discusses these
    objects but might not be announcing them."""
    text = _strip_tags(pre_text)
    desigs: list[str] = []
    seen: set[str] = set()
    for m in _PROVISIONAL_RE.finditer(text):
        d = m.group(1)
        if d not in seen:
            seen.add(d)
            desigs.append(d)
    for m in _NUMBERED_RE.finditer(text):
        d = m.group(1)
        if d not in seen:
            seen.add(d)
            desigs.append(d)
    return desigs


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)
