-- Observations: one citizen report, after the quality gate and the AI pipeline.
-- Section 5 of the plan, with the fixes found in review:
--   * TIMESTAMPTZ everywhere: a plain TIMESTAMP silently drops "+07:00".
--   * UUIDs default to gen_random_uuid().
--   * geom is generated from latitude/longitude, so it can never drift from them
--     (the plan's UPDATE without WHERE rewrote every row on each insert).
--   * A GIST index, or every ST_DWithin scans the whole table.
--   * CHECK constraints instead of free-text status and level columns.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE observations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id         text,
    latitude            double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude           double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    location_accuracy_m real CHECK (location_accuracy_m >= 0),
    -- geography, so ST_DWithin(a, b, 500) means 500 metres, not 500 degrees.
    geom                geography(Point, 4326) GENERATED ALWAYS AS (
                            ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                        ) STORED,
    observed_at         timestamptz NOT NULL,          -- when the photo was taken
    received_at         timestamptz NOT NULL DEFAULT now(),
    observation_types   text[] NOT NULL DEFAULT '{}',
    answers             jsonb NOT NULL DEFAULT '{}',
    image_path          text,
    image_sha256        text,
    image_phash         bit(64),                       -- near-duplicate photo detection
    duplicate_of        uuid REFERENCES observations(id) ON DELETE SET NULL,
    signals             text[] NOT NULL DEFAULT '{}',  -- signals the fusion step found present
    categories          text[] NOT NULL DEFAULT '{}',  -- 'vector', 'environment'
    risk                real NOT NULL CHECK (risk BETWEEN 0 AND 1),
    confidence          real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    level               text NOT NULL CHECK (level IN ('green', 'yellow', 'orange', 'red')),
    needs_verification  boolean NOT NULL,
    analysis            jsonb NOT NULL,                -- full pipeline output, for audit
    status              text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'needs_confirmation', 'needs_verification',
                                          'verified', 'dismissed')),
    is_demo             boolean NOT NULL DEFAULT false
);

CREATE INDEX observations_geom_idx ON observations USING GIST (geom);
CREATE INDEX observations_observed_at_idx ON observations (observed_at);
CREATE INDEX observations_categories_idx ON observations USING GIN (categories);
CREATE INDEX observations_status_idx ON observations (status);
