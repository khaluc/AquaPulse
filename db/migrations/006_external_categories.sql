-- Outside data for every Vector Watch group, not only mosquitoes: which group a sighting
-- belongs to (same ids as observations.vector_group) and which query brought it in.
ALTER TABLE external_observations
    ADD COLUMN category text NOT NULL DEFAULT 'mosquito_activity',
    ADD COLUMN query_key text NOT NULL DEFAULT 'mosquitoes';
ALTER TABLE external_observations ALTER COLUMN category DROP DEFAULT;
ALTER TABLE external_observations ALTER COLUMN query_key DROP DEFAULT;
CREATE INDEX external_observations_category_idx ON external_observations (category);
