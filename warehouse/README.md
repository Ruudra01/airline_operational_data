# `warehouse/` — Owner: **Person 4, Warehouse Modeller**

The star schema and its loader.

```
                        dim_date
                            │
        dim_airport ────────┼──────── dim_airport
     (departure role)       │      (arrival role)
                        fact_flight
                            │
        dim_time ───────────┼─────────── dim_airline
```

## The role-playing airport dimension
There is **ONE physical table**, `dim_airport`. `fact_flight` references it
**twice**:

```sql
departure_airport_key INTEGER NOT NULL REFERENCES dim_airport (airport_key),
arrival_airport_key   INTEGER NOT NULL REFERENCES dim_airport (airport_key),
```

Why one table and not `dim_departure_airport` + `dim_arrival_airport`:
* Detroit's name, city and state are stored **once**, so the two roles can
  never disagree.
* A new attribute (timezone, hub flag) is added in one place.
* `dim_airport` is *conformed*: any future fact (bookings, delays) joins the
  same table.

Two convenience views, `dim_departure_airport` and `dim_arrival_airport`,
pre-alias the columns so BI can join both roles in one `SELECT` without
column-name collisions. `dim_time` plays the same trick for
`departure_time_key` / `arrival_time_key`.

## Files
| Path | Table |
|---|---|
| `ddl/dim_airline.sql` | `dim_airline` (+ surrogate key) |
| `ddl/dim_airport.sql` | `dim_airport` (+ the two role views) |
| `ddl/dim_date.sql` | `dim_date`, `date_key` = `YYYYMMDD` INT |
| `ddl/dim_time.sql` | `dim_time`, `time_key` = `HHMM` INT |
| `ddl/fact_flight.sql` | `fact_flight` (+ `v_fact_flight_enriched`) |
| `load/load_warehouse.py` | Dimensions first, then the fact |

`scripts/migrate.py` orders files by filename, and `dim_*` sorts before
`fact_*`, so the FK targets always exist before the fact table is created.

## Grain and key design
* **Grain**: one row per operated flight leg (`flight_no` + service date +
  scheduled departure), enforced by the `fact_flight_grain` unique key.
* **Smart keys**: `20260909` for 2026-09-09, `1300` for 13:00. Readable in
  raw fact rows and partition-friendly.
* **Degenerate dimension**: `flight_no` sits on the fact row — it has no
  attributes of its own.
* Ambiguous codes never reach `dim_airport`, so every airport key identifies
  exactly one physical airport.

## Load order (enforced in code)
`dim_airport` → `dim_airline` → `dim_time` (all 1 440 minutes) →
`dim_date` (dates in the batch) → `fact_flight`.
Any fact row whose dimension key cannot be resolved **fails the load** rather
than being inserted as an orphan.

## Commands
```bash
make load
make psql-dw
```
