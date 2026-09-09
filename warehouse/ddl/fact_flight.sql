-- ===========================================================================
-- fact_flight  (owner: Person 4, Warehouse Modeller)
--
-- Grain: ONE ROW PER OPERATED FLIGHT LEG (flight number + service date +
-- scheduled departure). Transaction-grain fact table.
--
-- Foreign keys
--   date_key            -> dim_date     (service date of departure)
--   departure_time_key  -> dim_time     role-playing time dimension
--   arrival_time_key    -> dim_time
--   departure_airport_key -> dim_airport  <-- role-playing airport, FK #1
--   arrival_airport_key   -> dim_airport  <-- role-playing airport, FK #2
--   airline_key         -> dim_airline
--
-- Degenerate dimension: flight_no ('DL857') has no attributes of its own, so
-- it lives on the fact row rather than in a one-column dimension.
--
-- Measures: duration_minutes (additive), plus the source-reported value kept
-- alongside it for auditability.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS fact_flight (
    flight_fact_key       BIGSERIAL   PRIMARY KEY,

    -- dimension foreign keys ------------------------------------------------
    date_key              INTEGER     NOT NULL REFERENCES dim_date (date_key),
    departure_time_key    INTEGER     NOT NULL REFERENCES dim_time (time_key),
    arrival_time_key      INTEGER     NOT NULL REFERENCES dim_time (time_key),
    departure_airport_key INTEGER     NOT NULL REFERENCES dim_airport (airport_key),
    arrival_airport_key   INTEGER     NOT NULL REFERENCES dim_airport (airport_key),
    airline_key           INTEGER     NOT NULL REFERENCES dim_airline (airline_key),

    -- degenerate dimension --------------------------------------------------
    flight_no             VARCHAR(8)  NOT NULL,

    -- measures --------------------------------------------------------------
    duration_minutes           INTEGER NOT NULL,
    reported_duration_minutes  INTEGER,
    crossed_midnight           BOOLEAN NOT NULL DEFAULT FALSE,
    flight_count               SMALLINT NOT NULL DEFAULT 1,  -- additive counter

    -- lineage ---------------------------------------------------------------
    source_row_id         BIGINT,
    loaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fact_flight_duration_positive CHECK (duration_minutes > 0),
    CONSTRAINT fact_flight_distinct_airports
        CHECK (departure_airport_key <> arrival_airport_key),
    -- Enforces the declared grain, so a re-run can never double-count.
    CONSTRAINT fact_flight_grain UNIQUE
        (date_key, flight_no, departure_airport_key, arrival_airport_key, departure_time_key)
);

CREATE INDEX IF NOT EXISTS ix_fact_flight_date        ON fact_flight (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_flight_dep_airport ON fact_flight (departure_airport_key);
CREATE INDEX IF NOT EXISTS ix_fact_flight_arr_airport ON fact_flight (arrival_airport_key);
CREATE INDEX IF NOT EXISTS ix_fact_flight_airline    ON fact_flight (airline_key);

COMMENT ON COLUMN fact_flight.flight_no IS
    'Degenerate dimension: carrier + number, no attributes of its own.';
COMMENT ON COLUMN fact_flight.departure_airport_key IS
    'Role-playing FK #1 into dim_airport.';
COMMENT ON COLUMN fact_flight.arrival_airport_key IS
    'Role-playing FK #2 into the SAME dim_airport table.';

-- ---------------------------------------------------------------------------
-- Reporting view: resolves both airport roles so BI never has to self-join.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fact_flight_enriched AS
SELECT f.flight_fact_key,
       f.flight_no,
       d.full_date,
       d.year,
       d.month,
       d.quarter,
       al.airline_code,
       al.airline_name,
       dep.airport_code AS departure_airport_code,
       dep.city         AS departure_city,
       arr.airport_code AS arrival_airport_code,
       arr.city         AS arrival_city,
       dep_t.time_24h   AS departure_time_24h,
       arr_t.time_24h   AS arrival_time_24h,
       dep_t.am_pm      AS departure_am_pm,
       f.duration_minutes,
       f.crossed_midnight
FROM fact_flight f
JOIN dim_date    d   ON d.date_key      = f.date_key
JOIN dim_airline al  ON al.airline_key  = f.airline_key
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key
JOIN dim_time    dep_t ON dep_t.time_key = f.departure_time_key
JOIN dim_time    arr_t ON arr_t.time_key = f.arrival_time_key;
