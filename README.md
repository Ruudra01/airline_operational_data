# Airline Data Platform

End-to-end airline operations data platform: a 3NF OLTP source, a raw staging
zone, a validated ELT pipeline and a Kimball star schema — all runnable
locally with `docker compose` and one `make` chain.

```
PostgreSQL (OLTP, 3NF)          PostgreSQL (Warehouse, star)
┌────────────────────┐          ┌──────────────────────────┐
│ airport            │          │ dim_airport  ◄──┐        │
│ airline            │          │ dim_date        │ 2 FKs  │
│ flight             │  extract │ dim_time        │        │
│ flight_instance    │ ───────► │ dim_airline     │        │
└────────────────────┘          │ fact_flight ────┘        │
        │                       └──────────────────────────┘
        │  stg_flight_ops (raw TEXT)          ▲
        └──────── transform: validate ────────┘
                  standardise / dedupe
```

---

## Quick start

```bash
git clone <this repo> && cd airline_operational_data

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make setup      # docker compose up + wait for Postgres + apply all DDL
make seed       # 10 mock DL857 flight instances into the OLTP
make extract    # OLTP  -> stg_flight_ops   (raw, no cleaning)
make transform  # staging -> clean DataFrame (validate/standardise/dedupe)
make load       # clean DataFrame -> star schema (dims first, then fact)
make test       # pytest unit tests + warehouse integrity SQL
```

Or in one line:

```bash
make setup && make seed && make extract && make transform && make load && make test
```

Inspect either database in the browser at **http://localhost:8080** (Adminer;
switch the *Server* field between `postgres_oltp` and `postgres_dw`), or drop
into a shell with `make psql-oltp` / `make psql-dw`.

`make clean` tears down containers, volumes and generated CSVs.

### Prerequisites
Docker (with Compose v2), Python 3.10+, GNU Make. Nothing else — `psql` is not
required on the host, migrations run through SQLAlchemy.

### All Make targets
| Target | Does |
|---|---|
| `make help` | List every target |
| `make setup` | `.env` + containers + wait + migrate |
| `make migrate` | Apply OLTP migrations, staging DDL, warehouse DDL (idempotent) |
| `make seed` | Load the 10 mock flight instances |
| `make extract` | OLTP → `stg_flight_ops` |
| `make transform` | Staging → `data/clean_flights.csv` + `data/rejects.csv` |
| `make load` | Star-schema load |
| `make test` | `test-unit` + `test-integrity` |
| `make deps` | `pip install -r requirements.txt` |
| `make logs` / `psql-oltp` / `psql-dw` | Inspection |
| `make clean` | Tear everything down |

---

## The 7 roles

Each folder has exactly one owner and a `README.md` restating the contract.

| # | Role | Folder | Owns |
|---|---|---|---|
| **1** | OLTP Data Modeller | `oltp/` | 3NF schema, Flyway-style migrations, mock data generator |
| **2** | Extraction Engineer | `elt/extract/`, `elt/staging/` | Raw landing zone DDL, OLTP → staging copy |
| **3** | Transformation Engineer | `elt/transform/` | Validation rules, AM/PM standardisation, duration maths, de-duplication |
| **4** | Warehouse Modeller | `warehouse/` | Star-schema DDL, dimension + fact loaders, load order |
| **5** | QA / Data Quality | `tests/` | Pytest unit tests, warehouse referential-integrity SQL |
| **6** | BI / Analytics | `bi/` | Marts and analytical queries over the star |
| **7** | Platform / DevOps | `scripts/` | Docker Compose, Makefile, `config.py`, migration runner, CI |

Interfaces between roles are data contracts, not code imports:
Person 1 → `flight_instance`; Person 2 → `stg_flight_ops`; Person 3 → a clean
DataFrame; Person 4 → `fact_flight` + dims; Persons 5 and 6 read those.

---

## Repository layout

```
.
├── docker-compose.yml            postgres_oltp, postgres_dw, adminer
├── .env.example                  every credential and knob (copy to .env)
├── Makefile                      setup/seed/extract/transform/load/test/clean
├── requirements.txt
├── config.py                     centralised env-driven connection manager
├── conftest.py                   puts the repo root on sys.path for pytest
│
├── oltp/                         [Person 1]
│   ├── migrations/V1__initial_schema.sql
│   └── seeds/generate_mock_data.py
│
├── elt/
│   ├── staging/create_staging.sql        [Person 2]
│   ├── extract/extract_to_staging.py     [Person 2]
│   └── transform/                        [Person 3]
│       ├── validation.py
│       └── main.py
│
├── warehouse/                    [Person 4]
│   ├── ddl/{dim_airline,dim_airport,dim_date,dim_time,fact_flight}.sql
│   └── load/load_warehouse.py
│
├── tests/                        [Person 5]
│   ├── test_validation.py
│   └── test_integrity.sql
│
├── bi/marts/route_analytics.sql  [Person 6]
├── scripts/                      [Person 7]
│   ├── wait_for_db.py
│   ├── migrate.py
│   └── check_integrity.py
└── .github/workflows/ci.yml      [Person 7]
```

---

## How the role-playing airport dimension works

A flight touches two airports, but an airport is one *kind* of thing. So the
warehouse has **one physical `dim_airport` table**, and `fact_flight`
references it **twice**:

```sql
CREATE TABLE fact_flight (
    ...
    departure_airport_key INTEGER NOT NULL REFERENCES dim_airport (airport_key),
    arrival_airport_key   INTEGER NOT NULL REFERENCES dim_airport (airport_key),
    ...
);
```

Both foreign keys point at the same primary key. The *role* is carried by the
column name on the fact, not by a duplicated table.

