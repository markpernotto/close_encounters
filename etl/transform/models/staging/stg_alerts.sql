{{ config(materialized='view') }}

-- Threshold-rule matches against approach_events. Append-only by policy
-- (see docs/ALERT_RULES.md). The payload JSONB carries the numeric
-- evidence that fired the rule, useful for chart-style UIs downstream.

SELECT
    alert_id,
    fired_at,
    rule_id,
    spkid,
    approach_date,
    event_dedup_key,
    rationale,
    payload,
    dedup_key
FROM {{ source('raw', 'alerts') }}
