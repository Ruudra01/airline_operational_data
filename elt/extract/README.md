# `elt/extract/` — Owner: **Person 2, Extraction Engineer**

Copies the operational feed out of the OLTP into `stg_flight_ops`.

## Contract
* **No cleaning.** No casting, no filtering, no code resolution. The
  ambiguous `NY` station, the replayed duplicate leg and the wrong duration
  all land in staging untouched.
* **Full refresh.** `stg_flight_ops` is truncated on every run, so
  `make extract` is idempotent.
* **Row counts are asserted.** Rows read from the OLTP must equal rows landed
  in staging, or the step fails.
* Reads the `v_flight_ops_export` view, which concatenates `service_date`
  with the raw clock string so the staging contract carries the date inside
  `departure_time` / `arrival_time`.
* Every run stamps a `batch_id` for lineage.

## Commands
```bash
make extract
```
