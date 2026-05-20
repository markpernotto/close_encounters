"""Tests for etl.diff.compute_events — pure-function tests, no DB needed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from etl.diff import (
    EVENT_NEW_APPROACH,
    EVENT_NEW_OBJECT,
    EVENT_REVISED_APPROACH,
    EVENT_RISK_CLASS_CHANGE,
    compute_dedup_key,
    compute_events,
    compute_risk_events,
)

OBSERVED_AT = datetime(2026, 5, 8, 6, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------


def obj(spkid: str, designation: str = "") -> dict[str, Any]:
    return {"spkid": spkid, "designation": designation or spkid}


def approach(
    *,
    spkid: str,
    approach_date: datetime,
    distance_au: float = 0.04,
    v_rel: float = 10.0,
    orbit_id: str = "1",
    designation: str = "",
    body: str = "Earth",
) -> dict[str, Any]:
    return {
        "spkid": spkid,
        "designation": designation or spkid,
        "approach_date": approach_date,
        "body": body,
        "distance_au": distance_au,
        "v_rel_km_s": v_rel,
        "orbit_id": orbit_id,
    }


D1 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
D2 = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Empty / no-change cases
# ---------------------------------------------------------------------------


def test_no_changes_emits_no_events():
    same_obj = obj("1")
    same_app = approach(spkid="1", approach_date=D1)
    events = compute_events(
        prev_objects=[same_obj],
        curr_objects=[same_obj],
        prev_approaches=[same_app],
        curr_approaches=[same_app],
        observed_at=OBSERVED_AT,
    )
    assert events == []


def test_first_run_against_empty_prev_emits_only_new_object():
    """When prev is empty, every spkid in curr is a NEW_OBJECT.
    The corresponding approach should NOT also fire NEW_APPROACH; it's folded
    into the NEW_OBJECT event."""
    events = compute_events(
        prev_objects=[],
        curr_objects=[obj("1", "2024 YR4")],
        prev_approaches=[],
        curr_approaches=[approach(spkid="1", approach_date=D1)],
        observed_at=OBSERVED_AT,
    )
    types = [e["event_type"] for e in events]
    assert types == [EVENT_NEW_OBJECT]
    assert events[0]["approach_date"] == D1


# ---------------------------------------------------------------------------
# NEW_OBJECT
# ---------------------------------------------------------------------------


def test_new_object_uses_soonest_approach_as_anchor():
    events = compute_events(
        prev_objects=[obj("known")],
        curr_objects=[obj("known"), obj("brand_new")],
        prev_approaches=[approach(spkid="known", approach_date=D1)],
        curr_approaches=[
            approach(spkid="known", approach_date=D1),
            approach(spkid="brand_new", approach_date=D2),
            approach(spkid="brand_new", approach_date=D1),  # earlier — should win
        ],
        observed_at=OBSERVED_AT,
    )
    new_obj_events = [e for e in events if e["event_type"] == EVENT_NEW_OBJECT]
    assert len(new_obj_events) == 1
    assert new_obj_events[0]["spkid"] == "brand_new"
    assert new_obj_events[0]["approach_date"] == D1


def test_new_object_with_no_upcoming_approach_anchors_to_observed_at():
    events = compute_events(
        prev_objects=[],
        curr_objects=[obj("1")],
        prev_approaches=[],
        curr_approaches=[],  # no approach in window — orphan object
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    assert events[0]["event_type"] == EVENT_NEW_OBJECT
    assert events[0]["approach_date"] == OBSERVED_AT


# ---------------------------------------------------------------------------
# NEW_APPROACH
# ---------------------------------------------------------------------------


def test_new_approach_for_existing_object():
    known = obj("1")
    events = compute_events(
        prev_objects=[known],
        curr_objects=[known],
        prev_approaches=[approach(spkid="1", approach_date=D1)],
        curr_approaches=[
            approach(spkid="1", approach_date=D1),
            approach(spkid="1", approach_date=D2),  # newly forecast
        ],
        observed_at=OBSERVED_AT,
    )
    types = [e["event_type"] for e in events]
    assert types == [EVENT_NEW_APPROACH]
    assert events[0]["approach_date"] == D2


def test_new_approach_does_not_fire_when_object_is_also_new():
    """Avoid double-counting: a new object with an approach gets one
    NEW_OBJECT event, not NEW_OBJECT + NEW_APPROACH."""
    events = compute_events(
        prev_objects=[],
        curr_objects=[obj("1")],
        prev_approaches=[],
        curr_approaches=[approach(spkid="1", approach_date=D1)],
        observed_at=OBSERVED_AT,
    )
    types = [e["event_type"] for e in events]
    assert types.count(EVENT_NEW_APPROACH) == 0
    assert types.count(EVENT_NEW_OBJECT) == 1


# ---------------------------------------------------------------------------
# REVISED_APPROACH
# ---------------------------------------------------------------------------


def test_revised_approach_when_distance_changes():
    known = obj("1")
    prev_app = approach(spkid="1", approach_date=D1, distance_au=0.04)
    curr_app = approach(spkid="1", approach_date=D1, distance_au=0.035)  # got closer
    events = compute_events(
        prev_objects=[known],
        curr_objects=[known],
        prev_approaches=[prev_app],
        curr_approaches=[curr_app],
        observed_at=OBSERVED_AT,
    )
    revised = [e for e in events if e["event_type"] == EVENT_REVISED_APPROACH]
    assert len(revised) == 1
    assert revised[0]["prev_value"]["distance_au"] == 0.04
    assert revised[0]["new_value"]["distance_au"] == 0.035
    assert "distance_au" in revised[0]["diff_summary"]


def test_revised_approach_when_orbit_id_changes():
    known = obj("1")
    prev_app = approach(spkid="1", approach_date=D1, orbit_id="7")
    curr_app = approach(spkid="1", approach_date=D1, orbit_id="8")
    events = compute_events(
        prev_objects=[known],
        curr_objects=[known],
        prev_approaches=[prev_app],
        curr_approaches=[curr_app],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    assert events[0]["event_type"] == EVENT_REVISED_APPROACH
    assert "orbit_id" in events[0]["diff_summary"]


def test_no_revised_event_when_only_untracked_field_changes():
    """designation is not a revision-tracked field."""
    known = obj("1")
    prev_app = approach(spkid="1", approach_date=D1, designation="2024 YR4")
    curr_app = approach(spkid="1", approach_date=D1, designation="(99942) Apophis")
    events = compute_events(
        prev_objects=[known],
        curr_objects=[known],
        prev_approaches=[prev_app],
        curr_approaches=[curr_app],
        observed_at=OBSERVED_AT,
    )
    assert events == []


# ---------------------------------------------------------------------------
# Idempotency / dedup_key
# ---------------------------------------------------------------------------


def test_dedup_key_is_deterministic():
    args = {
        "event_type": EVENT_NEW_APPROACH,
        "spkid": "1",
        "approach_date": D1,
        "new_value": {"a": 1, "b": [2, 3]},
    }
    assert compute_dedup_key(**args) == compute_dedup_key(**args)


def test_dedup_key_differs_for_different_event_types():
    args = {"spkid": "1", "approach_date": D1, "new_value": {"x": 1}}
    k_new = compute_dedup_key(event_type=EVENT_NEW_APPROACH, **args)
    k_rev = compute_dedup_key(event_type=EVENT_REVISED_APPROACH, **args)
    assert k_new != k_rev


def test_dedup_key_stable_under_dict_key_order():
    """Canonical JSON sorts keys, so payload key order doesn't change the hash."""
    base = {"event_type": EVENT_NEW_APPROACH, "spkid": "1", "approach_date": D1}
    k1 = compute_dedup_key(**base, new_value={"a": 1, "b": 2})
    k2 = compute_dedup_key(**base, new_value={"b": 2, "a": 1})
    assert k1 == k2


