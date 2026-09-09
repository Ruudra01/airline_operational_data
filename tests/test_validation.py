"""Unit tests for the transform layer (owner: Person 5, QA / Data Quality).

These run without any database, so `pytest tests/test_validation.py` is a
fast pre-commit gate. The warehouse-level referential checks live in
tests/test_integrity.sql and run via `make test-integrity`.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from elt.transform.main import (
    compute_duration_minutes,
    parse_duration_minutes,
    standardize_time,
    to_timestamp,
)
from elt.transform.validation import (
    VALID_AIRPORTS,
    AmbiguousAirportError,
    DurationMismatchError,
    TimeFormatError,
    UnknownAirportError,
    ValidationError,
    airline_code_from_flight_no,
    reject_ambiguous,
    validate_airport_code,
    validate_duration,
    validate_flight_no,
)


# ==========================================================================
# The headline rule: 'NY' is rejected, 'DTW' passes.
# ==========================================================================
def test_ny_is_rejected_and_never_becomes_jfk():
    """'NY' is a metro code. It must raise, not silently resolve to JFK."""
    with pytest.raises(AmbiguousAirportError) as excinfo:
        reject_ambiguous({"dep_code": "NY", "arr_code": "SFO"})

    message = str(excinfo.value)
    assert "NY" in message
    assert "ambiguous" in message.lower()
    # Guard against a future "helpful" mapping being added.
    assert "JFK" not in message.replace("NOT JFK", "")


def test_dtw_passes():
    """A valid station code passes and comes back normalised."""
    result = reject_ambiguous({"dep_code": "DTW", "arr_code": "JFK"})
    assert result == {"dep_code": "DTW", "arr_code": "JFK"}


def test_reject_ambiguous_accepts_a_bare_code():
    assert reject_ambiguous("DTW") == {"code": "DTW"}
    with pytest.raises(AmbiguousAirportError):
        reject_ambiguous("NY")


@pytest.mark.parametrize("code", VALID_AIRPORTS)
def test_every_valid_airport_passes(code):
    assert validate_airport_code(code) == code


@pytest.mark.parametrize("code", ["NY", "NYC", "WAS", "CHI", "LON", "TYO"])
def test_all_metro_codes_are_ambiguous(code):
    with pytest.raises(AmbiguousAirportError):
        validate_airport_code(code)


@pytest.mark.parametrize("code", ["LGA", "ORD", "XXX", "atl"])
def test_unknown_airports_are_rejected(code):
    with pytest.raises(UnknownAirportError):
        validate_airport_code(code)


@pytest.mark.parametrize("code", ["", None, "  ", "nan"])
def test_missing_airport_code_is_rejected(code):
    with pytest.raises(UnknownAirportError):
        validate_airport_code(code)


def test_codes_are_normalised_before_validation():
    assert validate_airport_code("  dtw ") == "DTW"


def test_same_departure_and_arrival_is_rejected():
    with pytest.raises(ValidationError):
        reject_ambiguous({"dep_code": "JFK", "arr_code": "jfk"})


def test_missing_field_is_rejected():
    with pytest.raises(UnknownAirportError):
        reject_ambiguous({"dep_code": "DTW"})


# ==========================================================================
# AM/PM -> 24-hour standardisation
# ==========================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10:00 AM", "10:00"),          # the assignment's DTW departure
        ("11:45 AM", "11:45"),          # the assignment's JFK arrival
        ("1:00 PM", "13:00"),           # the assignment's JFK departure
        ("4:30 PM", "16:30"),           # the assignment's SFO arrival
        ("12:00 AM", "00:00"),          # midnight edge case
        ("12:00 PM", "12:00"),          # noon edge case
        ("12:05 AM", "00:05"),
        ("11:59 PM", "23:59"),
        ("10:00 am", "10:00"),          # lower case
        ("10:00 a.m.", "10:00"),        # dotted
        ("23:30", "23:30"),             # already 24-hour
        ("2026-09-09 1:00 PM", "13:00"),  # full staging timestamp
    ],
)
def test_standardize_time(raw, expected):
    assert standardize_time(raw) == expected


@pytest.mark.parametrize("raw", ["13:00 PM", "0:00 AM", "25:00", "10:60", "noon", "", None])
def test_bad_timestamps_are_rejected(raw):
    with pytest.raises(TimeFormatError):
        standardize_time(raw)


def test_to_timestamp_uses_the_embedded_date():
    assert to_timestamp("2026-09-09 10:00 AM") == datetime(2026, 9, 9, 10, 0)


def test_to_timestamp_falls_back_to_the_default_service_date():
    from datetime import date

    assert to_timestamp("10:00 AM", default_date=date(2026, 9, 9)) == datetime(
        2026, 9, 9, 10, 0
    )


# ==========================================================================
# Duration parsing, calculation and cross-validation
# ==========================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1h 45m", 105),
        ("3h 30m", 210),
        ("2h", 120),
        ("45m", 45),
        ("1:45", 105),
        ("105", 105),
        ("1 hour 45 min", 105),
        ("", None),
        (None, None),
    ],
)
def test_parse_duration_minutes(raw, expected):
    assert parse_duration_minutes(raw) == expected


def test_unparseable_duration_raises():
    with pytest.raises(ValidationError):
        parse_duration_minutes("about two hours")


def test_duration_from_the_assignment_legs():
    # DL857 DTW -> JFK, 10:00 AM to 11:45 AM
    minutes, overnight = compute_duration_minutes(
        to_timestamp("2026-09-09 10:00 AM"), to_timestamp("2026-09-09 11:45 AM")
    )
    assert (minutes, overnight) == (105, False)

    # DL857 JFK -> SFO, 1:00 PM to 4:30 PM
    minutes, overnight = compute_duration_minutes(
        to_timestamp("2026-09-09 1:00 PM"), to_timestamp("2026-09-09 4:30 PM")
    )
    assert (minutes, overnight) == (210, False)


def test_overnight_leg_rolls_to_the_next_day():
    minutes, overnight = compute_duration_minutes(
        to_timestamp("2026-09-09 11:30 PM"), to_timestamp("2026-09-09 3:00 AM")
    )
    assert (minutes, overnight) == (210, True)


def test_reported_duration_matching_the_clock_is_accepted():
    assert validate_duration(105, parse_duration_minutes("1h 45m")) == 105


def test_reported_duration_disagreeing_with_the_clock_is_rejected():
    with pytest.raises(DurationMismatchError):
        validate_duration(105, parse_duration_minutes("2h 45m"), flight_no="DL857")


def test_duration_tolerance_is_honoured():
    assert validate_duration(105, 107, tolerance_minutes=5) == 105
    with pytest.raises(DurationMismatchError):
        validate_duration(105, 117, tolerance_minutes=5)


def test_missing_reported_duration_trusts_the_clock():
    assert validate_duration(105, None) == 105


# ==========================================================================
# Flight number handling (degenerate dimension + airline lookup)
# ==========================================================================
def test_flight_no_is_normalised():
    assert validate_flight_no(" dl857 ") == "DL857"


def test_airline_code_is_derived_from_the_flight_number():
    assert airline_code_from_flight_no("DL857") == "DL"


@pytest.mark.parametrize("bad", ["857", "DELTA857", "DL", "", None])
def test_bad_flight_numbers_are_rejected(bad):
    with pytest.raises(ValidationError):
        validate_flight_no(bad)
