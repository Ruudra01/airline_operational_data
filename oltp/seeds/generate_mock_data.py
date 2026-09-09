#!/usr/bin/env python3
"""Seed the OLTP database with mock DL857 operations (owner: Person 1).

Mirrors the assignment sample data: Delta 857 flying DTW -> JFK and
JFK -> SFO on Sep 9, with 12-hour clock times, plus the three defects the
pipeline must handle:

    * row 3  - an exact duplicate leg          -> removed by row_number()
    * row 4  - departure station 'NY'          -> rejected as ambiguous
    * row 10 - duration_raw disagrees with the
               departure/arrival clock times   -> rejected by validation

Exactly 10 flight_instance rows are produced. Re-running truncates and
reloads, so `make seed` is idempotent.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

import config

LOG = logging.getLogger("seed")

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
# 'NY' is intentionally present and flagged: the operational feed really does
# emit metro codes. It must NEVER be silently resolved to JFK.
AIRPORTS: list[dict] = [
    {"code": "DTW", "name": "Detroit Metropolitan Wayne County",
     "city": "Detroit", "state": "MI", "country": "USA", "is_ambiguous": False},
    {"code": "JFK", "name": "John F. Kennedy International",
     "city": "New York", "state": "NY", "country": "USA", "is_ambiguous": False},
    {"code": "SFO", "name": "San Francisco International",
     "city": "San Francisco", "state": "CA", "country": "USA", "is_ambiguous": False},
    {"code": "NY", "name": "New York (metro area - AMBIGUOUS)",
     "city": "New York", "state": "NY", "country": "USA", "is_ambiguous": True},
]

AIRLINES: list[dict] = [
    {"iata_code": "DL", "icao_code": "DAL", "name": "Delta Air Lines", "country": "USA"},
]

# Route definitions (airline, number, from, to)
FLIGHTS: list[dict] = [
    {"iata_code": "DL", "flight_number": "857", "dep": "DTW", "arr": "JFK"},
    {"iata_code": "DL", "flight_number": "857", "dep": "JFK", "arr": "SFO"},
    # The dirty route: the feed reported the origin as the metro code 'NY'.
    {"iata_code": "DL", "flight_number": "857", "dep": "NY", "arr": "SFO"},
]

# 10 operated legs. `duration_raw` is what the source system claims; the
# transform recomputes it from the clock times and compares.
INSTANCES: list[dict] = [
    # 1 - the assignment's first leg
    {"dep": "DTW", "arr": "JFK", "service_date": date(2026, 9, 9),
     "departure_time_local": "10:00 AM", "arrival_time_local": "11:45 AM",
     "duration_raw": "1h 45m", "tail_number": "N301DN"},
    # 2 - the assignment's second leg (afternoon, PM times)
    {"dep": "JFK", "arr": "SFO", "service_date": date(2026, 9, 9),
     "departure_time_local": "1:00 PM", "arrival_time_local": "4:30 PM",
     "duration_raw": "3h 30m", "tail_number": "N301DN"},
    # 3 - EXACT DUPLICATE of row 1 (feed replay) -> dedupe must drop it
    {"dep": "DTW", "arr": "JFK", "service_date": date(2026, 9, 9),
     "departure_time_local": "10:00 AM", "arrival_time_local": "11:45 AM",
     "duration_raw": "1h 45m", "tail_number": "N301DN"},
    # 4 - AMBIGUOUS origin 'NY' -> validation must reject, not guess JFK
    {"dep": "NY", "arr": "SFO", "service_date": date(2026, 9, 9),
     "departure_time_local": "1:00 PM", "arrival_time_local": "4:30 PM",
     "duration_raw": "3h 30m", "tail_number": "N302DN"},
    # 5 - overnight leg: arrival clock time is EARLIER than departure
    {"dep": "JFK", "arr": "SFO", "service_date": date(2026, 9, 9),
     "departure_time_local": "11:30 PM", "arrival_time_local": "3:00 AM",
     "duration_raw": "3h 30m", "tail_number": "N303DN"},
    # 6-9 - clean repeats on the following days
    {"dep": "DTW", "arr": "JFK", "service_date": date(2026, 9, 10),
     "departure_time_local": "10:00 AM", "arrival_time_local": "11:45 AM",
     "duration_raw": "1h 45m", "tail_number": "N301DN"},
    {"dep": "JFK", "arr": "SFO", "service_date": date(2026, 9, 10),
     "departure_time_local": "1:00 PM", "arrival_time_local": "4:30 PM",
     "duration_raw": "3h 30m", "tail_number": "N301DN"},
    {"dep": "DTW", "arr": "JFK", "service_date": date(2026, 9, 11),
     "departure_time_local": "10:15 AM", "arrival_time_local": "12:05 PM",
     "duration_raw": "1h 50m", "tail_number": "N304DN"},
    {"dep": "JFK", "arr": "SFO", "service_date": date(2026, 9, 11),
     "departure_time_local": "12:45 PM", "arrival_time_local": "4:20 PM",
     "duration_raw": "3h 35m", "tail_number": "N304DN"},
    # 10 - duration_raw says 2h 45m but the clock says 1h 45m -> reject
    {"dep": "DTW", "arr": "JFK", "service_date": date(2026, 9, 12),
     "departure_time_local": "10:00 AM", "arrival_time_local": "11:45 AM",
     "duration_raw": "2h 45m", "tail_number": "N305DN"},
]


def seed() -> None:
    engine = config.oltp_engine()

    with engine.begin() as conn:
        # Reload from scratch; RESTART IDENTITY keeps surrogate keys stable
        # across runs so the seeded data is byte-for-byte reproducible.
        conn.execute(
            text("TRUNCATE flight_instance, flight, airline, airport RESTART IDENTITY CASCADE")
        )

        conn.execute(
            text(
                """
                INSERT INTO airport (code, name, city, state, country, is_ambiguous)
                VALUES (:code, :name, :city, :state, :country, :is_ambiguous)
                """
            ),
            AIRPORTS,
        )
        conn.execute(
            text(
                """
                INSERT INTO airline (iata_code, icao_code, name, country)
                VALUES (:iata_code, :icao_code, :name, :country)
                """
            ),
            AIRLINES,
        )

        airport_ids = dict(conn.execute(text("SELECT code, airport_id FROM airport")).all())
        airline_ids = dict(conn.execute(text("SELECT iata_code, airline_id FROM airline")).all())

        conn.execute(
            text(
                """
                INSERT INTO flight
                    (airline_id, flight_number, departure_airport_id, arrival_airport_id)
                VALUES (:airline_id, :flight_number, :dep_id, :arr_id)
                """
            ),
            [
                {
                    "airline_id": airline_ids[f["iata_code"]],
                    "flight_number": f["flight_number"],
                    "dep_id": airport_ids[f["dep"]],
                    "arr_id": airport_ids[f["arr"]],
                }
                for f in FLIGHTS
            ],
        )

        flight_ids = {
            (row.iata_code, row.flight_number, row.dep_code, row.arr_code): row.flight_id
            for row in conn.execute(
                text(
                    """
                    SELECT f.flight_id, al.iata_code, f.flight_number,
                           dep.code AS dep_code, arr.code AS arr_code
                    FROM flight f
                    JOIN airline al  ON al.airline_id  = f.airline_id
                    JOIN airport dep ON dep.airport_id = f.departure_airport_id
                    JOIN airport arr ON arr.airport_id = f.arrival_airport_id
                    """
                )
            ).all()
        }

        conn.execute(
            text(
                """
                INSERT INTO flight_instance
                    (flight_id, service_date, departure_time_local,
                     arrival_time_local, duration_raw, tail_number, source_system)
                VALUES (:flight_id, :service_date, :departure_time_local,
                        :arrival_time_local, :duration_raw, :tail_number, 'ops_feed')
                """
            ),
            [
                {
                    "flight_id": flight_ids[("DL", "857", i["dep"], i["arr"])],
                    "service_date": i["service_date"],
                    "departure_time_local": i["departure_time_local"],
                    "arrival_time_local": i["arrival_time_local"],
                    "duration_raw": i["duration_raw"],
                    "tail_number": i["tail_number"],
                }
                for i in INSTANCES
            ],
        )

    with engine.connect() as conn:
        counts = {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("airport", "airline", "flight", "flight_instance")
        }
    LOG.info("seeded: %s", counts)
    assert counts["flight_instance"] == 10, counts  # the assignment asks for 10


if __name__ == "__main__":
    config.configure_logging()
    seed()
