{{ config(materialized='table') }}

-- The denormalized "past 90 days" view, the symmetric companion to
-- mart_upcoming_approaches. /api/approaches/recent reads this directly.
-- 90 days is the window: long enough for "what happened recently" use
-- cases, short enough to keep the materialized table small. Callers
-- needing deeper history can query close_approaches_snapshots directly.

SELECT
    fca.spkid,
    fca.designation,
    fca.full_name,
    fca.approach_date,
    fca.body,
    fca.distance_au,
    fca.distance_ld,
    fca.distance_min_au,
    fca.distance_max_au,
    fca.v_rel_km_s,
    fca.v_inf_km_s,
    fca.orbit_id,
    fca.orbit_solution_date,
    fca.absolute_magnitude_h,
    fca.diameter_estimate_km,
    fca.diameter_km,
    fca.orbit_class,
    fca.neo,
    fca.pha,
    fca.apparent_mag_estimate,
    CASE
        WHEN fca.apparent_mag_estimate IS NULL THEN 'unknown'
        WHEN fca.apparent_mag_estimate <= 6  THEN 'naked_eye'
        WHEN fca.apparent_mag_estimate <= 10 THEN 'binoculars'
        WHEN fca.apparent_mag_estimate <= 13 THEN 'small_telescope'
        ELSE 'large_telescope'
    END AS visibility_bucket,
    fca.snapshot_date
FROM {{ ref('fact_close_approach') }} fca
WHERE fca.body = 'Earth'
  AND fca.approach_date < NOW()
  AND fca.approach_date >= NOW() - INTERVAL '90 days'
ORDER BY fca.approach_date DESC
