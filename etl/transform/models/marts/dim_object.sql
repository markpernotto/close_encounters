{{ config(materialized='view') }}

-- Object dimension with full SCD-2 history. Every time a tracked
-- attribute (orbit_class, neo, pha, H, diameter, albedo, rotation
-- period, spectral class) changes, a new row appears with the prior
-- row's dbt_valid_to closed off. Consumers that only need current
-- state should use mart_objects_current instead.
--
-- valid_to IS NULL marks the row as currently active.

SELECT
    spkid,
    designation,
    full_name,
    neo,
    pha,
    orbit_class,
    absolute_magnitude_h,
    diameter_km,
    diameter_estimate_km,
    albedo,
    rotation_period_h,
    spec_class,
    first_observed,
    last_observed,
    observation_arc_days,
    n_observations,
    dbt_valid_from AS valid_from,
    dbt_valid_to AS valid_to,
    (dbt_valid_to IS NULL) AS is_current,
    dbt_scd_id
FROM {{ ref('dim_object_snapshot') }}
