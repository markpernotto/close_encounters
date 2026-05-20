{{ config(materialized='table') }}

-- Orbit-revision dimension. Each row is one (spkid, solution_date)
-- combination — naturally immutable, since once JPL publishes an orbit
-- determination with a given solution_date it doesn't change. New
-- revisions arrive as new rows with later solution_dates.
--
-- This is the input to fact_close_approach's "what did JPL believe
-- about this object's orbit when they predicted the approach" question.

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
    source_retrieved_at,
    -- valid_from / valid_to flag the revision's authority window. valid_to
    -- of a revision is the next revision's solution_date (exclusive); the
    -- latest revision per spkid has valid_to = NULL meaning "still current."
    solution_date AS valid_from,
    LEAD(solution_date) OVER (
        PARTITION BY spkid ORDER BY solution_date
    ) AS valid_to,
    LEAD(solution_date) OVER (
        PARTITION BY spkid ORDER BY solution_date
    ) IS NULL AS is_current
FROM {{ ref('stg_orbit_elements') }}
