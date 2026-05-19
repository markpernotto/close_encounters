{{ config(materialized='view') }}

-- Orbital elements + sigmas per orbit-determination revision. The
-- (spkid, solution_date) grain is the input to dim_orbit_revision SCD-2.

SELECT
    spkid,
    solution_date,
    epoch,
    e,
    a,
    i,
    om,
    w,
    ma,
    sigma_e,
    sigma_a,
    sigma_i,
    source_retrieved_at
FROM {{ source('raw', 'orbit_elements_snapshots') }}
