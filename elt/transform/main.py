#!/usr/bin/env python3
"""Transform stage orchestration (owner: Person 3, Transformation Engineer).

Pipeline, in order:

    1. READ         stg_flight_ops with a row_number() window that ranks
                    duplicate legs.
    2. DEDUPLICATE  keep rn = 1 per (flight_no, dep, arr, dep_time, arr_time).
    3. VALIDATE     reject ambiguous station codes ('NY' stays rejected).
    4. STANDARDISE  '10:00 AM' -> '10:00', '1:00 PM' -> '13:00'.
    5. MEASURE      duration in minutes from the standardised timestamps,
                    cross-checked against the source-reported string.
    6. RETURN       one clean DataFrame ready for the star-schema loader.

Rejected rows are never dropped silently: they are returned as a second
DataFrame, written to `data/rejects.csv` and persisted to
`stg_flight_ops_rejects`.

Run:  make transform
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

import config
from elt.transform import validation
from elt.transform.validation import (
    TimeFormatError,
    ValidationError,
    airline_code_from_flight_no,
    reject_ambiguous,
    validate_duration,
    validate_flight_no,
)

LOG = logging.getLogger("transform")

# --------------------------------------------------------------------------
# 1. Read staging, ranking duplicates with row_number()
# --------------------------------------------------------------------------
# The dedupe grain is the natural key of an operated leg. stg_id breaks ties
# deterministically (earliest landed row wins), which keeps the pipeline
# reproducible across re-runs.
READ_STAGING_SQL = """
WITH ranked AS (
    SELECT s.stg_id,
           s.dep_code,
           s.arr_code,
           s.arrival_time,
           s.departure_time,
           s.duration,
           s.flight_no,
           s.source_system,
           s.source_row_id,
           row_number() OVER (
               PARTITION BY upper(btrim(s.flight_no)),
                            upper(btrim(s.dep_code)),
                            upper(btrim(s.arr_code)),
                            btrim(s.departure_time),
                            btrim(s.arrival_time)
               ORDER BY s.stg_id
           ) AS dedupe_rank
    FROM stg_flight_ops s
)
SELECT *
FROM ranked
ORDER BY stg_id
"""

# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------
# Accepts '10:00 AM', '10:00', '22:00', '2026-09-09 1:00 PM', '2026-09-09T13:00:00'
_TIMESTAMP_RE = re.compile(
    r"""^\s*
        (?:(?P<date>\d{4}-\d{2}-\d{2})[\sT]+)?      # optional date part
        (?P<hour>\d{1,2}):(?P<minute>\d{2})          # hh:mm
        (?::\d{2})?                                  # optional :ss
        \s*
        (?P<meridiem>[AaPp]\.?\s?[Mm]\.?)?           # optional AM/PM
        \s*$""",
    re.VERBOSE,
)

# '1h 45m', '1 h 45 min', '45m', '2h'
_DURATION_HM_RE = re.compile(
    r"^\s*(?:(?P<hours>\d+)\s*h(?:ours?|rs?)?)?\s*"
    r"(?:(?P<minutes>\d+)\s*m(?:in(?:ute)?s?)?)?\s*$",
    re.IGNORECASE,
)
# '1:45'
_DURATION_COLON_RE = re.compile(r"^\s*(?P<hours>\d{1,3}):(?P<minutes>\d{2})\s*$")
# '105'
_DURATION_INT_RE = re.compile(r"^\s*(?P<minutes>\d+)\s*$")


def _parse_clock(raw) -> tuple[date | None, int, int]:
    """Split a timestamp string into (date | None, hour_24, minute)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        raise TimeFormatError("timestamp is missing")

    match = _TIMESTAMP_RE.match(str(raw))
    if not match:
        raise TimeFormatError(f"cannot parse timestamp {raw!r}")

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    meridiem = match.group("meridiem")

    if not 0 <= minute <= 59:
        raise TimeFormatError(f"minute out of range in {raw!r}")

    if meridiem:
        # 12-hour clock: 12 AM -> 00, 12 PM -> 12, 1 PM -> 13.
        if not 1 <= hour <= 12:
            raise TimeFormatError(f"hour {hour} invalid for a 12-hour clock: {raw!r}")
        is_pm = meridiem.strip().lower().replace(".", "").replace(" ", "").startswith("p")
        hour = (hour % 12) + (12 if is_pm else 0)
    elif not 0 <= hour <= 23:
        raise TimeFormatError(f"hour {hour} out of range in {raw!r}")

    date_part = (
        datetime.strptime(match.group("date"), "%Y-%m-%d").date()
        if match.group("date")
        else None
    )
    return date_part, hour, minute


