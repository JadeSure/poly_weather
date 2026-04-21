from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from src.common.logging import logger
from src.common.settings import get_settings
from src.common.time import ensure_utc, parse_utc_datetime, utc_now
from src.data.awc_client import AviationWeatherClient
from src.data.taf_parser import parse_taf_payload
from src.db.models import MetarObservation, Station, TafForecastPeriod, TafReport


@dataclass(slots=True)
class WeatherFetchResult:
    station_code: str
    metar_count: int
    taf_count: int
    stale: bool


@dataclass(slots=True)
class StationWeatherPayloads:
    station: Station
    metar_payloads: list[dict]
    taf_payloads: list[dict]


async def fetch_weather_for_station(
    session: Session,
    station: Station,
    client: AviationWeatherClient | None = None,
) -> WeatherFetchResult:
    settings = get_settings()
    weather_client = client or AviationWeatherClient(settings.noaa_awc_api_base)
    payloads = await _fetch_station_payloads(station, weather_client)
    return _persist_weather_payloads(
        session,
        payloads.station,
        payloads.metar_payloads,
        payloads.taf_payloads,
    )

async def _fetch_station_payloads(
    station: Station,
    client: AviationWeatherClient,
) -> StationWeatherPayloads:
    metar_payloads, taf_payloads = await asyncio.gather(
        client.fetch_metar([station.icao_code]),
        client.fetch_taf([station.icao_code]),
    )
    return StationWeatherPayloads(
        station=station,
        metar_payloads=metar_payloads,
        taf_payloads=taf_payloads,
    )


async def sync_weather(
    session: Session,
    client: AviationWeatherClient | None = None,
    engine=None,
) -> list[WeatherFetchResult]:
    stations = session.exec(
        select(Station).where(Station.is_active.is_(True)).order_by(Station.city_name)
    ).all()

    if engine is None:
        results: list[WeatherFetchResult] = []
        for station in stations:
            results.append(await fetch_weather_for_station(session, station, client=client))
        return results

    settings = get_settings()
    weather_client = client or AviationWeatherClient(settings.noaa_awc_api_base)

    if _engine_uses_sqlite(engine):
        fetched_results = await asyncio.gather(
            *[_fetch_one_payloads(station, weather_client) for station in stations]
        )
        results: list[WeatherFetchResult] = []
        for fetched in fetched_results:
            if isinstance(fetched, WeatherFetchResult):
                results.append(fetched)
                continue
            try:
                results.append(
                    await _persist_weather_payloads_with_retry(
                        session,
                        fetched.station,
                        fetched.metar_payloads,
                        fetched.taf_payloads,
                    )
                )
            except Exception:
                logger.exception(
                    "station_fetch_failed",
                    extra={"event": "station_fetch_failed", "station": fetched.station.icao_code},
                )
                session.rollback()
                results.append(
                    WeatherFetchResult(
                        station_code=fetched.station.icao_code,
                        metar_count=0,
                        taf_count=0,
                        stale=True,
                    )
                )
        return results

    async def _fetch_one(station: Station) -> WeatherFetchResult:
        try:
            with Session(engine) as stn_session:
                return await fetch_weather_for_station(stn_session, station, client=weather_client)
        except Exception:
            logger.exception(
                "station_fetch_failed",
                extra={"event": "station_fetch_failed", "station": station.icao_code},
            )
            return WeatherFetchResult(
                station_code=station.icao_code, metar_count=0, taf_count=0, stale=True,
            )

    return list(await asyncio.gather(*[_fetch_one(s) for s in stations]))


async def _fetch_one_payloads(
    station: Station,
    weather_client: AviationWeatherClient,
) -> StationWeatherPayloads | WeatherFetchResult:
    try:
        return await _fetch_station_payloads(station, weather_client)
    except Exception:
        logger.exception(
            "station_fetch_failed",
            extra={"event": "station_fetch_failed", "station": station.icao_code},
        )
        return WeatherFetchResult(
            station_code=station.icao_code,
            metar_count=0,
            taf_count=0,
            stale=True,
        )


async def run_weather_loop() -> None:
    raise NotImplementedError("Scheduling is handled by src.worker.main.")


def save_metar_payload(session: Session, station: Station, payload: dict) -> int:
    observed_at = parse_utc_datetime(payload.get("reportTime")) or parse_utc_datetime(
        payload.get("obsTime")
    )
    if observed_at is None:
        raise ValueError(f"METAR payload missing observation time: {payload}")

    raw_report = payload.get("rawOb") or ""
    existing = _find_pending_metar(session, station.id, observed_at)
    if existing is None:
        with session.no_autoflush:
            existing = session.exec(
                select(MetarObservation).where(
                    MetarObservation.station_id == station.id,
                    MetarObservation.observed_at == observed_at,
                )
            ).first()
    if existing is not None:
        existing.temperature_c = payload.get("temp")
        existing.dewpoint_c = payload.get("dewp")
        existing.wind_speed_kt = payload.get("wspd")
        existing.wind_direction_deg = payload.get("wdir")
        existing.pressure_hpa = payload.get("altim")
        existing.visibility_m = _parse_visibility_to_m(payload.get("visib"))
        existing.raw_report = raw_report
        existing.fetched_at = utc_now()
        session.add(existing)
        return 0

    session.add(
        MetarObservation(
            station_id=station.id,
            observed_at=observed_at,
            temperature_c=payload.get("temp"),
            dewpoint_c=payload.get("dewp"),
            wind_speed_kt=payload.get("wspd"),
            wind_direction_deg=payload.get("wdir"),
            pressure_hpa=payload.get("altim"),
            visibility_m=_parse_visibility_to_m(payload.get("visib")),
            raw_report=raw_report,
            fetched_at=utc_now(),
        )
    )
    return 1


