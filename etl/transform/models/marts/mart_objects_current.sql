{{ config(materialized='table') }}

-- Currently-known best parameters per object. The "latest" view that
-- both the API and the Phase 4 sky-view feature will read from. Joins
-- the SCD-2 dim's current row to the latest orbit revision (so callers
-- get one row per spkid with full physical + orbital state).

WITH current_obj AS (
    SELECT *
    FROM {{ ref('dim_object') }}
    WHERE is_current
),

latest_orbit AS (
    SELECT
        spkid,
        solution_date,
        e,
        a,
        i,
        om,
        w,
        ma,
        sigma_e,
        sigma_a,
        sigma_i,
        epoch,
        ROW_NUMBER() OVER (PARTITION BY spkid ORDER BY solution_date DESC) AS rn
    FROM {{ ref('dim_orbit_revision') }}
)

SELECT
    obj.spkid,
    obj.designation,
    obj.full_name,
    obj.neo,
    obj.pha,
    obj.orbit_class,
    obj.absolute_magnitude_h,
    obj.diameter_km,
    obj.diameter_estimate_km,
    obj.albedo,
    obj.rotation_period_h,
    obj.spec_class,
    obj.first_observed,
    obj.last_observed,
    obj.observation_arc_days,
    obj.n_observations,
    obj.valid_from AS object_valid_from,
    orb.solution_date AS latest_solution_date,
    orb.epoch AS latest_epoch_jd,
    orb.e AS eccentricity,
    orb.a AS semi_major_axis_au,
    orb.i AS inclination_deg,
    orb.om AS longitude_ascending_node_deg,
    orb.w AS argument_perihelion_deg,
    orb.ma AS mean_anomaly_deg,
    orb.sigma_e,
    orb.sigma_a,
    orb.sigma_i,
    -- Phase 3 discovery enrichment (LEFT JOIN — only ~10% of objects have
    -- this populated; rest are NULL)
    da.discoverer,
    da.discovery_facility,
    da.discovery_program,
    da.discovery_date,
    da.mpec_id AS discovery_mpec_id,
    da.site_code AS discovery_site_code,
    da.citation_text
FROM current_obj obj
LEFT JOIN latest_orbit orb
    ON orb.spkid = obj.spkid AND orb.rn = 1
LEFT JOIN {{ source('raw', 'discovery_attributions') }} da
    ON da.spkid = obj.spkid
