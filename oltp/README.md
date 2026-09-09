# `oltp/` — Owner: **Person 1, OLTP Data Modeller**

## Responsibility
Own the 3NF operational schema and the mock operational feed. This folder is
the *source system*: it is allowed to be dirty, and it is not allowed to know
anything about the warehouse.

## Contents
| Path | What it is |
|---|---|
| `migrations/V1__initial_schema.sql` | All OLTP DDL. Flyway-style naming: `V<n>__<description>.sql` |
| `seeds/generate_mock_data.py` | Generates exactly 10 `flight_instance` rows (DL857 DTW→JFK and JFK→SFO, Sep 9, 12-hour clock times) |

## The model
```
airline ──┐
          ├──< flight >──┬── departure_airport_id ─┐
airport ──┘              └── arrival_airport_id  ──┴──> airport
                │
                └──< flight_instance   (one operated leg, one date)
```

* `flight` is the **route definition** (DL857 DTW→JFK is one row).
* `flight_instance` is **one operated occurrence** on one `service_date`.
* Times are stored as raw source strings (`'10:00 AM'`), not `TIME`. Cleaning
  is the warehouse's job — see `elt/transform/`.
* `airport.is_ambiguous` marks metro codes such as `NY`. They stay in the OLTP
  so the pipeline has real dirty data to reject.
* `flight_instance` has **no** unique constraint on
  `(flight_id, service_date, departure_time_local)` on purpose: the upstream
  feed replays legs, and de-duplication is the transform layer's job.

## Rules of engagement
* Never edit an applied migration — `scripts/migrate.py` compares checksums
  and will refuse. Add `V2__…sql` instead.
* Never resolve or clean data here.

## Commands
```bash
make migrate   # apply oltp/migrations
make seed      # load the 10 mock flight instances
make psql-oltp # poke around
```
