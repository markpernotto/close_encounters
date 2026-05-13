# Alert Rules

The "noteworthy" RSS feed and the `/api/alerts` endpoint surface only
those approach events that match one of the rules documented here. Each
rule is a pure function in `etl/alerts.py`, exhaustively unit-tested in
`tests/test_alerts.py`. This doc explains in plain English what each rule
checks, why, and how to interpret the resulting alert.

## False-alarm policy

**Alerts are never retracted.** If new data invalidates a prior alert —
say, JPL refines an orbit and the predicted distance moves outside the
threshold — a *correcting* alert is appended; the prior alert stays. This
policy applies to every rule below, and is the reason the `alerts` table
is append-only with no `valid_to` column.

Rationale: an alert that disappears is harder to reason about than a
correcting alert that explains what changed. RSS readers in particular
have no way to "unsee" a feed item; an honest correction is the right
contract.

## Diameter handling for size-gated rules

Many newly-discovered NEOs have only an absolute magnitude `H`, not a
measured diameter. When the size-gated rule needs a diameter, it falls
back to deriving one from `H` using the standard formula:

> diameter (km) = (1329 / √albedo) × 10^(−H / 5)

With a default albedo of 0.14 (typical NEO), `H = 22` ≈ 140 m, `H = 24` ≈
55 m. If neither `H` nor `diameter` is known, the rule does not fire —
the system is conservative on missing data.

`etl.alerts.best_diameter_km` picks in this order:

1. measured `diameter_km` (highest authority)
2. pre-computed `diameter_estimate_km` from SBDB
3. derived from `H` with the formula above

If all three are absent, the size-gated rule is silent for that object.

---

## Rule 1 — Sizeable object inside the lunar distance

**Internal id:** `size_and_distance`

**Fires when:** estimated diameter ≥ 50 m **AND** distance ≤ 1 LD.

**Where the numbers come from:** the planetary-defense community treats
50 m as the rough threshold above which a strike causes regional damage
(the Tunguska 1908 event is the canonical reference). One lunar distance
(LD ≈ 384,400 km) is a conventional shorthand for "passing close to Earth
on a scale you can relate to."

**Boundaries:** both are inclusive. A 50 m object at exactly 1 LD fires
this rule.

**Doesn't fire when:**

- the diameter cannot be established at all (no `diameter_km`, no
  `diameter_estimate_km`, no `H`)
- the object is smaller than 50 m
- the approach is farther than 1 LD

**Sample alert payload:**

```json
{
  "rule_id": "size_and_distance",
  "rationale": "diameter ~340m, distance 0.80 LD on 2026-06-01",
  "payload": { "diameter_km": 0.340, "distance_ld": 0.80 }
}
```

---

## Rule 2 — Very-close approach regardless of size

**Internal id:** `very_close_any_size`

**Fires when:** distance ≤ 0.5 LD.

**Where the numbers come from:** anything passing inside half the
Earth–Moon distance is operationally interesting whatever its size; for
context, geostationary satellites orbit at ~0.1 LD, so 0.5 LD is roughly
five-times-geostationary altitude. Approaches inside that mark are rare
enough on a per-day basis that the firehose is comfortably narrow.

**Boundaries:** inclusive. A pebble at exactly 0.5 LD fires this rule;
the same pebble at 0.51 LD does not.

**Doesn't fire when:**

- distance is unknown
- distance exceeds 0.5 LD

This rule deliberately ignores size. The Chelyabinsk 2013 event was a
~20 m bolide that nobody saw coming; an analogue passing at 0.4 LD is
worth surfacing even if its estimated diameter is below the 50 m gate.

**Sample alert payload:**

```json
{
  "rule_id": "very_close_any_size",
  "rationale": "distance 0.42 LD on 2026-06-05 (below 0.5 LD threshold)",
  "payload": { "distance_ld": 0.42 }
}
```

---

## Rule 3 — Newly-discovered, short observation arc, near-term approach

**Internal id:** `short_arc_late_warning`

**Fires when** all three hold:

- the event is `NEW_OBJECT` (this rule does **not** fire on
  `NEW_APPROACH` or `REVISED_APPROACH`)
- observation arc < 14 days
- the first close approach is within the next 30 days (forward in time
  from the run's `observed_at`)

**Where the numbers come from:** observation arc length is the standard
proxy for orbit-determination confidence. An arc of 14 days is the rough
threshold below which a new object's orbit is considered preliminary —
JPL's own MPEC announcements emphasize objects with short arcs as
operationally interesting because their predicted positions still carry
substantial uncertainty. The 30-day forward window matches the typical
horizon at which planetary-defense surveys (Catalina, ATLAS, Pan-STARRS)
focus their follow-up observation requests.

**Boundaries:** strict on the arc (`< 14`, so an object with arc = 14 days
does not fire), inclusive on the 30-day horizon (an approach at exactly
30 days fires).

**Doesn't fire when:**

- the event is not `NEW_OBJECT`
- observation arc is unknown
- observation arc is 14 days or longer
- the first close approach is in the past
- the first close approach is beyond the 30-day horizon

**Sample alert payload:**

```json
{
  "rule_id": "short_arc_late_warning",
  "rationale": "new object with 7-day observation arc; first close approach in 10 days",
  "payload": { "observation_arc_days": 7, "days_until_approach": 10 }
}
```

---

## Rule 4 — Risk class change (Phase 2)

**Internal id:** `risk_class_change` (planned)

Phase 2 will add this rule once NASA Sentry and ESA NEOCC are ingested.
It fires when an object is added to or moves up on either risk list. It
does **not** fire on downward moves (movement off the Sentry list is
common as observation arcs extend, and is not by itself newsworthy).

This rule is excluded from Phase 1 because the underlying risk-list data
is not yet in the warehouse.

---

## How to read an alert

Every alert carries:

| Field | Meaning |
|---|---|
| `alert_id` | Surrogate primary key; stable forever |
| `fired_at` | UTC timestamp the rule was evaluated |
| `rule_id` | The internal id from this document |
| `spkid` | JPL SPK-ID of the object — stable across designations |
| `approach_date` | UTC timestamp of the close approach the alert is about |
| `event_dedup_key` | sha256 hash linking back to the `approach_events` row that triggered evaluation |
| `rationale` | A short human-readable string explaining why the rule matched |
| `payload` | The numeric values the rule looked at, for downstream display |
| `dedup_key` | sha256 of `(rule_id, event_dedup_key)`; uniquely identifies this alert |

The `rationale` is the user-facing summary. The `payload` is the structured
form for UIs that want to chart or compare alerts.

## How to add a rule

1. Define an id and add an entry to `vocabularies/alert_rule.yaml`.
2. Write the rule as a function in `etl/alerts.py` matching the signature
   `(event, object_row, approach_row, observed_at) -> dict | None`.
3. Append the new function to `ALL_RULES` in `etl/alerts.py`.
4. Add to this document with the same template as the rules above.
5. Add exhaustive tests in `tests/test_alerts.py`: fires-as-expected,
   doesn't-fire-when-shouldn't, exact-boundary, and graceful behavior
   on missing inputs.

Rules are evaluated independently; one event can fire multiple rules.
The `dedup_key` formula uses the rule id, so the same event firing two
rules produces two separate alerts — by design.
