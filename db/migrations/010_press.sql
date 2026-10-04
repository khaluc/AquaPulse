-- What the Vietnamese press reported about a canal, from Google News RSS. Context for a
-- segment's passport: a headline is not a measurement, so these rows never enter any score,
-- hotspot or alert. Only title, source, date and link are stored, as a news index does.
CREATE TABLE press_mentions (
    id            bigserial PRIMARY KEY,
    url           text NOT NULL UNIQUE,
    title         text NOT NULL,
    source        text,
    published_at  timestamptz NOT NULL,
    waterway      text,              -- matched canal name, NULL when the article names none of ours
    tags          text[] NOT NULL DEFAULT '{}',   -- rác, nước đen, mùi hôi, cá chết, ngập, cải tạo
    query         text,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX press_mentions_published_idx ON press_mentions (published_at DESC);
CREATE INDEX press_mentions_waterway_idx ON press_mentions (waterway);
