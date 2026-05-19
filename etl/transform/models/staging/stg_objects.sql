{{ config(materialized='view') }}

-- Staging view over objects_snapshots. Pass-through with column ordering
-- and explicit casts; raw_row JSONB is dropped (not needed analytically;
-- query the raw table directly if provenance debugging is needed).

SELECT
    snapshot_date,
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
    solution_date,
    source_url,
    source_retrieved_at,
    source_checksum,
    extraction_version
FROM {{ source('raw', 'objects_snapshots') }}
