# `scripts/` — Owner: **Person 7, Platform / DevOps**

Infrastructure and plumbing. Nothing here contains business logic.

| Script | Job |
|---|---|
| `wait_for_db.py` | Blocks until both databases accept connections. `docker compose up -d` returns before Postgres finishes `initdb`. |
| `migrate.py` | Flyway-style SQL runner: applies `*.sql` in filename order, one transaction per file, recorded in `schema_version` (version, checksum, applied_at, success). Re-running is a no-op; editing an applied file is a hard error. |
| `check_integrity.py` | Runs `tests/test_integrity.sql` and exits non-zero on any `failure_count > 0`. |

Person 7 also owns `docker-compose.yml`, the `Makefile`, `config.py`,
`.env.example` and `.github/workflows/ci.yml`.

## Connection rules
No module in this repo builds a connection string. Everything calls
`config.oltp_engine()` / `config.dw_engine()`, and those read only
`OLTP_DB_URL` / `DW_DB_URL` from the environment. That is what lets CI point
the same code at service containers with no edits.

## Usage
```bash
python scripts/wait_for_db.py --db oltp --timeout 60
python scripts/migrate.py --db dw --dir warehouse/ddl
python scripts/check_integrity.py tests/test_integrity.sql
```