def test_compute_events_is_idempotent_via_dedup_keys():
    """Same inputs → same dedup_keys; load layer can dedupe on this."""
    inputs = {
        "prev_objects": [obj("1")],
        "curr_objects": [obj("1"), obj("2")],
        "prev_approaches": [approach(spkid="1", approach_date=D1)],
        "curr_approaches": [
            approach(spkid="1", approach_date=D1, distance_au=0.03),  # revised
            approach(spkid="2", approach_date=D2),
        ],
        "observed_at": OBSERVED_AT,
    }
    events_1 = compute_events(**inputs)
    events_2 = compute_events(**inputs)
    keys_1 = sorted(e["dedup_key"] for e in events_1)
    keys_2 = sorted(e["dedup_key"] for e in events_2)
    assert keys_1 == keys_2
    assert len(set(keys_1)) == len(keys_1)  # all unique within a run


# ---------------------------------------------------------------------------
# Combined / multi-event scenarios
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# compute_risk_events — Phase 2 Commit 7
# ---------------------------------------------------------------------------


def risk(
    *,
    agency: str = "NASA_SENTRY",
    designation: str = "99942",
    spkid: str | None = None,
    torino_scale: int | None = 0,
    palermo_scale: float | None = -2.69,
    impact_probability: float | None = 8.5e-7,
    risk_class: str = "background",
) -> dict[str, Any]:
    return {
        "agency": agency,
        "designation": designation,
        "spkid": spkid,
        "torino_scale": torino_scale,
        "palermo_scale": palermo_scale,
        "impact_probability": impact_probability,
        "risk_class": risk_class,
    }


