-- AquaPulse as a "health station" for urban rivers: a river observation group, an eco
-- score next to the risk score, canal segments with their own passport, and alerts
-- that carry their evidence.

ALTER TABLE observations DROP CONSTRAINT observations_vector_group_check;
ALTER TABLE observations ADD CONSTRAINT observations_vector_group_check
    CHECK (vector_group IN ('aedes_breeding_risk', 'mosquito_activity', 'fly_cluster',
                            'water_quality_signal', 'culex_environmental_risk', 'rodent_sighting',
                            'dead_animal', 'aquatic_species', 'other_reference', 'river_health'));

-- Ecological condition from what people can see (life in the water, litter, colour, smell):
-- 1 = looks healthy. Kept apart from the risk score, as the brief asks.
ALTER TABLE observations ADD COLUMN eco_score real CHECK (eco_score BETWEEN 0 AND 1);
-- The goal the reporter chose: environment, child_health, flooding, biodiversity.
ALTER TABLE observations ADD COLUMN observation_goal text;

-- Canal and river segments. Geometry from OpenStreetMap, loaded from db/data at start-up.
CREATE TABLE waterway_segments (
    id          text PRIMARY KEY,
    waterway    text NOT NULL,
    name        text NOT NULL,
    seg_order   integer NOT NULL,
    from_m      integer NOT NULL,
    to_m        integer NOT NULL,
    geom        geography(LineString, 4326) NOT NULL
);
CREATE INDEX waterway_segments_geom_idx ON waterway_segments USING GIST (geom);

-- What an alert rests on (signals, reporters, confidence, who verifies, what to do), kept
-- with the alert so the message and the page show the same evidence.
ALTER TABLE alerts ADD COLUMN evidence jsonb;
