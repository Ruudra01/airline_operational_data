-- ===========================================================================
-- dim_airport  (owner: Person 4, Warehouse Modeller)
--
-- ONE physical airport table, used TWICE by fact_flight through two separate
-- foreign keys (departure_airport_key, arrival_airport_key). This is the
-- classic role-playing dimension: the departure and arrival "dimensions" are
-- views over this single table, so a station's name, city and country are
-- stored once and can never disagree between the two roles.
--
-- Ambiguous metro codes (e.g. 'NY') are NEVER loaded here - the transform
-- layer rejects them upstream, so every key in this table identifies exactly
-- one physical airport.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS dim_airport (
    airport_key   SERIAL       PRIMARY KEY,      -- surrogate key
    airport_code  VARCHAR(4)   NOT NULL UNIQUE,  -- 'DTW' (natural key)
    airport_name  VARCHAR(120) NOT NULL,
    city          VARCHAR(80)  NOT NULL,
    state         VARCHAR(40),                   -- NULL outside the US
    country       VARCHAR(60)  NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT dim_airport_code_upper CHECK (airport_code = upper(airport_code))
);

CREATE INDEX IF NOT EXISTS ix_dim_airport_city ON dim_airport (city);

COMMENT ON TABLE dim_airport IS
    'Role-playing airport dimension: one physical table referenced twice by '
    'fact_flight (departure and arrival roles).';

-- ---------------------------------------------------------------------------
-- Role-playing views. BI tools join these instead of aliasing the base table,
-- which keeps column names unambiguous in a single SELECT.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dim_departure_airport AS
SELECT airport_key  AS departure_airport_key,
       airport_code AS departure_airport_code,
       airport_name AS departure_airport_name,
       city         AS departure_city,
       state        AS departure_state,
       country      AS departure_country
FROM dim_airport;

CREATE OR REPLACE VIEW dim_arrival_airport AS
SELECT airport_key  AS arrival_airport_key,
       airport_code AS arrival_airport_code,
       airport_name AS arrival_airport_name,
       city         AS arrival_city,
       state        AS arrival_state,
       country      AS arrival_country
FROM dim_airport;
