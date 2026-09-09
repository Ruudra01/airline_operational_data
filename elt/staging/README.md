# `elt/staging/` — Owner: **Person 2, Extraction Engineer**

DDL for the raw landing zone.

## `stg_flight_ops`
The six columns required by the spec — `dep_code`, `arr_code`,
`arrival_time`, `departure_time`, `duration`, `flight_no` — plus audit
columns (`stg_id`, `source_system`, `source_row_id`, `batch_id`,
`loaded_at`).

**Everything is `TEXT`, and there are no constraints.** That is deliberate:

* `dep_code` must be able to hold `'NY'`, otherwise the extract fails before
  the transform can report the defect.
* `departure_time` must be able to hold `'2026-09-09 10:00 AM'`.
* Duplicates must be able to land, because `row_number()` in
  `elt/transform/main.py` is what removes them.

`stg_id` (a `BIGSERIAL`) gives the de-duplication window function a
deterministic `ORDER BY`, so the same input always produces the same output.

`stg_flight_ops_rejects` holds every row the transform refused, with the
reason, for operational triage.

## Where does staging live?
Next to the OLTP by default (it is source-shaped, not star-shaped). Set
`STAGING_TARGET=dw` to land it in the warehouse database instead.

## Commands
```bash
make migrate   # includes elt/staging/create_staging.sql
```
