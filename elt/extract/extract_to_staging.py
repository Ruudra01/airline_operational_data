#!/usr/bin/env python3
"""Extract: OLTP -> stg_flight_ops (owner: Person 2, Extraction Engineer).

A deliberately dumb copy. It performs NO cleaning, NO type casting and NO
filtering: the ambiguous 'NY' station, the duplicated leg and the wrong
duration all land in staging exactly as the source system holds them, so
that the transform layer can report on them.

The only shaping done here is concatenating `service_date` with the raw
12-hour clock string, because the staging contract carries the date inside
`departure_time` / `arrival_time`.

Run:  make extract
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

import config

LOG = logging.getLogger("extract")

#: Column order of the staging contract (audit columns appended).
STAGING_COLUMNS = [
    "dep_code",
    "arr_code",
    "arrival_time",
    "departure_time",
    "duration",
    "flight_no",
    "source_system",
    "source_row_id",
    "batch_id",
]

# Reads the OLTP export view created by V1__initial_schema.sql. Everything
# comes back as text - staging is untyped on purpose.
EXTRACT_SQL = """
SELECT dep_code,
       arr_code,
       arrival_time,
       departure_time,
       duration,
       flight_no,
       source_system,
       source_row_id
FROM v_flight_ops_export
ORDER BY source_row_id
"""


def read_oltp() -> pd.DataFrame:
    """Pull the operational feed out of the 3NF database."""
    with config.oltp_engine().connect() as conn:
        df = pd.read_sql(text(EXTRACT_SQL), conn)
    LOG.info("read %d row(s) from OLTP", len(df))
    return df


def write_staging(df: pd.DataFrame, *, truncate: bool = True) -> str:
    """Land `df` in stg_flight_ops. Returns the batch id."""
    batch_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    df = df.copy()
    df["batch_id"] = batch_id
    df = df[STAGING_COLUMNS]

    engine = config.dw_engine() if _staging_lives_in_dw() else config.oltp_engine()
    with engine.begin() as conn:
        if truncate:
            # Full refresh: the pipeline is idempotent by construction, which
            # matters far more here than incremental cleverness.
            conn.execute(text("TRUNCATE stg_flight_ops RESTART IDENTITY"))
            conn.execute(text("TRUNCATE stg_flight_ops_rejects RESTART IDENTITY"))
        df.to_sql(
            "stg_flight_ops",
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )
        landed = conn.execute(text("SELECT count(*) FROM stg_flight_ops")).scalar_one()

    LOG.info("landed %d row(s) in stg_flight_ops (batch %s)", landed, batch_id)
    if landed != len(df):
        raise RuntimeError(f"row count mismatch: read {len(df)}, landed {landed}")
    return batch_id


def _staging_lives_in_dw() -> bool:
    """Staging sits next to the OLTP by default (see elt/staging/README.md)."""
    return config.env("STAGING_TARGET", "oltp").lower() in {"dw", "warehouse"}


def main() -> int:
    config.configure_logging()
    df = read_oltp()
    if df.empty:
        LOG.error("OLTP returned no rows - did you run `make seed`?")
        return 1
    write_staging(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
