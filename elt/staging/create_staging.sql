-- ===========================================================================
-- create_staging.sql
-- Raw landing zone for the operational feed.  Owner: Person 2 (Extraction)
--
-- Design rules for staging:
--   * Every business column is TEXT. Staging must accept whatever the source
--     sends - including '10:00 AM', '1h 45m' and the ambiguous code 'NY'.
--     Typing it here would make the extract fail on dirty data instead of
--     letting the transform layer report on it.
--   * No constraints, no foreign keys, no unique keys. Duplicates are
--     expected and are removed downstream with row_number().
--   * stg_id / loaded_at are audit columns: stg_id gives the deterministic
--     tie-break the de-duplication window function orders by.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS stg_flight_ops (
    -- the six columns required by the specification --------------------------
    dep_code        TEXT,          -- 'DTW'   (may be ambiguous, e.g. 'NY')
    arr_code        TEXT,          -- 'JFK'
    arrival_time    TEXT,          -- '2026-09-09 11:45 AM'
    departure_time  TEXT,          -- '2026-09-09 10:00 AM'
    duration        TEXT,          -- '1h 45m' as reported by the source
    flight_no       TEXT,          -- 'DL857'
    -- audit columns ----------------------------------------------------------
    stg_id          BIGSERIAL PRIMARY KEY,
    source_system   TEXT,
    source_row_id   BIGINT,        -- flight_instance_id in the OLTP
    batch_id        TEXT,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_stg_flight_ops_flight_no ON stg_flight_ops (flight_no);
CREATE INDEX IF NOT EXISTS ix_stg_flight_ops_batch     ON stg_flight_ops (batch_id);

COMMENT ON TABLE stg_flight_ops IS
    'Untyped 1:1 landing copy of the airline operations feed. Truncated and '
    'reloaded by elt/extract/extract_to_staging.py on every run.';

-- ---------------------------------------------------------------------------
-- Rejects table: rows the transform refused, kept for operational triage.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_flight_ops_rejects (
    reject_id      BIGSERIAL PRIMARY KEY,
    stg_id         BIGINT,
    dep_code       TEXT,
    arr_code       TEXT,
    arrival_time   TEXT,
    departure_time TEXT,
    duration       TEXT,
    flight_no      TEXT,
    reject_reason  TEXT NOT NULL,
    rejected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
