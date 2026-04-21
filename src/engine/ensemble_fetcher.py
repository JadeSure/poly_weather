from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from src.common.settings import get_settings
from src.db.models import EnsembleForecast, EnsembleRun, Station
from src.engine.open_meteo_client import OpenMeteoEnsembleClient


@dataclass(slots=True)
class DailyMemberForecast:
    forecast_date_local: date
    member_index: int
    member_name: str
    max_temp_c: float


@dataclass(slots=True)
class ForecastSyncResult:
    station_code: str
    days: int
    members: int


async def sync_forecasts(
    session: Session,
    client: OpenMeteoEnsembleClient | None = None,
    model_name: str = "gfs_seamless",
    forecast_days: int = 7,
) -> list[ForecastSyncResult]:
    settings = get_settings()
    forecast_client = client or OpenMeteoEnsembleClient(settings.open_meteo_ensemble_api_base)
    stations = session.exec(
        select(Station).where(Station.is_active.is_(True)).order_by(Station.city_name)
    ).all()

    results: list[ForecastSyncResult] = []
    for station in stations:
        if station.latitude is None or station.longitude is None:
            continue
        payload = await forecast_client.fetch_hourly_temperature_ensemble(
            latitude=station.latitude,
            longitude=station.longitude,
            timezone_name=station.timezone_name,
            model=model_name,
            forecast_days=forecast_days,
        )
        results.append(save_ensemble_payload(session, station, payload, model_name, forecast_days))
    session.commit()
    return results


def save_ensemble_payload(
    session: Session,
    station: Station,
    payload: dict,
    model_name: str,
    forecast_days: int,
) -> ForecastSyncResult:
    run = EnsembleRun(
        station_id=station.id,
        model_name=model_name,
        timezone_name=payload.get("timezone") or station.timezone_name,
        forecast_days=forecast_days,
    )
    session.add(run)
    session.flush()

    member_forecasts = aggregate_daily_member_maxima(payload)
    for forecast in member_forecasts:
        session.add(
            EnsembleForecast(
                ensemble_run_id=run.id,
                station_id=station.id,
                forecast_date_local=forecast.forecast_date_local,
                member_index=forecast.member_index,
                member_name=forecast.member_name,
                max_temp_c=forecast.max_temp_c,
            )
        )

    distinct_days = {item.forecast_date_local for item in member_forecasts}
    distinct_members = {item.member_name for item in member_forecasts}
    return ForecastSyncResult(
        station_code=station.icao_code,
        days=len(distinct_days),
        members=len(distinct_members),
    )


def aggregate_daily_member_maxima(payload: dict) -> list[DailyMemberForecast]:
    hourly = payload.get("hourly") or {}
    timestamps: list[str] = hourly.get("time") or []
    results: list[DailyMemberForecast] = []

    for member_index, member_name in enumerate(_ensemble_member_keys(hourly)):
        values = hourly.get(member_name) or []
        maxima_by_date: dict[date, float] = {}
        for timestamp, value in zip(timestamps, values, strict=False):
            if value is None:
                continue
            forecast_date = date.fromisoformat(timestamp[:10])
            maxima_by_date[forecast_date] = max(maxima_by_date.get(forecast_date, value), value)

        for forecast_date_local, max_temp_c in sorted(maxima_by_date.items()):
            results.append(
                DailyMemberForecast(
                    forecast_date_local=forecast_date_local,
                    member_index=member_index,
                    member_name=member_name,
                    max_temp_c=float(max_temp_c),
                )
            )
    return results


def _ensemble_member_keys(hourly: dict) -> list[str]:
    keys = []
    if "temperature_2m" in hourly:
        keys.append("temperature_2m")
    keys.extend(sorted(key for key in hourly if key.startswith("temperature_2m_member")))
    return keys


async def run_forecast_loop() -> None:
    raise NotImplementedError("Scheduling is handled by src.worker.main.")
