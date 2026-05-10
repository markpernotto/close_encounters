"""Tests for etl.alerts — pure-function tests over each rule.

These rules ship public alerts. The bar for coverage is high: every rule
gets fires/doesn't-fire/boundary cases, and the diameter-from-H derivation
is tested independently because it's used as a fallback by rule 1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from etl.alerts import (
    DEFAULT_ALBEDO,
    LATE_WARNING_WINDOW_DAYS,
    RULE_SHORT_ARC_LATE_WARNING,
    RULE_SIZE_AND_DISTANCE,
    RULE_VERY_CLOSE_ANY_SIZE,
    SHORT_ARC_DAYS,
    SIZE_RULE_DISTANCE_LD,
    SIZE_THRESHOLD_KM,
    VERY_CLOSE_DISTANCE_LD,
    best_diameter_km,
    derive_diameter_km,
    evaluate,
    rule_short_arc_late_warning,
    rule_size_and_distance,
    rule_very_close_any_size,
)
from etl.diff import EVENT_NEW_APPROACH, EVENT_NEW_OBJECT, EVENT_REVISED_APPROACH

OBSERVED_AT = datetime(2026, 5, 10, 6, 30, tzinfo=UTC)
APPROACH_DATE = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers — minimal context fixtures
# ---------------------------------------------------------------------------


def event(event_type: str = EVENT_NEW_APPROACH, *, spkid: str = "1") -> dict[str, Any]:
    return {
        "event_type": event_type,
        "spkid": spkid,
        "approach_date": APPROACH_DATE,
        "dedup_key": f"event-{event_type}-{spkid}",
    }


def obj(
    *,
    spkid: str = "1",
    diameter_km: float | None = None,
    diameter_estimate_km: float | None = None,
    h: float | None = None,
    albedo: float | None = None,
    arc_days: int | None = None,
) -> dict[str, Any]:
    return {
        "spkid": spkid,
        "designation": spkid,
        "diameter_km": diameter_km,
        "diameter_estimate_km": diameter_estimate_km,
        "absolute_magnitude_h": h,
        "albedo": albedo,
        "observation_arc_days": arc_days,
    }


def approach(
    *,
    spkid: str = "1",
    approach_date: datetime = APPROACH_DATE,
    distance_ld: float | None = 5.0,
) -> dict[str, Any]:
    return {
        "spkid": spkid,
        "approach_date": approach_date,
        "body": "Earth",
        "distance_ld": distance_ld,
        "distance_au": (distance_ld or 0.0) / 389.17,
    }


# ---------------------------------------------------------------------------
# Diameter derivation
# ---------------------------------------------------------------------------


def test_derive_diameter_returns_none_when_h_missing():
    assert derive_diameter_km(None) is None


def test_derive_diameter_uses_default_albedo_for_typical_neo():
    # H=22 with default albedo 0.14 → ~140 m
    d = derive_diameter_km(22.0)
    assert d is not None
    assert 0.130 < d < 0.155


def test_derive_diameter_at_size_boundary():
    # H=24 with default albedo 0.14 lands ~55 m — just above the 50 m gate
    d = derive_diameter_km(24.0)
    assert d is not None
    assert d >= SIZE_THRESHOLD_KM


def test_derive_diameter_falls_back_when_albedo_zero_or_negative():
    a = derive_diameter_km(22.0, albedo=0.0)
    b = derive_diameter_km(22.0, albedo=-0.1)
    c = derive_diameter_km(22.0, albedo=DEFAULT_ALBEDO)
    assert a == c
    assert b == c


def test_best_diameter_prefers_measured_over_estimate_over_h():
    measured = obj(diameter_km=0.3, diameter_estimate_km=0.2, h=22.0)
    estimate = obj(diameter_estimate_km=0.2, h=22.0)
    h_only = obj(h=22.0)
    nothing = obj()
    assert best_diameter_km(measured) == 0.3
    assert best_diameter_km(estimate) == 0.2
    assert best_diameter_km(h_only) == pytest.approx(derive_diameter_km(22.0))
    assert best_diameter_km(nothing) is None


# ---------------------------------------------------------------------------
# Rule 1 — size_and_distance
# ---------------------------------------------------------------------------


def test_rule_size_and_distance_fires_on_big_close_object():
    a = rule_size_and_distance(
        event(),
        obj(diameter_km=0.150),
        approach(distance_ld=0.8),
        OBSERVED_AT,
    )
    assert a is not None
    assert a["rule_id"] == RULE_SIZE_AND_DISTANCE
    assert "diameter" in a["rationale"]
    assert a["payload"]["diameter_km"] == 0.150


def test_rule_size_and_distance_does_not_fire_on_small_object():
    a = rule_size_and_distance(
        event(),
        obj(diameter_km=0.020),  # 20 m — below threshold
        approach(distance_ld=0.5),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_size_and_distance_does_not_fire_when_far():
    a = rule_size_and_distance(
        event(),
        obj(diameter_km=0.200),
        approach(distance_ld=5.0),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_size_and_distance_uses_h_fallback_when_diameter_missing():
    """H=22 with default albedo derives ~140 m → above the 50 m gate."""
    a = rule_size_and_distance(
        event(),
        obj(h=22.0),
        approach(distance_ld=0.9),
        OBSERVED_AT,
    )
    assert a is not None


def test_rule_size_and_distance_does_not_fire_when_no_size_known():
    a = rule_size_and_distance(
        event(),
        obj(),  # no diameter, no H
        approach(distance_ld=0.5),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_size_and_distance_at_exact_thresholds():
    """Boundary: diameter exactly 50 m, distance exactly 1 LD → fires (≤/≥)."""
    a = rule_size_and_distance(
        event(),
        obj(diameter_km=SIZE_THRESHOLD_KM),
        approach(distance_ld=SIZE_RULE_DISTANCE_LD),
        OBSERVED_AT,
    )
    assert a is not None


def test_rule_size_and_distance_skips_if_distance_missing():
    a = rule_size_and_distance(
        event(),
        obj(diameter_km=0.200),
        approach(distance_ld=None),
        OBSERVED_AT,
    )
    assert a is None


# ---------------------------------------------------------------------------
# Rule 2 — very_close_any_size
# ---------------------------------------------------------------------------


def test_rule_very_close_fires_inside_half_lunar():
    a = rule_very_close_any_size(
        event(),
        obj(),
        approach(distance_ld=0.4),
        OBSERVED_AT,
    )
    assert a is not None
    assert a["rule_id"] == RULE_VERY_CLOSE_ANY_SIZE


def test_rule_very_close_does_not_fire_outside_half_lunar():
    a = rule_very_close_any_size(
        event(),
        obj(),
        approach(distance_ld=0.6),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_very_close_at_exact_threshold_fires():
    """0.5 LD exactly → fires (≤)."""
    a = rule_very_close_any_size(
        event(),
        obj(),
        approach(distance_ld=VERY_CLOSE_DISTANCE_LD),
        OBSERVED_AT,
    )
    assert a is not None


def test_rule_very_close_ignores_size_entirely():
    """A pebble at 0.4 LD still fires; size is irrelevant for this rule."""
    a = rule_very_close_any_size(
        event(),
        obj(diameter_km=0.001),  # 1 m
        approach(distance_ld=0.4),
        OBSERVED_AT,
    )
    assert a is not None


# ---------------------------------------------------------------------------
# Rule 3 — short_arc_late_warning
# ---------------------------------------------------------------------------


def test_rule_short_arc_fires_for_new_object_with_imminent_approach():
    soon = OBSERVED_AT + timedelta(days=10)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=7),
        approach(approach_date=soon, distance_ld=3.0),
        OBSERVED_AT,
    )
    assert a is not None
    assert a["rule_id"] == RULE_SHORT_ARC_LATE_WARNING


def test_rule_short_arc_skips_well_tracked_object():
    soon = OBSERVED_AT + timedelta(days=10)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=SHORT_ARC_DAYS),  # not strictly less than threshold
        approach(approach_date=soon),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_short_arc_skips_far_future_approach():
    far = OBSERVED_AT + timedelta(days=LATE_WARNING_WINDOW_DAYS + 5)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=7),
        approach(approach_date=far),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_short_arc_skips_past_approach():
    past = OBSERVED_AT - timedelta(days=1)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=7),
        approach(approach_date=past),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_short_arc_only_fires_for_new_objects():
    """A NEW_APPROACH or REVISED_APPROACH never fires this rule, even if
    the object happens to be poorly-tracked and the approach is imminent."""
    soon = OBSERVED_AT + timedelta(days=10)
    for et in (EVENT_NEW_APPROACH, EVENT_REVISED_APPROACH):
        a = rule_short_arc_late_warning(
            event(et),
            obj(arc_days=7),
            approach(approach_date=soon),
            OBSERVED_AT,
        )
        assert a is None, f"{et} should not fire short_arc_late_warning"


def test_rule_short_arc_skips_when_arc_unknown():
    soon = OBSERVED_AT + timedelta(days=10)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=None),
        approach(approach_date=soon),
        OBSERVED_AT,
    )
    assert a is None


def test_rule_short_arc_at_exact_window_edge_fires():
    """Approach exactly at the 30-day horizon, arc exactly 13 days → fires."""
    edge = OBSERVED_AT + timedelta(days=LATE_WARNING_WINDOW_DAYS)
    a = rule_short_arc_late_warning(
        event(EVENT_NEW_OBJECT),
        obj(arc_days=SHORT_ARC_DAYS - 1),
        approach(approach_date=edge),
        OBSERVED_AT,
    )
    assert a is not None


# ---------------------------------------------------------------------------
# Evaluator — fan-out + dedup_key
# ---------------------------------------------------------------------------


def test_evaluate_can_fan_out_multiple_alerts_for_one_event():
    """A big object at 0.4 LD trips both rule 1 (size+distance) and rule 2
    (very close)."""
    alerts = evaluate(
        event(),
        obj(diameter_km=0.150),
        approach(distance_ld=0.4),
        OBSERVED_AT,
    )
    rule_ids = {a["rule_id"] for a in alerts}
    assert RULE_SIZE_AND_DISTANCE in rule_ids
    assert RULE_VERY_CLOSE_ANY_SIZE in rule_ids


def test_evaluate_emits_no_alerts_when_no_rules_match():
    alerts = evaluate(
        event(),
        obj(diameter_km=0.020),  # too small for rule 1
        approach(distance_ld=5.0),  # too far for rules 1 and 2
        OBSERVED_AT,
    )
    assert alerts == []


def test_evaluate_dedup_keys_are_deterministic_and_unique_per_rule():
    args = (event(), obj(diameter_km=0.150), approach(distance_ld=0.4), OBSERVED_AT)
    a1 = evaluate(*args)
    a2 = evaluate(*args)
    keys_1 = {a["dedup_key"] for a in a1}
    keys_2 = {a["dedup_key"] for a in a2}
    # Same inputs → same dedup_keys (idempotent at the load layer).
    assert keys_1 == keys_2
    # Different rules on the same event must have different dedup_keys.
    assert len({a["dedup_key"] for a in a1}) == len(a1)


def test_evaluate_dedup_key_changes_when_event_changes():
    common = (obj(diameter_km=0.150), approach(distance_ld=0.4), OBSERVED_AT)
    a1 = evaluate(event(spkid="1"), *common)
    a2 = evaluate(event(spkid="2"), *common)
    assert {a["dedup_key"] for a in a1}.isdisjoint({a["dedup_key"] for a in a2})
