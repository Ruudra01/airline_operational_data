#!/usr/bin/env python3
"""Validation rules for the transform stage (owner: Person 3).

The single most important rule in this platform:

    An ambiguous station code is REJECTED, never resolved.

'NY' is a metro/city code covering JFK, LGA and EWR. Mapping it to JFK would
invent a fact that the source never stated, and it would silently corrupt
every route-level metric in the warehouse. So we raise instead.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

#: The only station codes this platform is allowed to load.
VALID_AIRPORTS: list[str] = ["DTW", "JFK", "SFO"]

#: Metro/city codes that look like airports but identify more than one.
#: Listed separately only to produce a clearer error message.
AMBIGUOUS_AIRPORTS: frozenset[str] = frozenset({"NY", "NYC", "WAS", "CHI", "LON", "TYO"})

#: Staging columns that hold a station code.
AIRPORT_CODE_FIELDS: tuple[str, ...] = ("dep_code", "arr_code")


class ValidationError(ValueError):
    """Base class for every row-level rejection reason."""


class AmbiguousAirportError(ValidationError):
    """Raised for metro codes such as 'NY' that map to several airports."""


class UnknownAirportError(ValidationError):
    """Raised for a code that is neither valid nor a known metro code."""


class DurationMismatchError(ValidationError):
    """Raised when the source-reported duration disagrees with the clock times."""


class TimeFormatError(ValidationError):
    """Raised when a timestamp cannot be parsed as a 12- or 24-hour clock."""


def normalise_code(value: Any) -> str:
    """Trim and upper-case a station code; None/NaN become ''."""
    if value is None:
        return ""
    text = str(value).strip().upper()
    return "" if text in {"", "NAN", "NONE", "NULL"} else text


def validate_airport_code(value: Any, *, field: str = "airport_code") -> str:
    """Return the normalised code, or raise.

    >>> validate_airport_code("dtw")
    'DTW'
    >>> validate_airport_code("NY")
    Traceback (most recent call last):
        ...
    elt.transform.validation.AmbiguousAirportError: ...
    """
    code = normalise_code(value)

    if not code:
        raise UnknownAirportError(f"{field}: station code is missing")

    if code in VALID_AIRPORTS:
        return code

    if code in AMBIGUOUS_AIRPORTS:
        raise AmbiguousAirportError(
            f"{field}: {code!r} is an ambiguous city/metro code and cannot be "
            f"resolved to a single airport (it is NOT JFK). Fix the source feed."
        )

    raise UnknownAirportError(
        f"{field}: {code!r} is not a known airport. "
        f"Allowed: {', '.join(VALID_AIRPORTS)}."
    )


def reject_ambiguous(row: Mapping[str, Any] | str) -> dict[str, str]:
    """Reject a staging row (or a bare code) that carries a bad station code.

    Accepts either a mapping with `dep_code` / `arr_code` keys - the normal
    case, one staging row - or a single code string for convenience.

    Returns the normalised codes on success; raises
    :class:`AmbiguousAirportError` or :class:`UnknownAirportError` otherwise.
    Nothing is ever repaired or guessed.
    """
    if isinstance(row, str):
        return {"code": validate_airport_code(row, field="airport_code")}

    cleaned: dict[str, str] = {}
    for field in AIRPORT_CODE_FIELDS:
        if field not in row:
            raise UnknownAirportError(f"row is missing required field {field!r}")
        cleaned[field] = validate_airport_code(row[field], field=field)

    if cleaned["dep_code"] == cleaned["arr_code"]:
        raise ValidationError(
            f"departure and arrival station are identical ({cleaned['dep_code']})"
        )
    return cleaned


def validate_flight_no(value: Any) -> str:
    """Normalise 'dl857 ' -> 'DL857' and require carrier + number."""
    flight_no = normalise_code(value).replace(" ", "")
    if not flight_no:
        raise ValidationError("flight_no: missing")
    carrier, number = flight_no[:2], flight_no[2:]
    if not (carrier.isalpha() and number.isdigit()):
        raise ValidationError(
            f"flight_no: {flight_no!r} is not <2-letter carrier><number>, e.g. 'DL857'"
        )
    return flight_no


def airline_code_from_flight_no(flight_no: str) -> str:
    """'DL857' -> 'DL'."""
    return validate_flight_no(flight_no)[:2]


def validate_duration(
    computed_minutes: int,
    reported_minutes: int | None,
    *,
    tolerance_minutes: int = 0,
    flight_no: str = "",
) -> int:
    """Cross-check the recomputed duration against the source-reported one."""
    if computed_minutes <= 0:
        raise DurationMismatchError(
            f"{flight_no}: computed duration {computed_minutes} min is not positive"
        )
    if reported_minutes is None:
        # Source did not report a duration: trust the clock times, but say so.
        return computed_minutes
    drift = abs(computed_minutes - reported_minutes)
    if drift > tolerance_minutes:
        raise DurationMismatchError(
            f"{flight_no}: source reported {reported_minutes} min but the "
            f"departure/arrival clock times give {computed_minutes} min "
            f"(drift {drift} min > tolerance {tolerance_minutes} min)"
        )
    return computed_minutes


def unknown_codes(codes: Iterable[Any]) -> set[str]:
    """Codes in `codes` that would be rejected. Handy for profiling staging."""
    bad = set()
    for code in codes:
        try:
            validate_airport_code(code)
        except ValidationError:
            bad.add(normalise_code(code))
    return bad
