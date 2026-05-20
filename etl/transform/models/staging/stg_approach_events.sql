{{ config(materialized='view') }}

-- Derived event stream emitted by etl.diff. Idempotent on dedup_key.
-- prev_value / new_value JSONB columns are preserved — they're the
-- audit trail for what changed between snapshots.

SELECT
    event_id,
    observed_at,
    spkid,
    designation,
    agency,
    approach_date,
    event_type,
    prev_value,
    new_value,
    diff_summary,
    dedup_key
FROM {{ source('raw', 'approach_events') }}
