-- close_encounters / neo_citation — Phase 1 schema
--
-- Raw landing tables for the nightly snapshot/diff/publish pipeline.
-- Phase 2 will add risk_assessments + dbt mart layer.
-- Phase 3 will add discovery_publications + object_publications + discovery_attributions.

-- ---------------------------------------------------------------------------
-- objects_snapshots — one row per (snapshot_date, spkid)
-- The reference catalog of small-body physical and orbital metadata,
-- sourced from JPL SBDB. snapshot_date is the date we pulled this row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS objects_snapshots (
    snapshot_date          DATE NOT NULL,
    designation            TEXT NOT NULL,        -- e.g. "(99942) Apophis", "2024 YR4", "C/2023 A3"
    spkid                  TEXT NOT NULL,        -- JPL SPK-ID, more stable than designation
    full_name              TEXT,
    neo                    BOOLEAN,
    pha                    BOOLEAN,              -- potentially hazardous asteroid
    orbit_class            TEXT,                 -- AMO, APO, ATE, IEO, etc. (controlled vocab)
    absolute_magnitude_h   DOUBLE PRECISION,
    diameter_km            DOUBLE PRECISION,     -- if directly measured
    diameter_estimate_km   DOUBLE PRECISION,     -- derived from H + albedo
    albedo                 DOUBLE PRECISION,
    rotation_period_h      DOUBLE PRECISION,
    spec_class             TEXT,                 -- spectral classification when known
    first_observed         DATE,
    last_observed          DATE,
    observation_arc_days   INT,
    n_observations         INT,
    solution_date          DATE NOT NULL,        -- date of the orbit-determination solution
    raw_row                JSONB,
    source_url             TEXT NOT NULL,
    source_retrieved_at    TIMESTAMPTZ NOT NULL,
    source_checksum        TEXT NOT NULL,
    extraction_version     TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, spkid)
);
CREATE INDEX IF NOT EXISTS idx_objects_snapshots_spkid ON objects_snapshots (spkid);
CREATE INDEX IF NOT EXISTS idx_objects_snapshots_designation ON objects_snapshots (designation);

-- ---------------------------------------------------------------------------
-- orbit_elements_snapshots — one row per (spkid, solution_date)
-- Orbit elements are revised whenever new observations come in. We keep
-- every revision keyed by solution_date to drive Phase 2 SCD-2 modeling.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orbit_elements_snapshots (
    spkid                  TEXT NOT NULL,
    solution_date          DATE NOT NULL,
    epoch                  DOUBLE PRECISION,     -- Julian Date
    e                      DOUBLE PRECISION,     -- eccentricity
    a                      DOUBLE PRECISION,     -- semi-major axis (AU)
    i                      DOUBLE PRECISION,     -- inclination (deg)
    om                     DOUBLE PRECISION,     -- longitude of ascending node
    w                      DOUBLE PRECISION,     -- argument of perihelion
    ma                     DOUBLE PRECISION,     -- mean anomaly
    sigma_e                DOUBLE PRECISION,
    sigma_a                DOUBLE PRECISION,
    sigma_i                DOUBLE PRECISION,
    covariance             JSONB,                -- full covariance matrix when available
    raw_row                JSONB,
    source_retrieved_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (spkid, solution_date)
);

-- ---------------------------------------------------------------------------
-- close_approaches_snapshots — one row per (snapshot_date, spkid, approach_date, body)
-- The CNEOS close-approach feed, snapshotted nightly. Same approach event
-- can appear in many snapshots with revised distances as the orbit improves.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS close_approaches_snapshots (
    snapshot_date          DATE NOT NULL,
    spkid                  TEXT NOT NULL,
    designation            TEXT NOT NULL,
    approach_date          TIMESTAMPTZ NOT NULL,
    body                   TEXT NOT NULL,        -- usually "Earth"; CNEOS includes Moon, Mars, etc.
    distance_au            DOUBLE PRECISION NOT NULL,
    distance_ld            DOUBLE PRECISION,     -- lunar distances
    distance_min_au        DOUBLE PRECISION,     -- 1-sigma minimum
    distance_max_au        DOUBLE PRECISION,     -- 1-sigma maximum
    v_rel_km_s             DOUBLE PRECISION,     -- relative velocity at approach
    v_inf_km_s             DOUBLE PRECISION,     -- velocity at infinity
    solution_date          DATE NOT NULL,
    raw_row                JSONB,
    source_retrieved_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (snapshot_date, spkid, approach_date, body)
);
CREATE INDEX IF NOT EXISTS idx_close_approaches_approach_date ON close_approaches_snapshots (approach_date);
CREATE INDEX IF NOT EXISTS idx_close_approaches_spkid ON close_approaches_snapshots (spkid);

-- ---------------------------------------------------------------------------
-- approach_events — derived stream of changes between consecutive snapshots
-- Populated by etl.diff. Drives the alert pipeline and the public RSS feeds.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approach_events (
    event_id               BIGSERIAL PRIMARY KEY,
    observed_at            TIMESTAMPTZ NOT NULL,
    spkid                  TEXT NOT NULL,
    approach_date          TIMESTAMPTZ NOT NULL,
    event_type             TEXT NOT NULL,        -- NEW_APPROACH, REVISED_APPROACH, NEW_OBJECT, RISK_CLASS_CHANGE
    prev_value             JSONB,
    new_value              JSONB,
    diff_summary           TEXT
);
CREATE INDEX IF NOT EXISTS idx_approach_events_observed_at ON approach_events (observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_approach_events_spkid ON approach_events (spkid);
CREATE INDEX IF NOT EXISTS idx_approach_events_approach_date ON approach_events (approach_date);