def standardize_time(raw) -> str:
    """12-hour clock -> zero-padded 24-hour 'HH:MM'.

    >>> standardize_time("10:00 AM")
    '10:00'
    >>> standardize_time("1:00 PM")
    '13:00'
    >>> standardize_time("2026-09-09 12:05 AM")
    '00:05'
    """
    _, hour, minute = _parse_clock(raw)
    return f"{hour:02d}:{minute:02d}"


def to_timestamp(raw, default_date: date | None = None) -> datetime:
    """Parse to a naive datetime, falling back to `default_date` when the
    string carries no date part."""
    date_part, hour, minute = _parse_clock(raw)
    if date_part is None:
        date_part = default_date or datetime.strptime(
            config.DEFAULT_SERVICE_DATE, "%Y-%m-%d"
        ).date()
    return datetime(date_part.year, date_part.month, date_part.day, hour, minute)


def parse_duration_minutes(raw) -> int | None:
    """Source-reported duration -> minutes. None when nothing was reported.

    >>> parse_duration_minutes("1h 45m")
    105
    >>> parse_duration_minutes("3:30")
    210
    >>> parse_duration_minutes("95")
    95
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text_value = str(raw).strip()
    if not text_value:
        return None

    for pattern in (_DURATION_COLON_RE, _DURATION_INT_RE, _DURATION_HM_RE):
        match = pattern.match(text_value)
        if not match:
            continue
        groups = match.groupdict()
        hours = int(groups.get("hours") or 0)
        minutes = int(groups.get("minutes") or 0)
        if pattern is _DURATION_HM_RE and not (groups.get("hours") or groups.get("minutes")):
            continue  # empty match - keep looking
        return hours * 60 + minutes

    raise ValidationError(f"cannot parse duration {raw!r}")


def compute_duration_minutes(departure: datetime, arrival: datetime) -> tuple[int, bool]:
    """Elapsed minutes between departure and arrival.

    Returns (minutes, crossed_midnight). An arrival clock time earlier than
    the departure means the leg landed the next day, so a day is added.

    ponytail: block time is computed on naive local clock times, which is
    correct for the sample data (single-timezone legs). Add a timezone per
    airport to dim_airport and convert to UTC here if the platform ever
    ingests real cross-timezone schedules.
    """
    crossed_midnight = arrival < departure
    if crossed_midnight:
        arrival = arrival + timedelta(days=1)
    return int((arrival - departure).total_seconds() // 60), crossed_midnight


# --------------------------------------------------------------------------
# Stage functions
# --------------------------------------------------------------------------
def read_staging() -> pd.DataFrame:
    """Read stg_flight_ops with duplicate ranking applied."""
    with config.oltp_engine().connect() as conn:
        df = pd.read_sql(text(READ_STAGING_SQL), conn)
    LOG.info("read %d staging row(s)", len(df))
    return df


def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into (survivors, duplicates) on the row_number() rank."""
    duplicates = df[df["dedupe_rank"] > 1].copy()
    survivors = df[df["dedupe_rank"] == 1].copy()
    if not duplicates.empty:
        LOG.warning(
            "dropped %d duplicate leg(s): %s",
            len(duplicates),
            ", ".join(
                f"{r.flight_no} {r.dep_code}->{r.arr_code} @ {r.departure_time}"
                for r in duplicates.itertuples()
            ),
        )
    duplicates["reject_reason"] = "duplicate leg (row_number() rank > 1)"
    return survivors, duplicates


