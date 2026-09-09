-- ===========================================================================
-- V1__initial_schema.sql
-- OLTP (3NF) schema for airline operations.  Owner: Person 1 (OLTP Modeller)
--
-- Normalisation notes
--   * airport / airline are independent reference entities.
--   * flight is the *route definition* (which airline, which number, from
--     where to where).  It depends on airline + airport only.
--   * flight_instance is one operated occurrence of a flight on one date.
--     Times are stored EXACTLY as the operational source system emits them
--     (12-hour clock strings such as '10:00 AM') because cleaning is the
--     warehouse's job, not the source's.  The ELT layer standardises them.
--
-- Idempotent: every object is created with IF NOT EXISTS so the Flyway-style
-- runner can be re-pointed at a fresh database at any time.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- airport
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airport (
    airport_id   SERIAL       PRIMARY KEY,
    code         VARCHAR(4)   NOT NULL UNIQUE,   -- IATA station code as received
    name         VARCHAR(120) NOT NULL,
    city         VARCHAR(80)  NOT NULL,
    state        VARCHAR(40),                    -- NULL for non-US stations
    country      VARCHAR(60)  NOT NULL DEFAULT 'USA',
    is_ambiguous BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT airport_code_upper CHECK (code = upper(code))
);

COMMENT ON COLUMN airport.is_ambiguous IS
    'TRUE for city/metro codes such as NY that do NOT identify a single '
    'airport. Kept in the OLTP so the pipeline has real dirty data to '
    'reject; never promoted to dim_airport.';

-- ---------------------------------------------------------------------------
-- airline
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS airline (
    airline_id SERIAL       PRIMARY KEY,
    iata_code  VARCHAR(3)   NOT NULL UNIQUE,     -- 'DL'
    icao_code  VARCHAR(4),                       -- 'DAL'
    name       VARCHAR(120) NOT NULL,
    country    VARCHAR(60)  NOT NULL DEFAULT 'USA',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT airline_code_upper CHECK (iata_code = upper(iata_code))
);

-- ---------------------------------------------------------------------------
-- flight  (route definition: DL857 DTW->JFK is one row)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight (
    flight_id             SERIAL      PRIMARY KEY,
    airline_id            INTEGER     NOT NULL REFERENCES airline (airline_id),
    flight_number         VARCHAR(6)  NOT NULL,  -- '857' (no carrier prefix: 3NF)
    departure_airport_id  INTEGER     NOT NULL REFERENCES airport (airport_id),
    arrival_airport_id    INTEGER     NOT NULL REFERENCES airport (airport_id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT flight_distinct_endpoints
        CHECK (departure_airport_id <> arrival_airport_id),
    CONSTRAINT flight_natural_key
        UNIQUE (airline_id, flight_number, departure_airport_id, arrival_airport_id)
);

CREATE INDEX IF NOT EXISTS ix_flight_airline  ON flight (airline_id);
CREATE INDEX IF NOT EXISTS ix_flight_dep_arr  ON flight (departure_airport_id, arrival_airport_id);

-- ---------------------------------------------------------------------------
-- flight_instance  (one operated leg on one calendar date)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_instance (
    flight_instance_id  BIGSERIAL   PRIMARY KEY,
    flight_id           INTEGER     NOT NULL REFERENCES flight (flight_id),
    service_date        DATE        NOT NULL,
    -- Raw 12-hour clock strings straight from the operational feed.
    departure_time_local VARCHAR(12) NOT NULL,   -- '10:00 AM'
    arrival_time_local   VARCHAR(12) NOT NULL,   -- '11:45 AM'
    duration_raw         VARCHAR(16) NOT NULL,   -- '1h 45m' (source-reported)
    tail_number          VARCHAR(10),
    source_system        VARCHAR(40) NOT NULL DEFAULT 'ops_feed',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deliberately NO unique constraint on (flight_id, service_date,
-- departure_time_local): the upstream feed is known to re-send legs, and the
-- transform layer is the component responsible for de-duplicating them with
-- row_number(). Constraining it here would hide the defect the pipeline is
-- supposed to handle.
CREATE INDEX IF NOT EXISTS ix_flight_instance_flight ON flight_instance (flight_id);
CREATE INDEX IF NOT EXISTS ix_flight_instance_date   ON flight_instance (service_date);

-- ---------------------------------------------------------------------------
-- Convenience view: the exact shape the extract step copies to staging.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_flight_ops_export AS
SELECT
    dep.code                                                       AS dep_code,
    arr.code                                                       AS arr_code,
    to_char(fi.service_date, 'YYYY-MM-DD') || ' ' || fi.arrival_time_local   AS arrival_time,
    to_char(fi.service_date, 'YYYY-MM-DD') || ' ' || fi.departure_time_local AS departure_time,
    fi.duration_raw                                                AS duration,
    al.iata_code || fi_flight.flight_number                        AS flight_no,
    fi.source_system                                               AS source_system,
    fi.flight_instance_id                                          AS source_row_id
FROM flight_instance fi
JOIN flight  fi_flight ON fi_flight.flight_id = fi.flight_id
JOIN airline al        ON al.airline_id       = fi_flight.airline_id
JOIN airport dep       ON dep.airport_id      = fi_flight.departure_airport_id
JOIN airport arr       ON arr.airport_id      = fi_flight.arrival_airport_id;