**Why not two tables?** Because `dim_departure_airport` and
`dim_arrival_airport` would store Detroit twice — and the day someone fixes a
typo in one of them, "Detroit → Detroit" round trips stop reconciling. One
table means one truth: a new attribute (timezone, hub flag, elevation) is
added once, and the dimension is *conformed*, so a future `fact_booking` or
`fact_delay` joins the very same table.

**How you query it.** Join it twice with different aliases:

```sql
SELECT dep.city AS departure_city,
       arr.city AS arrival_city,
       round(avg(f.duration_minutes), 1) AS avg_duration_minutes
FROM fact_flight f
JOIN dim_airport dep ON dep.airport_key = f.departure_airport_key  -- role 1
JOIN dim_airport arr ON arr.airport_key = f.arrival_airport_key    -- role 2
GROUP BY 1, 2;
```

Two convenience views, `dim_departure_airport` and `dim_arrival_airport`,
pre-alias every column (`departure_city`, `arrival_city`, …) so BI tools that
cannot express a self-join still get unambiguous names. `dim_time` plays the
same two roles for `departure_time_key` and `arrival_time_key`.

---

## Data quality: what the pipeline refuses to do

### `'NY'` is rejected, not resolved
```python
VALID_AIRPORTS = ['DTW', 'JFK', 'SFO']
```
`NY` is a **metro code** covering JFK, LGA and EWR. Converting it to `JFK`
would invent a fact the source never stated, and every route metric built on
it would be quietly wrong. So `reject_ambiguous()` raises
`AmbiguousAirportError`, the row lands in `stg_flight_ops_rejects` with its
reason, and the load continues without it. Anything outside `VALID_AIRPORTS`
raises `UnknownAirportError` for the same reason.

### AM/PM is standardised to 24-hour
`'10:00 AM'` → `'10:00'`, `'1:00 PM'` → `'13:00'`, and the two traps handled
explicitly: `'12:00 AM'` → `'00:00'`, `'12:00 PM'` → `'12:00'`.

### Duration is recomputed and cross-checked
The pipeline never trusts the source's `duration` string. It recomputes block
time from the standardised departure and arrival (adding a day when the
arrival clock time is earlier — the overnight case) and compares against the
reported value. Drift beyond `DURATION_TOLERANCE_MINUTES` (default `0`) is a
rejection, not a warning.

### Duplicates die by `row_number()`
```sql
row_number() OVER (
    PARTITION BY flight_no, dep_code, arr_code, departure_time, arrival_time
    ORDER BY stg_id
) AS dedupe_rank
```
Rank 1 survives; `stg_id` makes the tie-break deterministic. The fact table's
`fact_flight_grain` unique key is the second line of defence.

### The seeded data exercises all four
The 10 mock rows are 7 clean + 3 rejected:

| Row | Defect | Caught by |
|---|---|---|
| 3 | exact duplicate of row 1 | `row_number()` |
| 4 | departure station `NY` | `reject_ambiguous()` |
| 10 | reported `2h 45m` vs 1h 45m on the clock | `validate_duration()` |

Row 5 (`11:30 PM` → `3:00 AM`) is *not* a defect: it loads as 210 minutes with
`crossed_midnight = TRUE`.

---

## Configuration

Everything is environment-driven; **no module builds a connection string**.
All database access goes through `config.oltp_engine()` / `config.dw_engine()`,
which read `OLTP_DB_URL` / `DW_DB_URL` via `os.getenv`. That is what lets CI
point the identical code at service containers without editing a line.

| Variable | Default | Meaning |
|---|---|---|
| `OLTP_DB_URL` | `postgresql+psycopg2://airline:airline@localhost:5432/airline_oltp` | 3NF source |
| `DW_DB_URL` | `postgresql+psycopg2://airline:airline@localhost:5433/airline_dw` | Star schema |
| `SERVICE_DATE` | `2026-09-09` | Fallback date when a staging timestamp has no date part |
| `DURATION_TOLERANCE_MINUTES` | `0` | Allowed clock-vs-reported drift |
| `STAGING_TARGET` | `oltp` | Which database holds `stg_flight_ops` |
| `DATA_DIR` | `data` | Where `make transform` writes its CSVs |
| `LOG_LEVEL` | `INFO` | |

`make setup` creates `.env` from `.env.example` if it is missing.

## Migrations

`scripts/migrate.py` is a Flyway-style runner: `*.sql` applied in filename
order, one transaction per file, recorded in `schema_version` with a checksum.
Re-running applies nothing. **Editing an already-applied migration is a hard
error** — add `V2__…sql` instead.

Warehouse DDL is un-versioned and ordered alphabetically, which puts every
`dim_*` file before `fact_flight.sql`, so the FK targets exist first.

## CI

`.github/workflows/ci.yml` runs on every push and PR. It starts the same two
Postgres 16 images as service containers, then runs
`migrate → seed → extract → transform → load → test` and builds the BI mart,
uploading `data/*.csv` as artifacts. A green build proves the migrations
apply, the transform rejects what it should, the star loads and referential
integrity holds.

## Extending it

* New airport → add to `airport` (OLTP) **and** `VALID_AIRPORTS`. The
  allow-list is deliberately explicit: an unknown code must fail loudly.
* Cross-timezone flights → add a timezone column to `dim_airport` and convert
  to UTC in `compute_duration_minutes()` (marked with a `ponytail:` comment).
* SCD2 on `dim_airport` → add `valid_from` / `valid_to` / `is_current` and
  change the upsert; `fact_flight` already carries surrogate keys, so nothing
  else moves.
* New fact (delays, bookings) → reuse `dim_airport`, `dim_date`, `dim_time`,
  `dim_airline` unchanged. That is the payoff of conformed dimensions.
