-- ===========================================================================
-- dim_date  (owner: Person 4, Warehouse Modeller)
-- Smart integer key in YYYYMMDD form, so 2026-09-09 -> 20260909.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS dim_date (
    date_key     INTEGER     PRIMARY KEY,   -- YYYYMMDD, e.g. 20260909
    full_date    DATE        NOT NULL UNIQUE,
    day          SMALLINT    NOT NULL,      -- 1-31
    month        SMALLINT    NOT NULL,      -- 1-12
    quarter      SMALLINT    NOT NULL,      -- 1-4
    year         SMALLINT    NOT NULL,
    day_name     VARCHAR(9)  NOT NULL,      -- 'Wednesday'
    month_name   VARCHAR(9)  NOT NULL,      -- 'September'
    day_of_week  SMALLINT    NOT NULL,      -- 1 = Monday .. 7 = Sunday
    is_weekend   BOOLEAN     NOT NULL,
    CONSTRAINT dim_date_key_matches_date
        CHECK (date_key = to_char(full_date, 'YYYYMMDD')::INTEGER),
    CONSTRAINT dim_date_parts_valid
        CHECK (day BETWEEN 1 AND 31 AND month BETWEEN 1 AND 12 AND quarter BETWEEN 1 AND 4)
);

COMMENT ON COLUMN dim_date.date_key IS 'Smart key: YYYYMMDD as an INTEGER.';
