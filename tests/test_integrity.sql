-- ===========================================================================
-- tests/test_integrity.sql
-- Warehouse referential-integrity and grain checks.
-- Owner: Person 5 (QA / Data Quality)
--
-- Contract: every statement returns exactly (check_name, failure_count).
-- scripts/check_integrity.py runs them and exits non-zero if any count > 0,
-- which is what `make test` and CI rely on.
--
-- The declared FOREIGN KEY constraints already make orphans impossible, so
-- these checks are the belt to that braces: they also catch the load running
-- against a database where the constraints were dropped or never applied.
-- ===========================================================================

-- --- FK #1: departure role of dim_airport ---------------------------------
SELECT 'fact.departure_airport_key -> dim_airport.airport_key' AS check_name,
       count(*)                                                AS failure_count
FROM fact_flight f
LEFT JOIN dim_airport d ON d.airport_key = f.departure_airport_key
WHERE d.airport_key IS NULL;

-- --- FK #2: arrival role of the SAME dim_airport table --------------------
SELECT 'fact.arrival_airport_key -> dim_airport.airport_key' AS check_name,
       count(*)                                             AS failure_count
FROM fact_flight f
LEFT JOIN dim_airport d ON d.airport_key = f.arrival_airport_key
WHERE d.airport_key IS NULL;

-- --- FK: dim_date ---------------------------------------------------------
SELECT 'fact.date_key -> dim_date.date_key' AS check_name,
       count(*)                             AS failure_count
FROM fact_flight f
LEFT JOIN dim_date d ON d.date_key = f.date_key
WHERE d.date_key IS NULL;

-- --- FK: dim_time, departure role -----------------------------------------
SELECT 'fact.departure_time_key -> dim_time.time_key' AS check_name,
       count(*)                                       AS failure_count
FROM fact_flight f
LEFT JOIN dim_time t ON t.time_key = f.departure_time_key
WHERE t.time_key IS NULL;

-- --- FK: dim_time, arrival role -------------------------------------------
SELECT 'fact.arrival_time_key -> dim_time.time_key' AS check_name,
       count(*)                                     AS failure_count
FROM fact_flight f
LEFT JOIN dim_time t ON t.time_key = f.arrival_time_key
WHERE t.time_key IS NULL;

-- --- FK: dim_airline ------------------------------------------------------
SELECT 'fact.airline_key -> dim_airline.airline_key' AS check_name,
       count(*)                                      AS failure_count
FROM fact_flight f
LEFT JOIN dim_airline a ON a.airline_key = f.airline_key
WHERE a.airline_key IS NULL;

-- --- No NULL foreign keys -------------------------------------------------
SELECT 'fact_flight has no NULL dimension keys' AS check_name,
       count(*)                                 AS failure_count
FROM fact_flight
WHERE date_key IS NULL
   OR departure_time_key IS NULL
   OR arrival_time_key IS NULL
   OR departure_airport_key IS NULL
   OR arrival_airport_key IS NULL
   OR airline_key IS NULL;

-- --- Grain: no duplicate legs survived the pipeline -----------------------
SELECT 'fact_flight grain is unique' AS check_name,
       count(*)                      AS failure_count
FROM (
    SELECT date_key, flight_no, departure_airport_key,
           arrival_airport_key, departure_time_key
    FROM fact_flight
    GROUP BY 1, 2, 3, 4, 5
    HAVING count(*) > 1
) dupes;

-- --- Measures are sane ----------------------------------------------------
SELECT 'fact_flight.duration_minutes is positive' AS check_name,
       count(*)                                    AS failure_count
FROM fact_flight
WHERE duration_minutes IS NULL OR duration_minutes <= 0;

SELECT 'fact_flight.duration_minutes matches the reported value' AS check_name,
       count(*)                                                  AS failure_count
FROM fact_flight
WHERE reported_duration_minutes IS NOT NULL
  AND duration_minutes <> reported_duration_minutes;

-- --- A leg never departs from and arrives at the same airport -------------
SELECT 'fact_flight departure <> arrival airport' AS check_name,
       count(*)                                   AS failure_count
FROM fact_flight
WHERE departure_airport_key = arrival_airport_key;

-- --- Ambiguous metro codes never reached the warehouse --------------------
SELECT 'dim_airport contains no ambiguous metro codes' AS check_name,
       count(*)                                         AS failure_count
FROM dim_airport
WHERE airport_code IN ('NY', 'NYC', 'WAS', 'CHI', 'LON', 'TYO');

-- --- dim_airport is a single physical table used in two roles ------------
SELECT 'dim_airport.airport_code is unique' AS check_name,
       count(*)                              AS failure_count
FROM (
    SELECT airport_code FROM dim_airport GROUP BY airport_code HAVING count(*) > 1
) dupes;

-- --- dim_time is complete (all 1 440 minutes) -----------------------------
SELECT 'dim_time holds all 1440 minutes' AS check_name,
       abs(1440 - count(*))               AS failure_count
FROM dim_time;

-- --- Smart keys are internally consistent ---------------------------------
SELECT 'dim_date.date_key equals YYYYMMDD of full_date' AS check_name,
       count(*)                                          AS failure_count
FROM dim_date
WHERE date_key <> to_char(full_date, 'YYYYMMDD')::INTEGER;

SELECT 'dim_time.time_key equals hour_24 * 100 + minute' AS check_name,
       count(*)                                           AS failure_count
FROM dim_time
WHERE time_key <> hour_24 * 100 + minute;

-- --- The fact table is not empty (a silent no-op load is a failure) ------
SELECT 'fact_flight is populated' AS check_name,
       CASE WHEN count(*) = 0 THEN 1 ELSE 0 END AS failure_count
FROM fact_flight;
