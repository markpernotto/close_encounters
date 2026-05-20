{{ config(materialized='table') }}

-- Cross-agency reconciliation. One row per (designation, assessment_date)
-- with both NASA Sentry and ESA NEOCC scores pivoted side-by-side. The
-- coverage column makes the asymmetric-tracking story explicit:
--
--   'both'      → designation present in both agencies' risk lists
--   'NASA only' → tracked by Sentry but not by NEOCC
--   'ESA only'  → tracked by NEOCC but not by Sentry
--
-- delta_palermo is the (NASA - ESA) signed difference; the disagreement
-- structure across the catalog is the analytical payoff the plan called
-- out as "content, not a bug."

WITH unioned AS (
    SELECT
        designation,
        assessment_date,
        agency,
        torino_scale,
        palermo_scale,
        palermo_scale_max,
        impact_probability,
        n_impacts,
        potential_impact_year_min,
        potential_impact_year_max,
        diameter_km,
        v_inf_km_s
    FROM {{ ref('stg_risk_assessments') }}
),

pivoted AS (
    SELECT
        designation,
        assessment_date,
        MAX(CASE WHEN agency = 'NASA_SENTRY' THEN torino_scale END) AS nasa_torino_scale,
        MAX(CASE WHEN agency = 'NASA_SENTRY' THEN palermo_scale END) AS nasa_palermo_scale,
        MAX(CASE WHEN agency = 'NASA_SENTRY' THEN palermo_scale_max END) AS nasa_palermo_scale_max,
        MAX(CASE WHEN agency = 'NASA_SENTRY' THEN impact_probability END) AS nasa_impact_probability,
        MAX(CASE WHEN agency = 'NASA_SENTRY' THEN n_impacts END) AS nasa_n_impacts,
        MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN torino_scale END) AS esa_torino_scale,
        MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN palermo_scale END) AS esa_palermo_scale,
        MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN palermo_scale_max END) AS esa_palermo_scale_max,
        MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN impact_probability END) AS esa_impact_probability,
        -- Physical / kinematic from whichever agency reported it (NEOCC's
        -- diameter is often more authoritative for newly-discovered objects).
        COALESCE(
            MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN diameter_km END),
            MAX(CASE WHEN agency = 'NASA_SENTRY' THEN diameter_km END)
        ) AS diameter_km,
        COALESCE(
            MAX(CASE WHEN agency = 'NASA_SENTRY' THEN v_inf_km_s END),
            MAX(CASE WHEN agency = 'ESA_NEOCC'  THEN v_inf_km_s END)
        ) AS v_inf_km_s,
        MAX(potential_impact_year_min) AS potential_impact_year_min,
        MAX(potential_impact_year_max) AS potential_impact_year_max,
        BOOL_OR(agency = 'NASA_SENTRY') AS in_sentry,
        BOOL_OR(agency = 'ESA_NEOCC')   AS in_neocc
    FROM unioned
    GROUP BY designation, assessment_date
)

SELECT
    designation,
    assessment_date,
    -- Coverage classification: easiest filter for downstream questions
    CASE
        WHEN in_sentry AND in_neocc THEN 'both'
        WHEN in_sentry THEN 'NASA only'
        ELSE 'ESA only'
    END AS coverage,
    nasa_torino_scale,
    nasa_palermo_scale,
    nasa_palermo_scale_max,
    nasa_impact_probability,
    nasa_n_impacts,
    esa_torino_scale,
    esa_palermo_scale,
    esa_palermo_scale_max,
    esa_impact_probability,
    -- The disagreement, signed: positive = NASA scores HIGHER risk than ESA
    (nasa_palermo_scale - esa_palermo_scale) AS delta_palermo,
    ABS(nasa_palermo_scale - esa_palermo_scale) AS abs_delta_palermo,
    diameter_km,
    v_inf_km_s,
    potential_impact_year_min,
    potential_impact_year_max
FROM pivoted