def _persist_weather_payloads(
    session: Session,
    station: Station,
    metar_payloads: list[dict],
    taf_payloads: list[dict],
) -> WeatherFetchResult:
    metar_count = 0
    taf_count = 0
    for payload in metar_payloads:
        metar_count += save_metar_payload(session, station, payload)
    for payload in taf_payloads:
        taf_count += save_taf_payload(session, station, payload)

    stale = refresh_station_stale_flag(session, station.id)
    session.commit()
    return WeatherFetchResult(
        station_code=station.icao_code,
        metar_count=metar_count,
        taf_count=taf_count,
        stale=stale,
    )


def save_taf_payload(session: Session, station: Station, payload: dict) -> int:
    issue_time = parse_utc_datetime(payload.get("issueTime"))
    if issue_time is None:
        raise ValueError(f"TAF payload missing issue time: {payload}")

    raw_taf = payload.get("rawTAF") or ""
    existing = _find_pending_taf_report(session, station.id, issue_time)
    if existing is None:
        with session.no_autoflush:
            existing = session.exec(
                select(TafReport).where(
                    TafReport.station_id == station.id,
                    TafReport.issue_time == issue_time,
                )
            ).first()
    if existing is not None:
        return 0

    report = TafReport(
        station_id=station.id,
        issue_time=issue_time,
        valid_time_from=parse_utc_datetime(payload.get("validTimeFrom")),
        valid_time_to=parse_utc_datetime(payload.get("validTimeTo")),
        raw_taf=raw_taf,
        fetched_at=utc_now(),
    )
    session.add(report)
    session.flush()

    for period in parse_taf_payload(payload):
        session.add(
            TafForecastPeriod(
                taf_report_id=report.id,
                station_id=station.id,
                time_from=parse_utc_datetime(period.period_start_at),
                time_to=parse_utc_datetime(period.period_end_at),
                time_bec=parse_utc_datetime(period.period_transition_at),
                fcst_change=period.fcst_change,
                probability=period.probability,
                wind_direction_deg=period.wind_direction_deg,
                wind_speed_kt=period.wind_speed_kt,
                wind_gust_kt=period.wind_gust_kt,
                visibility=period.visibility,
                weather_string=period.weather_string,
                clouds_json=period.clouds_json,
                temperature_json=period.temperature_json,
            )
        )
    return 1


def refresh_station_stale_flag(
    session: Session,
    station_id: int | None,
    stale_after_hours: int = 4,
) -> bool:
    if station_id is None:
        return True

    latest = session.exec(
        select(MetarObservation)
        .where(MetarObservation.station_id == station_id)
        .order_by(MetarObservation.observed_at.desc())
    ).first()
    if latest is None:
        return True

    stale_cutoff = utc_now() - timedelta(hours=stale_after_hours)
    latest.is_stale = ensure_utc(latest.observed_at) < stale_cutoff
    session.add(latest)
    return latest.is_stale


def _parse_visibility_to_m(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("+"):
        normalized = normalized[:-1]
    if normalized.endswith("SM"):
        try:
            return int(float(normalized[:-2]) * 1609.34)
        except ValueError:
            return None
    try:
        return int(float(normalized))
    except ValueError:
        return None


def _engine_uses_sqlite(engine) -> bool:
    return getattr(getattr(engine, "dialect", None), "name", None) == "sqlite"


async def _persist_weather_payloads_with_retry(
    session: Session,
    station: Station,
    metar_payloads: list[dict],
    taf_payloads: list[dict],
    max_attempts: int = 4,
    base_delay_seconds: float = 0.25,
) -> WeatherFetchResult:
    for attempt in range(1, max_attempts + 1):
        try:
            return _persist_weather_payloads(session, station, metar_payloads, taf_payloads)
        except OperationalError as exc:
            session.rollback()
            if not _is_sqlite_lock_error(exc) or attempt == max_attempts:
                raise
            logger.warning(
                "sqlite_write_retry",
                extra={
                    "event": "sqlite_write_retry",
                    "station": station.icao_code,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
            await asyncio.sleep(base_delay_seconds * attempt)

    raise RuntimeError("sqlite weather persistence retry loop exhausted")


def _is_sqlite_lock_error(exc: OperationalError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "database is locked" in message or "database table is locked" in message


def _find_pending_metar(
    session: Session,
    station_id: int | None,
    observed_at,
) -> MetarObservation | None:
    for instance in session.new:
        if (
            isinstance(instance, MetarObservation)
            and instance.station_id == station_id
            and instance.observed_at == observed_at
        ):
            return instance
    return None


def _find_pending_taf_report(
    session: Session,
    station_id: int | None,
    issue_time,
) -> TafReport | None:
    for instance in session.new:
        if (
            isinstance(instance, TafReport)
            and instance.station_id == station_id
            and instance.issue_time == issue_time
        ):
            return instance
    return None
