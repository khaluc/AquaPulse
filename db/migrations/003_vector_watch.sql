-- Vector Watch module: the group of each report, its scores, and before/after photos.

ALTER TABLE observations
    ADD COLUMN risk_domain text
        CHECK (risk_domain IN ('vector', 'sanitation', 'water_quality', 'aquatic', 'reference')),
    ADD COLUMN vector_group text
        CHECK (vector_group IN ('aedes_breeding_risk', 'mosquito_activity', 'fly_cluster',
                                'water_quality_signal', 'culex_environmental_risk', 'rodent_sighting',
                                'dead_animal', 'aquatic_species', 'other_reference')),
    ADD COLUMN group_score real CHECK (group_score BETWEEN 0 AND 1),
    ADD COLUMN vector_breeding_risk real CHECK (vector_breeding_risk BETWEEN 0 AND 1),
    ADD COLUMN environmental_signal real CHECK (environmental_signal BETWEEN 0 AND 1),
    ADD COLUMN human_contact_risk real CHECK (human_contact_risk BETWEEN 0 AND 1),
    -- After a community intervention (section "Before/After Verification -> Update Risk"):
    ADD COLUMN group_score_after real CHECK (group_score_after BETWEEN 0 AND 1),
    ADD COLUMN treated_at timestamptz;

CREATE INDEX observations_vector_group_idx ON observations (vector_group);

-- Photos a verifier takes on site. 'after' photos are scored with the same group rule,
-- so the dashboard can show the score before and after the clean-up.
CREATE TABLE verification_photos (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      uuid NOT NULL REFERENCES verification_tasks(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('before', 'after')),
    image_path   text NOT NULL,
    group_score  real CHECK (group_score BETWEEN 0 AND 1),
    analysis     jsonb NOT NULL,
    uploaded_by  text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verification_photos_task_idx ON verification_photos (task_id);
