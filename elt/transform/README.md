# `elt/transform/` — Owner: **Person 3, Transformation Engineer**

Where the data quality rules live. Input: `stg_flight_ops`. Output: one clean
`pandas.DataFrame` plus a rejects DataFrame.

## Order of operations
1. **Read** staging with a `row_number()` window ranking duplicate legs.
2. **Deduplicate** — keep rank 1 per
   `(flight_no, dep_code, arr_code, departure_time, arrival_time)`.
3. **Validate** — `reject_ambiguous()` on every row.
4. **Standardise** — `'10:00 AM'` → `'10:00'`, `'1:00 PM'` → `'13:00'`.
5. **Measure** — duration in minutes from the standardised timestamps,
   cross-checked against the source-reported `duration` string.
6. **Return** a DataFrame carrying the warehouse smart keys (`date_key`,
   `departure_time_key`, `arrival_time_key`) already derived.

## The rule that matters
```python
VALID_AIRPORTS = ['DTW', 'JFK', 'SFO']
```
`'NY'` raises `AmbiguousAirportError`. It is **never** mapped to `JFK`.
`NY` is a metro code covering JFK, LGA and EWR; picking one would invent a
fact the source never stated and would corrupt every route metric in the
warehouse. Same for any code outside `VALID_AIRPORTS`
(`UnknownAirportError`).

## Rejections are visible, never silent
Every refused row goes to the returned rejects DataFrame, to
`data/rejects.csv`, and to `stg_flight_ops_rejects` with its reason.

With the seeded data, 10 staged rows become **7 clean / 3 rejected**:

| Reason | Rows |
|---|---|
| duplicate leg (`row_number()` rank > 1) | 1 |
| ambiguous station code `NY` | 1 |
| reported duration disagrees with clock times | 1 |

## Edge cases handled
* `12:00 AM` → `00:00`, `12:00 PM` → `12:00`.
* Overnight legs (`11:30 PM` → `3:00 AM`) roll the arrival to the next day
  and set `crossed_midnight`.
* Duration formats `1h 45m`, `1:45`, `105`, `1 hour 45 min`.

## Commands
```bash
make transform             # writes data/clean_flights.csv and data/rejects.csv
pytest tests/test_validation.py
```
