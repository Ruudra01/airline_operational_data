-- ===========================================================================
-- dim_time  (owner: Person 4, Warehouse Modeller)
-- Minute-grain time-of-day dimension, fully populated with all 1 440 minutes
-- by warehouse/load/load_warehouse.py.
-- Smart integer key in HHMM form, so 13:00 -> 1300 and 00:05 -> 5.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS dim_time (
    time_key    INTEGER    PRIMARY KEY,   -- HHMM, e.g. 1300 for 13:00
    hour_24     SMALLINT   NOT NULL,      -- 0-23
    minute      SMALLINT   NOT NULL,      -- 0-59
    am_pm       CHAR(2)    NOT NULL,      -- 'AM' / 'PM'
    hour_12     SMALLINT   NOT NULL,      -- 1-12, for 12-hour reporting
    time_24h    CHAR(5)    NOT NULL,      -- '13:00'
    time_12h    VARCHAR(8) NOT NULL,      -- '1:00 PM'
    day_part    VARCHAR(12) NOT NULL,     -- Night/Morning/Afternoon/Evening
    CONSTRAINT dim_time_key_matches_parts CHECK (time_key = hour_24 * 100 + minute),
    CONSTRAINT dim_time_ranges CHECK (hour_24 BETWEEN 0 AND 23 AND minute BETWEEN 0 AND 59),
    CONSTRAINT dim_time_am_pm CHECK (am_pm IN ('AM', 'PM'))
);

COMMENT ON COLUMN dim_time.time_key IS 'Smart key: hour_24 * 100 + minute.';
