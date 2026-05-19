{{ config(materialized='view') }}

-- CNEOS close-approach predictions, snapshotted nightly. orbit_id changes
-- across snapshots signal a JPL orbit-determination revision; the
-- fact_close_approach mart joins this against dim_orbit_revision to
-- recover the orbit that produced each prediction.

SELECT
    snapshot_date,
    spkid,
    designation,
    approach_date,
    body,
    distance_au,
    distance_ld,
    distance_min_au,
    distance_max_au,
    v_rel_km_s,
    v_inf_km_s,
    orbit_id,
    solution_date,
    source_retrieved_at
FROM {{ source('raw', 'close_approaches_snapshots') }}
