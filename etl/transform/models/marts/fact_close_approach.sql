{{ config(materialized='table') }}

-- Fact table: one row per (spkid, approach_date, body) at the LATEST
-- snapshot. Joined to dim_orbit_revision via "most-recent orbit
-- determination at or before the snapshot date" — answers "what did
-- JPL believe about this orbit when they made this prediction?"
--
-- apparent_mag_estimate is a simplified naked-eye-brightness proxy:
--   m ≈ H + 5 * log10(distance_au)
-- This assumes Sun-object distance ≈ 1 AU at Earth approach and ignores
-- phase-angle correction. Real apparent magnitude is typically 0.5-1
-- mag fainter due to phase. Good enough for "naked eye?" filtering
-- (m ≤ 6) and "small telescope?" (m ≤ 13) categorical buckets.

WITH latest_snapshot AS (
    SELECT MAX(snapshot_date) AS d FROM {{ ref('stg_close_approaches') }}
),

approaches AS (
    SELECT *
    FROM {{ ref('stg_close_approaches') }}
    WHERE snapshot_date = (SELECT d FROM latest_snapshot)
),

-- For each approach, find the orbit revision in effect at the snapshot
-- date. That's the orbit determination that JPL was using when they
-- computed this close approach prediction.
approach_with_orbit AS (
    SELECT
        a.snapshot_date,
        a.spkid,
        a.designation,
        a.approach_date,
        a.body,
        a.distance_au,
        a.distance_ld,
        a.distance_min_au,
        a.distance_max_au,
        a.v_rel_km_s,
        a.v_inf_km_s,
        a.orbit_id,
        a.source_retrieved_at,
        orb.solution_date AS orbit_solution_date,
        orb.epoch AS orbit_epoch,
        orb.e AS orbit_eccentricity,
        orb.a AS orbit_semi_major_au,
        orb.i AS orbit_inclination_deg,
        orb.sigma_a AS orbit_sigma_a,
        ROW_NUMBER() OVER (
            PARTITION BY a.spkid, a.approach_date, a.body
            ORDER BY orb.solution_date DESC NULLS LAST
        ) AS rn
    FROM approaches a
    LEFT JOIN {{ ref('dim_orbit_revision') }} orb
        ON orb.spkid = a.spkid
       AND orb.solution_date <= a.snapshot_date
)

SELECT
    awo.snapshot_date,
    awo.spkid,
    awo.designation,
    awo.approach_date,
    awo.body,
    awo.distance_au,
    awo.distance_ld,
    awo.distance_min_au,
    awo.distance_max_au,
    awo.v_rel_km_s,
    awo.v_inf_km_s,
    awo.orbit_id,
    -- Orbit revision context
    awo.orbit_solution_date,
    awo.orbit_epoch,
    awo.orbit_eccentricity,
    awo.orbit_semi_major_au,
    awo.orbit_inclination_deg,
    awo.orbit_sigma_a,
    -- Object physical params (current)
    obj.full_name,
    obj.orbit_class,
    obj.neo,
    obj.pha,
    obj.absolute_magnitude_h,
    obj.diameter_km,
    obj.diameter_estimate_km,
    -- Derived: simplified apparent magnitude estimate at approach
    CASE
        WHEN obj.absolute_magnitude_h IS NOT NULL AND awo.distance_au > 0
        THEN obj.absolute_magnitude_h + 5 * LOG(awo.distance_au)
        ELSE NULL
    END AS apparent_mag_estimate,
    awo.source_retrieved_at
FROM approach_with_orbit awo
LEFT JOIN {{ ref('mart_objects_current') }} obj
    ON obj.spkid = awo.spkid
WHERE awo.rn = 1
