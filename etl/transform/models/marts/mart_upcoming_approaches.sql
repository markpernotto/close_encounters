{{ config(materialized='table') }}

-- The denormalized "next 60 days" view the public API and the RSS / JSON
-- feeds can read directly without further joins. Mirrors the columns
-- the Phase 1 FastAPI endpoints already return, plus apparent magnitude
-- estimate and orbit-revision context.
--
-- Filtered to Earth approaches in the LATEST snapshot. Sorted ascending
-- by approach_date so consumers can paginate forward in time.

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
    -- Categorical visibility bucket for UI filtering
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
  AND fca.approach_date >= NOW()
  AND fca.approach_date <= NOW() + INTERVAL '60 days'
ORDER BY fca.approach_date
