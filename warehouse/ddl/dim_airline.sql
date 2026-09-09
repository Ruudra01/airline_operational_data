-- ===========================================================================
-- dim_airline  (owner: Person 4, Warehouse Modeller)
-- Conformed carrier dimension. Type 1 (overwrite on change).
-- Applied before fact_flight because migrate.py orders files by filename and
-- 'dim_*' sorts before 'fact_*'.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS dim_airline (
    airline_key   SERIAL       PRIMARY KEY,   -- surrogate key
    airline_code  VARCHAR(3)   NOT NULL UNIQUE,  -- 'DL' (natural/business key)
    icao_code     VARCHAR(4),
    airline_name  VARCHAR(120) NOT NULL,
    country       VARCHAR(60)  NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE dim_airline IS 'Type 1 carrier dimension keyed by IATA code.';
