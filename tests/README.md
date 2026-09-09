# `tests/` — Owner: **Person 5, QA / Data Quality**

Two layers, both wired into `make test` and therefore into CI.

## 1. `test_validation.py` — unit tests, no database
Fast pre-commit gate. Covers:
* `'NY'` raises `AmbiguousAirportError`; `'DTW'` passes. *(the headline test)*
* Every metro code in `AMBIGUOUS_AIRPORTS` is rejected.
* Codes outside `VALID_AIRPORTS` raise `UnknownAirportError`.
* AM/PM → 24-hour, including the `12:00 AM` / `12:00 PM` traps.
* Duration parsing (`1h 45m`, `1:45`, `105`), overnight legs, and the
  clock-vs-reported cross-check.
* Flight-number normalisation and carrier derivation.

```bash
pytest tests/test_validation.py -q
```

## 2. `test_integrity.sql` — warehouse checks, post-load
Every statement returns `(check_name, failure_count)`.
`scripts/check_integrity.py` runs them and exits non-zero on any failure.

Checks: all six fact foreign keys (**including both role-playing airport
keys**), no NULL keys, unique grain, positive durations, durations matching
the reported value, departure ≠ arrival airport, no ambiguous codes in
`dim_airport`, `dim_time` completeness, smart-key consistency, and that the
fact table is not empty.

```bash
make test-integrity
```

## Why both
The unit tests prove the *rules* are right without infrastructure. The SQL
checks prove the *loaded warehouse* obeys them. A rule can be correct and
still be skipped by a loader bug; only the second layer catches that.

`great-expectations` is in `requirements.txt` for the next iteration
(profiling and expectation suites over `stg_flight_ops`); the current checks
are plain SQL because plain SQL is enough for this grain.
