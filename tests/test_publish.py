"""Tests for etl.publish renderers — pure functions, no DB."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

from etl.publish import (
    UPCOMING_WINDOW_DAYS,
    render_health_json,
    render_noteworthy_json,
    render_noteworthy_rss,
    render_upcoming_json,
    render_upcoming_rss,
)

GENERATED_AT = datetime(2026, 5, 10, 6, 30, tzinfo=UTC)
APPROACH = datetime(2026, 6, 1, 12, 27, tzinfo=UTC)
FIRED_AT = datetime(2026, 5, 10, 6, 31, tzinfo=UTC)


def upcoming_row(**overrides):
    base = {
        "designation": "2024 YR4",
        "spkid": "20099942",
        "full_name": "99942 Apophis (2004 MN4)",
        "approach_date": APPROACH,
        "body": "Earth",
        "distance_au": 0.045,
        "distance_ld": 17.5,
        "v_rel_km_s": 10.7,
        "v_inf_km_s": 10.7,
        "diameter_estimate_km": 0.340,
        "absolute_magnitude_h": 19.7,
        "orbit_class": "ATE",
    }
    base.update(overrides)
    return base


def alert_row(**overrides):
    base = {
        "alert_id": 42,
        "fired_at": FIRED_AT,
        "rule_id": "size_and_distance",
        "spkid": "20099942",
        "approach_date": APPROACH,
        "designation": "(99942) Apophis",
        "rationale": "diameter ~340m, distance 0.80 LD on 2026-06-01",
        "payload": {"diameter_km": 0.340, "distance_ld": 0.80},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# JSON renderers
# ---------------------------------------------------------------------------


def test_upcoming_json_envelope_and_count():
    rows = [upcoming_row(), upcoming_row(designation="2026 HD2", spkid="X")]
    out = render_upcoming_json(rows, generated_at=GENERATED_AT)
    payload = json.loads(out)
    assert payload["count"] == 2
    assert payload["window_days"] == UPCOMING_WINDOW_DAYS
    assert payload["generated_at"] == GENERATED_AT.isoformat()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["designation"] == "2024 YR4"


def test_upcoming_json_handles_empty_rows():
    payload = json.loads(render_upcoming_json([], generated_at=GENERATED_AT))
    assert payload["count"] == 0
    assert payload["items"] == []


def test_upcoming_json_serializes_datetimes_as_iso():
    out = render_upcoming_json([upcoming_row()], generated_at=GENERATED_AT)
    payload = json.loads(out)
    assert payload["items"][0]["approach_date"] == APPROACH.isoformat()


def test_upcoming_json_is_byte_stable_for_same_input():
    rows = [upcoming_row()]
    a = render_upcoming_json(rows, generated_at=GENERATED_AT)
    b = render_upcoming_json(rows, generated_at=GENERATED_AT)
    assert a == b


def test_noteworthy_json_envelope_and_count():
    out = render_noteworthy_json([alert_row()], generated_at=GENERATED_AT)
    payload = json.loads(out)
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["rule_id"] == "size_and_distance"
    assert item["designation"] == "(99942) Apophis"
    assert item["fired_at"] == FIRED_AT.isoformat()


def test_health_json_shape():
    out = render_health_json(
        generated_at=GENERATED_AT,
        upcoming_count=25,
        noteworthy_count=3,
        latest_snapshot_date=date(2026, 5, 10),
    )
    payload = json.loads(out)
    assert payload == {
        "status": "ok",
        "generated_at": GENERATED_AT.isoformat(),
        "latest_snapshot_date": "2026-05-10",
        "upcoming_count": 25,
        "noteworthy_count": 3,
    }


def test_health_json_handles_no_snapshot():
    out = render_health_json(
        generated_at=GENERATED_AT,
        upcoming_count=0,
        noteworthy_count=0,
        latest_snapshot_date=None,
    )
    assert json.loads(out)["latest_snapshot_date"] is None


# ---------------------------------------------------------------------------
# RSS renderers — parse the output to verify it's valid XML
# ---------------------------------------------------------------------------


def test_upcoming_rss_is_well_formed_xml():
    xml = render_upcoming_rss([upcoming_row()], generated_at=GENERATED_AT)
    # ET.fromstring will raise if the XML is malformed
    root = ET.fromstring(xml)
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "close encounters — upcoming approaches"
    items = channel.findall("item")
    assert len(items) == 1
    title = items[0].find("title").text
    assert "2024 YR4" in title
    assert "2026-06-01" in title
    assert "17.50 LD" in title


def test_upcoming_rss_with_no_items_still_valid():
    xml = render_upcoming_rss([], generated_at=GENERATED_AT)
    root = ET.fromstring(xml)
    channel = root.find("channel")
    assert channel.findall("item") == []


def test_upcoming_rss_escapes_xml_special_characters():
    """A designation with an ampersand must not break the XML."""
    rows = [upcoming_row(designation="A & B", full_name="Asteroid <test>")]
    xml = render_upcoming_rss(rows, generated_at=GENERATED_AT)
    # Round-trip through the parser; failure raises ParseError
    root = ET.fromstring(xml)
    title = root.find("./channel/item/title").text
    assert "A & B" in title  # ET decodes &amp; back to &
    assert "<test>" not in xml.replace("&lt;test&gt;", "")  # raw < absent


def test_upcoming_rss_item_has_pubdate_and_guid():
    xml = render_upcoming_rss([upcoming_row()], generated_at=GENERATED_AT)
    root = ET.fromstring(xml)
    item = root.find("./channel/item")
    pubdate = item.find("pubDate").text
    assert pubdate.startswith("Mon, 01 Jun 2026") or pubdate.startswith("Mon, 1 Jun 2026")
    guid = item.find("guid")
    assert guid.attrib.get("isPermaLink") == "false"
    assert "20099942" in guid.text
    assert APPROACH.isoformat() in guid.text


def test_noteworthy_rss_is_well_formed():
    xml = render_noteworthy_rss([alert_row()], generated_at=GENERATED_AT)
    root = ET.fromstring(xml)
    item = root.find("./channel/item")
    title = item.find("title").text
    assert "size_and_distance" in title
    assert "(99942) Apophis" in title
    category = item.find("category").text
    assert category == "size_and_distance"
    description = item.find("description").text
    assert "diameter ~340m" in description


def test_rss_lastbuilddate_uses_generated_at():
    xml = render_upcoming_rss([], generated_at=GENERATED_AT)
    root = ET.fromstring(xml)
    last_build = root.find("./channel/lastBuildDate").text
    # RFC 2822: "Sun, 10 May 2026 06:30:00 +0000" or with leading-zero day
    assert "10 May 2026" in last_build
    assert "06:30:00" in last_build


def test_rss_handles_missing_optional_fields():
    """A row missing distance_ld and v_rel_km_s should still render cleanly."""
    rows = [
        upcoming_row(
            distance_ld=None,
            v_rel_km_s=None,
            diameter_estimate_km=None,
            orbit_class=None,
        )
    ]
    xml = render_upcoming_rss(rows, generated_at=GENERATED_AT)
    root = ET.fromstring(xml)
    title = root.find("./channel/item/title").text
    assert "unknown distance" in title


def test_rss_is_byte_stable_for_same_input():
    rows = [upcoming_row()]
    a = render_upcoming_rss(rows, generated_at=GENERATED_AT)
    b = render_upcoming_rss(rows, generated_at=GENERATED_AT)
    assert a == b
