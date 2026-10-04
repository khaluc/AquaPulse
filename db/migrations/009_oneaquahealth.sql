-- Data from the OneAquaHealth consortium's open API (api.enora-oah.eu), the source the
-- hackathon points at: its pilot cities, its research sites, the sites people created in
-- the OneAquaHealth Citizen Science App, the health-risk indicators measured at each site,
-- and a few urban context numbers. Kept in its own tables: it is their measurement, never
-- mixed into our citizen scores.
CREATE TABLE oah_cities (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE oah_sites (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    city_id     text REFERENCES oah_cities(id),
    kind        text NOT NULL CHECK (kind IN ('research', 'citizen')),  -- citizen = Citizen Science App
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    geom        geography(Point, 4326) GENERATED ALWAYS AS (
                    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED,
    altitude    real,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX oah_sites_geom_idx ON oah_sites USING GIST (geom);
CREATE INDEX oah_sites_city_idx ON oah_sites (city_id);

-- One row per sampling: their laboratory-derived risks, 0-1, as published.
CREATE TABLE oah_health_risks (
    site_code       text NOT NULL,
    sampled_on      date,
    pathogen_risk   real,
    fecal_risk      real,
    arg_risk        real,   -- antibiotic-resistance genes
    health_risk     real,
    PRIMARY KEY (site_code, sampled_on)
);

-- Urban context around a site; only the fields a citizen page can explain.
CREATE TABLE oah_urban_context (
    site_code            text PRIMARY KEY,
    urban_pct_500m       real,
    impervious_pct_500m  real,
    veg_cover_frac_500m  real,
    distance_sewage_m    real,
    distance_motorway_m  real
);
