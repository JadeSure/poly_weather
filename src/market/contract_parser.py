from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.db.models import Station


SETTLEMENT_STATION_RE = re.compile(r"/([A-Z]{4})(?:/)?$")
BUCKET_RE = re.compile(
    r"(?P<low>-?\d+)(?:\s*[-–]\s*(?P<high>-?\d+))?\s*°?\s*(?P<unit>[CF])",
    re.IGNORECASE,
)

# Matches "on April 8", "on April 8?", "on Jan 15", etc.
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December|"
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
)
DATE_IN_TEXT_RE = re.compile(
    rf"\bon\s+(?P<month>{_MONTH_NAMES})\s+(?P<day>\d{{1,2}})\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedContract:
    question: str
    city_code: str | None
    forecast_date_local: date | None
    bucket_label: str | None
    bucket_low: int | None
    bucket_high: int | None
    bucket_unit: str | None
    parsed_station_code: str | None


def parse_station_code_from_url(settlement_url: str | None) -> str | None:
    if not settlement_url:
        return None
    match = SETTLEMENT_STATION_RE.search(settlement_url)
    return match.group(1) if match else None


def parse_bucket_from_text(text: str | None) -> tuple[str | None, int | None, int | None, str | None]:
    if not text:
        return None, None, None, None
    match = BUCKET_RE.search(text)
    if match is None:
        return None, None, None, None

    lower_text = text.lower()
    low = int(match.group("low"))
    high = int(match.group("high")) if match.group("high") else low
    if "or below" in lower_text:
        low = None
    if "or above" in lower_text or "or higher" in lower_text:
        high = None
    unit = match.group("unit").upper()
    return match.group(0), low, high, unit


def parse_json_list(value: str | list | None) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_outcome_token_map(payload: dict) -> dict[str, str]:
    outcomes = parse_json_list(payload.get("outcomes"))
    token_ids = parse_json_list(payload.get("clobTokenIds"))
    return {
        str(outcome): str(token_ids[index])
        for index, outcome in enumerate(outcomes)
        if index < len(token_ids)
    }


def infer_city_code(question: str, stations: list[Station]) -> str | None:
    normalized_question = question.lower()
    for station in stations:
        if station.city_name.lower() in normalized_question:
            return station.city_code
    return None


def is_highest_temp_market(question: str) -> bool:
    q = question.lower()
    if "lowest" in q or "low temp" in q or "minimum" in q:
        return False
    return True


def is_weather_market_payload(payload: dict, stations: list[Station]) -> bool:
    resolution_source = payload.get("resolutionSource") or ""
    description = payload.get("description") or ""
    question = payload.get("question") or ""
    blob = " ".join([resolution_source, description, question]).lower()
    if "wunderground.com/history/daily" in blob:
        if not is_highest_temp_market(question):
            return False
        return True
    if "temperature" in blob or "high temp" in blob:
        if not is_highest_temp_market(question):
            return False
        return infer_city_code(question + " " + description, stations) is not None
    return False


def parse_contract_payload(payload: dict, stations: list[Station]) -> ParsedContract:
    question = payload.get("question") or ""
    city_code = infer_city_code(question + " " + (payload.get("description") or ""), stations)
    settlement_url = payload.get("resolutionSource") or ""
    bucket_label, bucket_low, bucket_high, bucket_unit = parse_bucket_from_text(
        question or payload.get("groupItemTitle")
    )
    forecast_date = _parse_forecast_date_from_text(question)
    if forecast_date is None:
        forecast_date = _parse_forecast_date_from_iso(payload.get("endDateIso"))
    return ParsedContract(
        question=question,
        city_code=city_code,
        forecast_date_local=forecast_date,
        bucket_label=bucket_label,
        bucket_low=bucket_low,
        bucket_high=bucket_high,
        bucket_unit=bucket_unit,
        parsed_station_code=parse_station_code_from_url(settlement_url),
    )


def _parse_forecast_date_from_text(text: str) -> date | None:
    match = DATE_IN_TEXT_RE.search(text)
    if match is None:
        return None
    month_str = match.group("month")
    day = int(match.group("day"))
    now = datetime.now(timezone.utc)
    try:
        # Try full month name first, then abbreviated
        for fmt in ("%B", "%b"):
            try:
                month = datetime.strptime(month_str, fmt).month
                break
            except ValueError:
                continue
        else:
            return None
        # Assume current year; if the date is far in the past, use next year
        candidate = date(now.year, month, day)
        if (now.date() - candidate).days > 180:
            candidate = date(now.year + 1, month, day)
        return candidate
    except ValueError:
        return None


def _parse_forecast_date_from_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
