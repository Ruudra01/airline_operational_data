# `bi/` — Owner: **Person 6, BI / Analytics**

Consumption layer. Reads the star schema only — never staging, never the OLTP.

## `marts/route_analytics.sql`
Average block time by **departure city** and **arrival city**, which is the
query that demonstrates the role-playing dimension:

```sql
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key  -- role 1
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key    -- role 2
```

One physical `dim_airport`, joined twice, reads as "Detroit → New York".

Also in the file:
* `mart_route_analytics` — a materialised view so dashboards hit a table
  (`REFRESH MATERIALIZED VIEW mart_route_analytics;` after each load).
* Average duration by departure time-of-day bucket, via `dim_time.day_part`.

## Expected output on the seeded data
| departure_city | arrival_city | flights | avg_duration_minutes |
|---|---|---|---|
| New York | San Francisco | 4 | 211.3 |
| Detroit | New York | 3 | 106.7 |

## Run it
```bash
docker compose exec -T postgres_dw psql -U airline -d airline_dw \
  -f - < bi/marts/route_analytics.sql
```

Or point Metabase / Superset / Power BI at `postgres_dw` on port 5433 and
start from `v_fact_flight_enriched`.
