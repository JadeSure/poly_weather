from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


STATION_RE = re.compile(r"^(?P<station>[A-Z]{4})\s")
TIME_RE = re.compile(r"\b(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})Z\b")
WIND_RE = re.compile(r"\b(?P<direction>\d{3}|VRB)(?P<speed>\d{2,3})KT\b")
VISIBILITY_RE = re.compile(r"\b(?P<visibility>\d{4})\b")
TEMP_RE = re.compile(r"\b(?P<temp>M?\d{2})/(?P<dewpoint>M?\d{2})\b")
PRESSURE_RE = re.compile(r"\bQ(?P<pressure>\d{4})\b")


@dataclass(slots=True)
class ParsedMetarObservation:
    station: str
    observed_at: datetime
    temperature_c: float | None
    dewpoint_c: float | None
    wind_speed_kt: int | None
    wind_direction_deg: int | None
    visibility_m: int | None
    pressure_hpa: float | None
    raw_text: str


def _parse_signed_two_digit_temp(token: str) -> float:
    if token.startswith("M"):
        return -float(token[1:])
    return float(token)


def _resolve_observation_time(
    day: int,
    hour: int,
    minute: int,
    reference_time: datetime | None = None,
) -> datetime:
    ref = reference_time or datetime.now(timezone.utc)
    candidate = datetime(ref.year, ref.month, day, hour, minute, tzinfo=timezone.utc)

    # Handle month boundaries conservatively for METAR day-of-month timestamps.
    if (candidate - ref).days > 7:
        month = ref.month - 1 or 12
        year = ref.year - 1 if ref.month == 1 else ref.year
        candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    elif (ref - candidate).days > 25:
        month = ref.month + 1 if ref.month < 12 else 1
        year = ref.year + 1 if ref.month == 12 else ref.year
        candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)

    return candidate


def parse_metar(
    report_text: str,
    reference_time: datetime | None = None,
) -> ParsedMetarObservation:
    station_match = STATION_RE.search(report_text)
    time_match = TIME_RE.search(report_text)
    if station_match is None or time_match is None:
        raise ValueError(f"Invalid METAR report: {report_text!r}")

    station = station_match.group("station")
    observed_at = _resolve_observation_time(
        int(time_match.group("day")),
        int(time_match.group("hour")),
        int(time_match.group("minute")),
        reference_time=reference_time,
    )

    wind_match = WIND_RE.search(report_text)
    visibility_match = VISIBILITY_RE.search(report_text)
    temp_match = TEMP_RE.search(report_text)
    pressure_match = PRESSURE_RE.search(report_text)

    wind_direction = None
    if wind_match and wind_match.group("direction") != "VRB":
        wind_direction = int(wind_match.group("direction"))

    temperature_c = None
    dewpoint_c = None
    if temp_match:
        temperature_c = _parse_signed_two_digit_temp(temp_match.group("temp"))
        dewpoint_c = _parse_signed_two_digit_temp(temp_match.group("dewpoint"))

    return ParsedMetarObservation(
        station=station,
        observed_at=observed_at,
        temperature_c=temperature_c,
        dewpoint_c=dewpoint_c,
        wind_speed_kt=int(wind_match.group("speed")) if wind_match else None,
        wind_direction_deg=wind_direction,
        visibility_m=int(visibility_match.group("visibility")) if visibility_match else None,
        pressure_hpa=float(pressure_match.group("pressure")) if pressure_match else None,
        raw_text=report_text,
    )


def observed_local_time(observation: ParsedMetarObservation, timezone_name: str) -> datetime:
    return observation.observed_at.astimezone(ZoneInfo(timezone_name))

