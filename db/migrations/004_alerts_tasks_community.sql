-- Sections 17-21: alerts, community tasks, points, notifications, feedback on AI results.

-- Alerts: a hotspot that people act on. Refreshed from the clustering after each report;
-- an alert keeps its identity while its cluster grows, so it is not re-created each time.
CREATE TABLE alerts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category        text NOT NULL,
    level           text NOT NULL CHECK (level IN ('green', 'yellow', 'orange', 'red')),
    status          text NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'verified', 'resolved', 'dismissed')),
    latitude        double precision NOT NULL,
    longitude       double precision NOT NULL,
    geom            geography(Point, 4326) GENERATED ALWAYS AS (
                        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    spread_m        real NOT NULL,
    reports         integer NOT NULL,
    reporters       integer NOT NULL,
    max_risk        real NOT NULL,
    hull            jsonb,
    observation_ids uuid[] NOT NULL,
    is_demo         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    verified_by     text,
    verified_at     timestamptz,
    resolved_at     timestamptz,
    note            text NOT NULL DEFAULT ''
);
CREATE INDEX alerts_geom_idx ON alerts USING GIST (geom);
CREATE INDEX alerts_status_idx ON alerts (status);

-- Community tasks (section 19): "check 3 standing-water sites after the rain, in 24 h".
-- Completed when the volunteer has sent after-photos for enough reports in the area.
CREATE TABLE community_tasks (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title         text NOT NULL,
    description   text NOT NULL DEFAULT '',
    category      text NOT NULL DEFAULT 'vector',
    latitude      double precision NOT NULL,
    longitude     double precision NOT NULL,
    geom          geography(Point, 4326) GENERATED ALWAYS AS (
                      ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    radius_m      real NOT NULL CHECK (radius_m > 0),
    target_count  integer NOT NULL CHECK (target_count > 0),
    reward_points integer NOT NULL CHECK (reward_points >= 0),
    deadline      timestamptz NOT NULL,
    alert_id      uuid REFERENCES alerts(id) ON DELETE SET NULL,
    created_by    text NOT NULL,
    status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'expired')),
    completed_by  text,
    completed_at  timestamptz,
    is_demo       boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Points (section 19). One row per award; the unique key makes every award idempotent.
CREATE TABLE points_ledger (
    id          bigserial PRIMARY KEY,
    user_id     text NOT NULL,
    points      integer NOT NULL,
    reason      text NOT NULL,
    ref_id      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, reason, ref_id)
);
CREATE INDEX points_ledger_user_idx ON points_ledger (user_id);

-- Notifications (section 20): area notices (no user_id) and personal ones (user_id set).
CREATE TABLE notifications (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,
    level       text,
    user_id     text,
    latitude    double precision,
    longitude   double precision,
    geom        geography(Point, 4326) GENERATED ALWAYS AS (
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    message     text NOT NULL,
    ref_id      text,
    is_demo     boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_geom_idx ON notifications USING GIST (geom);
CREATE INDEX notifications_user_idx ON notifications (user_id);

-- "Đánh dấu thông tin sai" on the AI result screen: kept as labels for the next training round.
CREATE TABLE observation_feedback (
    id              bigserial PRIMARY KEY,
    observation_id  uuid NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    reporter_id     text,
    wrong_items     text[] NOT NULL DEFAULT '{}',
    note            text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);
