{{ config(materialized='view') }}

-- Cross-agency impact-risk classifications. Designation has been
-- normalized at extract time so the same object's records from
-- NASA_SENTRY and ESA_NEOCC join cleanly on (designation).

SELECT
    agency,
    designation,
    assessment_date,
    spkid,
    risk_class,
    torino_scale,
    palermo_scale,
    palermo_scale_max,
    impact_probability,
    n_impacts,
    potential_impact_year_min,
    potential_impact_year_max,
    energy_mt,
    diameter_km,
    absolute_magnitude_h,
    v_inf_km_s,
    last_observed,
    source_url,
    source_retrieved_at,
    extraction_version
FROM {{ source('raw', 'risk_assessments') }}
