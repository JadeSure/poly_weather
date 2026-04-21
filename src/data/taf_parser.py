import json
from dataclasses import dataclass

from src.common.time import parse_utc_datetime


@dataclass(slots=True)
class ParsedTafPeriod:
    raw_text: str
    period_start_at: str | None = None
    period_end_at: str | None = None
    period_transition_at: str | None = None
    fcst_change: str | None = None
    probability: int | None = None
    wind_direction_deg: int | None = None
    wind_speed_kt: int | None = None
    wind_gust_kt: int | None = None
    visibility: str | None = None
    weather_string: str | None = None
    clouds_json: str | None = None
    temperature_json: str | None = None


def parse_taf(report_text: str) -> list[ParsedTafPeriod]:
    return [ParsedTafPeriod(raw_text=report_text)]


def parse_taf_payload(payload: dict) -> list[ParsedTafPeriod]:
    raw_taf = payload.get("rawTAF", "")
    periods: list[ParsedTafPeriod] = []
    for fcst in payload.get("fcsts", []):
        periods.append(
            ParsedTafPeriod(
                raw_text=raw_taf,
                period_start_at=_iso_or_none(fcst.get("timeFrom")),
                period_end_at=_iso_or_none(fcst.get("timeTo")),
                period_transition_at=_iso_or_none(fcst.get("timeBec")),
                fcst_change=fcst.get("fcstChange"),
                probability=fcst.get("probability"),
                wind_direction_deg=fcst.get("wdir"),
                wind_speed_kt=fcst.get("wspd"),
                wind_gust_kt=fcst.get("wgst"),
                visibility=fcst.get("visib"),
                weather_string=fcst.get("wxString"),
                clouds_json=json.dumps(fcst.get("clouds", []), ensure_ascii=True),
                temperature_json=json.dumps(fcst.get("temp", []), ensure_ascii=True),
            )
        )
    return periods or [ParsedTafPeriod(raw_text=raw_taf)]


def _iso_or_none(value: str | int | float | None) -> str | None:
    parsed = parse_utc_datetime(value)
    return parsed.isoformat() if parsed else None