def test_risk_added_emits_event_with_no_prev_value():
    events = compute_risk_events(
        prev_risks=[],
        curr_risks=[risk(designation="2024 YR4")],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == EVENT_RISK_CLASS_CHANGE
    assert e["designation"] == "2024 YR4"
    assert e["agency"] == "NASA_SENTRY"
    assert e["prev_value"] is None
    assert e["new_value"]["palermo_scale"] == -2.69
    assert e["approach_date"] is None
    assert "added to NASA_SENTRY" in e["diff_summary"]


def test_risk_retracted_emits_event_with_no_new_value():
    events = compute_risk_events(
        prev_risks=[risk(designation="2024 YR4")],
        curr_risks=[],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == EVENT_RISK_CLASS_CHANGE
    assert e["new_value"] is None
    assert e["prev_value"] is not None
    assert "removed from NASA_SENTRY" in e["diff_summary"]


def test_risk_unchanged_emits_nothing():
    same = risk()
    events = compute_risk_events(
        prev_risks=[same],
        curr_risks=[same],
        observed_at=OBSERVED_AT,
    )
    assert events == []


def test_risk_palermo_change_emits_event():
    events = compute_risk_events(
        prev_risks=[risk(palermo_scale=-2.69)],
        curr_risks=[risk(palermo_scale=-2.55)],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    e = events[0]
    assert e["prev_value"]["palermo_scale"] == -2.69
    assert e["new_value"]["palermo_scale"] == -2.55
    assert "palermo_scale" in e["diff_summary"]


def test_risk_torino_escalation_emits_event():
    events = compute_risk_events(
        prev_risks=[risk(torino_scale=0)],
        curr_risks=[risk(torino_scale=2, risk_class="torino_2")],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    e = events[0]
    assert e["prev_value"]["torino_scale"] == 0
    assert e["new_value"]["torino_scale"] == 2


def test_risk_untracked_field_change_emits_nothing():
    """diameter changes don't trigger a risk event; only Torino, Palermo,
    impact probability, or risk_class do."""
    events = compute_risk_events(
        prev_risks=[{**risk(), "diameter_km": 0.34, "v_inf_km_s": 27.5}],
        curr_risks=[{**risk(), "diameter_km": 0.36, "v_inf_km_s": 27.5}],
        observed_at=OBSERVED_AT,
    )
    assert events == []


def test_risk_same_designation_different_agencies_emits_two_events():
    """NASA's record and ESA's record for the same body are independent
    streams. A change in one is a separate event from a change in the other."""
    events = compute_risk_events(
        prev_risks=[
            risk(agency="NASA_SENTRY", palermo_scale=-2.69),
            risk(agency="ESA_NEOCC", palermo_scale=-2.70),
        ],
        curr_risks=[
            risk(agency="NASA_SENTRY", palermo_scale=-2.55),  # NASA changed
            risk(agency="ESA_NEOCC", palermo_scale=-2.70),    # ESA didn't
        ],
        observed_at=OBSERVED_AT,
    )
    assert len(events) == 1
    assert events[0]["agency"] == "NASA_SENTRY"


def test_risk_carries_spkid_when_resolved():
    events = compute_risk_events(
        prev_risks=[],
        curr_risks=[risk(spkid="20099942")],
        observed_at=OBSERVED_AT,
    )
    assert events[0]["spkid"] == "20099942"


def test_risk_spkid_none_when_unresolved():
    events = compute_risk_events(
        prev_risks=[],
        curr_risks=[risk(spkid=None)],
        observed_at=OBSERVED_AT,
    )
    assert events[0]["spkid"] is None


def test_risk_dedup_keys_distinguish_agencies():
    """Otherwise-identical risk events from NASA vs ESA must have different
    dedup_keys — they're separate facts about the same body."""
    events = compute_risk_events(
        prev_risks=[],
        curr_risks=[
            risk(agency="NASA_SENTRY"),
            risk(agency="ESA_NEOCC"),
        ],
        observed_at=OBSERVED_AT,
    )
    keys = {e["dedup_key"] for e in events}
    assert len(keys) == 2


def test_risk_events_are_idempotent():
    """Running the same diff twice produces the same dedup_keys."""
    inputs = dict(
        prev_risks=[risk(palermo_scale=-2.69)],
        curr_risks=[risk(palermo_scale=-2.55)],
        observed_at=OBSERVED_AT,
    )
    a = compute_risk_events(**inputs)
    b = compute_risk_events(**inputs)
    assert {e["dedup_key"] for e in a} == {e["dedup_key"] for e in b}


# ---------------------------------------------------------------------------
# dedup_key backwards compatibility — extension must not break existing keys
# ---------------------------------------------------------------------------


def test_dedup_key_unchanged_when_no_designation_or_agency_passed():
    """Approach events (which don't pass designation/agency) must produce
    the same dedup_key after the Commit 7 extension. Otherwise re-running
    diff.py after deployment would emit duplicates of every existing
    approach event."""
    args = {
        "event_type": EVENT_NEW_APPROACH,
        "spkid": "1",
        "approach_date": D1,
        "new_value": {"a": 1, "b": 2},
    }
    # Same hash as before the extension — computed manually by reproducing
    # the original payload format
    import hashlib as _h
    import json as _j
    expected_payload = _j.dumps({
        "event_type": EVENT_NEW_APPROACH,
        "spkid": "1",
        "approach_date": D1.isoformat(),
        "new_value": {"a": 1, "b": 2},
    }, sort_keys=True, default=str)
    expected = _h.sha256(expected_payload.encode("utf-8")).hexdigest()
    assert compute_dedup_key(**args) == expected


def test_full_diff_scenario_multiple_event_types():
    prev_objects = [obj("a"), obj("b")]
    curr_objects = [obj("a"), obj("b"), obj("c", "2024 YR4")]
    prev_approaches = [
        approach(spkid="a", approach_date=D1, distance_au=0.04, orbit_id="1"),
        approach(spkid="b", approach_date=D1),
    ]
    curr_approaches = [
        approach(spkid="a", approach_date=D1, distance_au=0.038, orbit_id="2"),  # revised
        approach(spkid="b", approach_date=D1),                                    # unchanged
        approach(spkid="b", approach_date=D2),                                    # new approach
        approach(spkid="c", approach_date=D2, designation="2024 YR4"),            # new object's approach
    ]
    events = compute_events(
        prev_objects=prev_objects,
        curr_objects=curr_objects,
        prev_approaches=prev_approaches,
        curr_approaches=curr_approaches,
        observed_at=OBSERVED_AT,
    )
    by_type: dict[str, list] = {}
    for e in events:
        by_type.setdefault(e["event_type"], []).append(e)
    assert sorted(by_type) == [EVENT_NEW_APPROACH, EVENT_NEW_OBJECT, EVENT_REVISED_APPROACH]
    assert len(by_type[EVENT_NEW_OBJECT]) == 1
    assert by_type[EVENT_NEW_OBJECT][0]["spkid"] == "c"
    assert len(by_type[EVENT_NEW_APPROACH]) == 1
    assert by_type[EVENT_NEW_APPROACH][0]["spkid"] == "b"
    assert len(by_type[EVENT_REVISED_APPROACH]) == 1
    assert by_type[EVENT_REVISED_APPROACH][0]["spkid"] == "a"