def transform_row(row: pd.Series) -> dict:
    """Validate + standardise + measure one staging row. Raises on rejection."""
    codes = reject_ambiguous(row)                     # 'NY' dies here
    flight_no = validate_flight_no(row["flight_no"])

    departure_at = to_timestamp(row["departure_time"])
    arrival_at = to_timestamp(row["arrival_time"])

    computed, crossed_midnight = compute_duration_minutes(departure_at, arrival_at)
    reported = parse_duration_minutes(row["duration"])
    duration_minutes = validate_duration(
        computed,
        reported,
        tolerance_minutes=config.DURATION_TOLERANCE_MINUTES,
        flight_no=flight_no,
    )

    return {
        "stg_id": int(row["stg_id"]),
        "flight_no": flight_no,
        "airline_code": airline_code_from_flight_no(flight_no),
        "dep_code": codes["dep_code"],
        "arr_code": codes["arr_code"],
        "service_date": departure_at.date(),
        "departure_at": departure_at,
        "arrival_at": arrival_at + (timedelta(days=1) if crossed_midnight else timedelta()),
        "departure_time_24h": f"{departure_at:%H:%M}",
        "arrival_time_24h": f"{arrival_at:%H:%M}",
        # Warehouse surrogate keys, derived here so the loader stays dumb.
        "date_key": int(f"{departure_at:%Y%m%d}"),
        "departure_time_key": departure_at.hour * 100 + departure_at.minute,
        "arrival_time_key": arrival_at.hour * 100 + arrival_at.minute,
        "duration_minutes": duration_minutes,
        "reported_duration_minutes": reported,
        "crossed_midnight": crossed_midnight,
        "source_system": row.get("source_system"),
        "source_row_id": row.get("source_row_id"),
    }


def validate_and_standardize(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply transform_row to every survivor, collecting rejects."""
    clean_rows: list[dict] = []
    rejects: list[dict] = []

    for _, row in df.iterrows():
        try:
            clean_rows.append(transform_row(row))
        except ValidationError as exc:
            LOG.warning("rejected stg_id=%s: %s", row["stg_id"], exc)
            reject = row.to_dict()
            reject["reject_reason"] = f"{type(exc).__name__}: {exc}"
            rejects.append(reject)

    clean = pd.DataFrame(clean_rows)
    return clean, pd.DataFrame(rejects)


def persist_rejects(rejects: pd.DataFrame) -> None:
    """Write rejects to stg_flight_ops_rejects for operational triage."""
    if rejects.empty:
        return
    columns = [
        "stg_id", "dep_code", "arr_code", "arrival_time",
        "departure_time", "duration", "flight_no", "reject_reason",
    ]
    payload = rejects.reindex(columns=columns)
    with config.oltp_engine().begin() as conn:
        payload.to_sql("stg_flight_ops_rejects", conn, if_exists="append", index=False)
    LOG.info("persisted %d reject(s) to stg_flight_ops_rejects", len(payload))


def build_clean_dataframe(persist: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The transform stage, end to end.

    Returns (clean, rejects). This is the function the warehouse loader calls.
    """
    staged = read_staging()
    if staged.empty:
        raise RuntimeError("stg_flight_ops is empty - run `make extract` first")

    survivors, duplicates = deduplicate(staged)
    clean, invalid = validate_and_standardize(survivors)
    rejects = pd.concat([duplicates, invalid], ignore_index=True)

    if persist:
        persist_rejects(rejects)

    LOG.info(
        "transform complete: %d clean, %d rejected (%d duplicate, %d invalid)",
        len(clean), len(rejects), len(duplicates), len(invalid),
    )
    return clean, rejects


def main() -> int:
    config.configure_logging()
    clean, rejects = build_clean_dataframe(persist=True)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean_path = config.DATA_DIR / "clean_flights.csv"
    clean.to_csv(clean_path, index=False)
    LOG.info("wrote %s", clean_path)

    if not rejects.empty:
        reject_path = config.DATA_DIR / "rejects.csv"
        rejects.to_csv(reject_path, index=False)
        LOG.info("wrote %s", reject_path)

    print(
        clean[
            ["flight_no", "dep_code", "arr_code", "service_date",
             "departure_time_24h", "arrival_time_24h", "duration_minutes"]
        ].to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
