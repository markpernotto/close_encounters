{% snapshot dim_object_snapshot %}
    {{
        config(
            target_schema='public',
            unique_key='spkid',
            strategy='check',
            check_cols=[
                'neo',
                'pha',
                'orbit_class',
                'absolute_magnitude_h',
                'diameter_km',
                'albedo',
                'rotation_period_h',
                'spec_class'
            ]
        )
    }}

-- Per-object current parameters, snapshotted with SCD-2 semantics. dbt
-- materializes this as a table and adds dbt_valid_from / dbt_valid_to /
-- dbt_updated_at / dbt_scd_id columns. When any of the check_cols above
-- change between runs, dbt closes the existing row (sets valid_to) and
-- inserts a new row with valid_from = run time.
--
-- Source: the latest snapshot per spkid from stg_objects. Sentry / NEOCC
-- attrs live in their own staging table — this dim is JPL-SBDB-only.

WITH latest AS (
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
        ROW_NUMBER() OVER (PARTITION BY spkid ORDER BY snapshot_date DESC) AS rn
    FROM {{ ref('stg_objects') }}
)

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
    n_observations
FROM latest
WHERE rn = 1

{% endsnapshot %}
