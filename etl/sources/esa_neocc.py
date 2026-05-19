"""ESA NEOCC Risk List client.

Endpoint: https://neo.ssa.esa.int/PSDB-portlet/download?file=esa_risk_list
Docs:     https://neo.ssa.esa.int/computer-access

Public, no auth. The response is **pipe-delimited plain text**, not JSON:

    Last Update: 2026-05-19 14:54 UTC
    <column-header row 1>
    <column-header row 2>
    <format-spec placeholder row>
    <designation>      | <diam_m> | <*=Y> | <VI Max date> | <IP max> | <PS max> | <TS> | <vel> | <years> | <IP cum> | <PS cum> |
    ...

The first four lines are headers/placeholder; data rows follow. Each row
is a single virtual-impactor summary per object, similar in spirit to
NASA Sentry but with European observation arcs and different solution
parameters — that disagreement is itself the cross-agency reconciliation
story Phase 2 surfaces.
"""

from __future__ import annotations

import re
from typing import Any

from etl._http import get_text

NEOCC_RISK_LIST_URL = (
    "https://neo.ssa.esa.int/PSDB-portlet/download?file=esa_risk_list"
)

# Header / placeholder lines we skip. The first line is "Last Update: ..."
# followed by two human-readable header rows and one "AAAA NNNN ..." format
# placeholder. After that every line is a data row.
_HEADER_LINES = 4


def fetch_risk_list_raw() -> str:
    """Fetch the full text body of the ESA NEOCC risk list."""
    return get_text(NEOCC_RISK_LIST_URL)


def fetch_risk_list() -> list[dict[str, Any]]:
    """Fetch and parse the risk list into row dicts."""
    return parse_risk_list_text(fetch_risk_list_raw())


def parse_risk_list_text(text: str) -> list[dict[str, Any]]:
    """Parse the NEOCC pipe-delimited risk list. Returns one dict per row.

    Each dict has keys: designation, name, diameter_m, sig, vi_max_date,
    ip_max, ps_max, ts, v_inf, years, ip_cum, ps_cum. All values are
    stripped strings; numeric coercion is the caller's responsibility
    (lives in etl.transform).
    """
    lines = text.splitlines()
    rows: list[dict[str, Any]] = []
    for raw in lines[_HEADER_LINES:]:
        cells = [c.strip() for c in raw.split("|")]
        # Trailing pipe produces an empty cell — drop it
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < 11:
            continue  # skip malformed / blank lines
        designation_cell, *rest = cells
        designation, name = _split_designation_and_name(designation_cell)
        diameter_m, sig, vi_max_date, ip_max, ps_max, ts, v_inf, years, ip_cum, ps_cum = rest[:10]
        rows.append(
            {
                "designation": designation,
                "name": name,
                "diameter_m": diameter_m,
                "sig": sig,
                "vi_max_date": vi_max_date,
                "ip_max": ip_max,
                "ps_max": ps_max,
                "ts": ts,
                "v_inf": v_inf,
                "years": years,
                "ip_cum": ip_cum,
                "ps_cum": ps_cum,
            }
        )
    return rows


# A provisional designation is a 4-digit year followed by 2 capital letters
# and optional digits, with no internal space (e.g. "2023VD3", "1979XB").
# Canonical IAU form has a space: "2023 VD3", "1979 XB". We normalize so
# the same designation matches across CNEOS / SBDB / Sentry / NEOCC.
_PROVISIONAL = re.compile(r"^(\d{4})([A-Z]{2}\d*)$")


def _split_designation_and_name(cell: str) -> tuple[str, str]:
    """The combined "Num/des. Name" field is a fixed-width string. The
    designation appears at the start; if the object has a permanent name
    it follows after whitespace.

    Examples we have to handle:
      "2023VD3"                       → ("2023 VD3", "")
      "1979XB"                        → ("1979 XB", "")
      "99942              Apophis"    → ("99942", "Apophis")
      "(99942) Apophis"               → ("99942", "Apophis")
    """
    parts = cell.split()
    if not parts:
        return "", ""
    head = parts[0]
    name = " ".join(parts[1:]) if len(parts) > 1 else ""
    # Strip enclosing parens around numbered asteroid: "(99942)" → "99942"
    if head.startswith("(") and head.endswith(")"):
        head = head[1:-1]
    return _normalize_designation(head), name


def _normalize_designation(des: str) -> str:
    """Insert a space inside provisional designations so 2023VD3 → 2023 VD3."""
    m = _PROVISIONAL.match(des)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return des
