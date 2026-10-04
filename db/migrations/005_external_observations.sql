-- Observations collected by other platforms (iNaturalist first). Kept apart from our own
-- reports: they are context on the map ("mosquitoes were seen here"), they do not enter
-- hotspots, alerts, trends or points, and their species names come from that platform's
-- community, not from AquaPulse.
CREATE TABLE external_observations (
    id              bigserial PRIMARY KEY,
    source          text NOT NULL,                 -- 'inaturalist'
    source_id       text NOT NULL,
    url             text NOT NULL,
    taxon_id        bigint,
    taxon_name      text NOT NULL,
    taxon_rank      text,
    common_name     text,
    quality_grade   text,                          -- iNaturalist: research | needs_id | casual
    observed_on     date NOT NULL,
    observed_at     timestamptz,
    latitude        double precision NOT NULL,
    longitude       double precision NOT NULL,
    geom            geography(Point, 4326) GENERATED ALWAYS AS (
                        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    accuracy_m      real,
    obscured        boolean NOT NULL DEFAULT false,
    license         text NOT NULL,                 -- licence of the observation record
    photo_url       text,                          -- only when the photo itself has an open licence
    photo_license   text,
    attribution     text,                          -- required by CC BY: shown next to the photo
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX external_observations_geom_idx ON external_observations USING GIST (geom);
CREATE INDEX external_observations_observed_idx ON external_observations (observed_on);

-- One row per sync run, so the page can say where the data came from and when.
CREATE TABLE external_syncs (
    id          bigserial PRIMARY KEY,
    source      text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    fetched     integer NOT NULL DEFAULT 0,
    kept        integer NOT NULL DEFAULT 0,
    removed     integer NOT NULL DEFAULT 0,
    error       text
);
