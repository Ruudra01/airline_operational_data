-- ===========================================================================
-- bi/marts/route_analytics.sql
-- Average block time by departure city and arrival city.
-- Owner: Person 6 (BI / Analytics)
--
-- This is THE query that proves the role-playing dimension works: dim_airport
-- is joined twice against the same physical table - once through
-- departure_airport_key, once through arrival_airport_key - so a route reads
-- as "Detroit -> New York" from one dimension used in two roles.
--
-- Run it directly:
--   docker compose exec -T postgres_dw \
--     psql -U airline -d airline_dw -f - < bi/marts/route_analytics.sql
-- ===========================================================================

-- --- Headline: average duration per city pair -----------------------------
SELECT dep.city                                   AS departure_city,
       dep.airport_code                           AS departure_airport,
       arr.city                                   AS arrival_city,
       arr.airport_code                           AS arrival_airport,
       count(*)                                   AS flights,
       round(avg(f.duration_minutes), 1)          AS avg_duration_minutes,
       min(f.duration_minutes)                    AS min_duration_minutes,
       max(f.duration_minutes)                    AS max_duration_minutes,
       round(avg(f.duration_minutes) / 60.0, 2)   AS avg_duration_hours
FROM fact_flight f
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key  -- role 1
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key    -- role 2
GROUP BY dep.city, dep.airport_code, arr.city, arr.airport_code
ORDER BY avg_duration_minutes DESC;

-- ---------------------------------------------------------------------------
-- Persisted mart, so BI tools query a table instead of re-deriving the joins.
-- Refresh with:  REFRESH MATERIALIZED VIEW mart_route_analytics;
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mart_route_analytics AS
SELECT dep.city                              AS departure_city,
       dep.airport_code                      AS departure_airport,
       dep.state                             AS departure_state,
       arr.city                              AS arrival_city,
       arr.airport_code                      AS arrival_airport,
       arr.state                             AS arrival_state,
       al.airline_code,
       al.airline_name,
       count(*)                              AS flights,
       round(avg(f.duration_minutes), 1)     AS avg_duration_minutes,
       min(f.duration_minutes)               AS min_duration_minutes,
       max(f.duration_minutes)               AS max_duration_minutes,
       sum(f.duration_minutes)               AS total_block_minutes,
       count(*) FILTER (WHERE f.crossed_midnight) AS overnight_flights,
       min(d.full_date)                      AS first_service_date,
       max(d.full_date)                      AS last_service_date
FROM fact_flight f
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key
JOIN dim_airline al  ON al.airline_key  = f.airline_key
JOIN dim_date    d   ON d.date_key      = f.date_key
GROUP BY dep.city, dep.airport_code, dep.state,
         arr.city, arr.airport_code, arr.state,
         al.airline_code, al.airline_name;

-- --- Supporting cut: average duration by departure time-of-day bucket -----
SELECT dep.city                            AS departure_city,
       arr.city                            AS arrival_city,
       t.day_part                          AS departure_day_part,
       count(*)                            AS flights,
       round(avg(f.duration_minutes), 1)   AS avg_duration_minutes
FROM fact_flight f
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key
JOIN dim_time    t   ON t.time_key      = f.departure_time_key
GROUP BY dep.city, arr.city, t.day_part
ORDER BY dep.city, arr.city, avg_duration_minutes DESC;
