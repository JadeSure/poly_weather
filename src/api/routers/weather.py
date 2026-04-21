import json
import math

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.time import ensure_utc
from src.db.models import (
    EnsembleForecast,
    EnsembleRun,
    MetarObservation,
    Station,
    TafForecastPeriod,
    TafReport,
)

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("/stations")
def list_stations(session: Session = Depends(session_dep)) -> dict:
    stations = session.exec(select(Station).order_by(Station.city_name)).all()
    data = []
    for station in stations:
        latest_observation = session.exec(
            select(MetarObservation)
            .where(MetarObservation.station_id == station.id)
            .order_by(MetarObservation.observed_at.desc())
        ).first()
        data.append(
            {
                "city_code": station.city_code,
                "city_name": station.city_name,
                "icao_code": station.icao_code,
                "settlement_unit": station.settlement_unit,
                "latest_observation": None
                if latest_observation is None
                else {
                    "observed_at": _iso_datetime(latest_observation.observed_at),
                    "temperature_c": latest_observation.temperature_c,
                    "is_stale": latest_observation.is_stale,
                },
            }
        )
    return {"data": data, "error": None}


@router.get("/taf/latest")
def list_latest_taf(
    city_code: str | None = Query(default=None),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_taf_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get("/taf/summary")
def list_latest_taf_summary(
    city_code: str | None = Query(default=None),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_taf_summary_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get("/forecast/latest")
def list_latest_forecast(
    city_code: str | None = Query(default=None),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_forecast_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get("/forecast/summary")
def list_latest_forecast_summary(
    city_code: str | None = Query(default=None),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_forecast_summary_data(session, station) for station in stations]
    return {"data": data, "error": None}


def build_station_taf_data(session: Session, station: Station) -> dict:
    latest_taf = session.exec(
        select(TafReport)
        .where(TafReport.station_id == station.id)
        .order_by(TafReport.issue_time.desc())
    ).first()

    return {
        "city_code": station.city_code,
        "city_name": station.city_name,
        "icao_code": station.icao_code,
        "latest_taf": None if latest_taf is None else serialize_taf_report(session, latest_taf),
    }


def build_station_taf_summary_data(session: Session, station: Station) -> dict:
    latest_taf = session.exec(
        select(TafReport)
        .where(TafReport.station_id == station.id)
        .order_by(TafReport.issue_time.desc())
    ).first()

    return {
        "city_code": station.city_code,
        "city_name": station.city_name,
        "icao_code": station.icao_code,
        "latest_taf": None if latest_taf is None else serialize_taf_report_with_summary(session, latest_taf),
    }


def build_station_forecast_data(session: Session, station: Station) -> dict:
    latest_run = session.exec(
        select(EnsembleRun)
        .where(EnsembleRun.station_id == station.id)
        .order_by(EnsembleRun.fetched_at.desc())
    ).first()

    return {
        "city_code": station.city_code,
        "city_name": station.city_name,
        "icao_code": station.icao_code,
        "latest_forecast": None if latest_run is None else serialize_ensemble_run(session, latest_run),
    }


def build_station_forecast_summary_data(session: Session, station: Station) -> dict:
    latest_run = session.exec(
        select(EnsembleRun)
        .where(EnsembleRun.station_id == station.id)
        .order_by(EnsembleRun.fetched_at.desc())
    ).first()

    return {
        "city_code": station.city_code,
        "city_name": station.city_name,
        "icao_code": station.icao_code,
        "latest_forecast": None if latest_run is None else serialize_ensemble_run_with_summary(session, latest_run),
    }


def serialize_taf_report(session: Session, report: TafReport) -> dict:
    periods = session.exec(
        select(TafForecastPeriod)
        .where(TafForecastPeriod.taf_report_id == report.id)
        .order_by(TafForecastPeriod.time_from.asc(), TafForecastPeriod.id.asc())
    ).all()
    return {
        "issue_time": _iso_datetime(report.issue_time),
        "valid_time_from": _iso_datetime(report.valid_time_from),
        "valid_time_to": _iso_datetime(report.valid_time_to),
        "raw_taf": report.raw_taf,
        "periods": [serialize_taf_period(period) for period in periods],
    }


def serialize_taf_report_with_summary(session: Session, report: TafReport) -> dict:
    periods = session.exec(
        select(TafForecastPeriod)
        .where(TafForecastPeriod.taf_report_id == report.id)
        .order_by(TafForecastPeriod.time_from.asc(), TafForecastPeriod.id.asc())
    ).all()
    serialized_periods = [serialize_taf_period_with_summary(period) for period in periods]
    return {
        "issue_time": _iso_datetime(report.issue_time),
        "valid_time_from": _iso_datetime(report.valid_time_from),
        "valid_time_to": _iso_datetime(report.valid_time_to),
        "raw_taf": report.raw_taf,
        "explanation_zh": "TAF 是机场未来一段时间的天气预报，下面按时间段给出中文解释。",
        "periods": serialized_periods,
        "summary_lines_zh": [item["summary_zh"] for item in serialized_periods],
    }


def serialize_ensemble_run(session: Session, run: EnsembleRun) -> dict:
    forecasts = session.exec(
        select(EnsembleForecast)
        .where(EnsembleForecast.ensemble_run_id == run.id)
        .order_by(EnsembleForecast.forecast_date_local.asc(), EnsembleForecast.member_index.asc())
    ).all()
    grouped = group_forecasts_by_date(forecasts)
    return {
        "model_name": run.model_name,
        "timezone_name": run.timezone_name,
        "forecast_days": run.forecast_days,
        "fetched_at": _iso_datetime(run.fetched_at),
        "temperature_unit": "C",
        "days": [
            {
                "forecast_date_local": forecast_date_local,
                "member_count": len(items),
                "members": [
                    {
                        "member_index": item.member_index,
                        "member_name": item.member_name,
                        "max_temp_c": item.max_temp_c,
                    }
                    for item in items
                ],
            }
            for forecast_date_local, items in grouped
        ],
    }


def serialize_ensemble_run_with_summary(session: Session, run: EnsembleRun) -> dict:
    forecasts = session.exec(
        select(EnsembleForecast)
        .where(EnsembleForecast.ensemble_run_id == run.id)
        .order_by(EnsembleForecast.forecast_date_local.asc(), EnsembleForecast.member_index.asc())
    ).all()
    grouped = group_forecasts_by_date(forecasts)
    day_summaries = [
        summarize_forecast_day(forecast_date_local, items)
        for forecast_date_local, items in grouped
    ]
    return {
        "model_name": run.model_name,
        "timezone_name": run.timezone_name,
        "forecast_days": run.forecast_days,
        "fetched_at": _iso_datetime(run.fetched_at),
        "temperature_unit": "C",
        "explanation_zh": "这是 Open-Meteo ensemble 的日最高温摘要，表示同一日期下多个预报成员的分布情况。",
        "days": day_summaries,
        "summary_lines_zh": [item["summary_zh"] for item in day_summaries],
    }


def serialize_taf_period(period: TafForecastPeriod) -> dict:
    return {
        "time_from": _iso_datetime(period.time_from),
        "time_to": _iso_datetime(period.time_to),
        "time_bec": _iso_datetime(period.time_bec),
        "fcst_change": period.fcst_change,
        "probability": period.probability,
        "wind_direction_deg": period.wind_direction_deg,
        "wind_speed_kt": period.wind_speed_kt,
        "wind_gust_kt": period.wind_gust_kt,
        "visibility": period.visibility,
        "weather_string": period.weather_string,
        "clouds": _parse_json_field(period.clouds_json),
        "temperature": _parse_json_field(period.temperature_json),
    }


def serialize_taf_period_with_summary(period: TafForecastPeriod) -> dict:
    payload = serialize_taf_period(period)
    payload["change_label_zh"] = _fcst_change_to_zh(period.fcst_change)
    payload["summary_zh"] = build_taf_period_summary_zh(period)
    return payload


def build_taf_period_summary_zh(period: TafForecastPeriod) -> str:
    parts = [
        _build_time_text(period),
        _fcst_change_to_zh(period.fcst_change),
        _build_wind_text(period),
        _build_visibility_text(period.visibility),
        _build_weather_text(period.weather_string),
        _build_cloud_text(period.clouds_json),
    ]
    return "；".join(part for part in parts if part)


def _build_time_text(period: TafForecastPeriod) -> str:
    if period.time_from and period.time_to:
        return f"{period.time_from.isoformat()} 到 {period.time_to.isoformat()}"
    if period.time_from:
        return f"从 {period.time_from.isoformat()} 开始"
    return "时间未明确"


def _fcst_change_to_zh(value: str | None) -> str:
    mapping = {
        None: "基础预报时段",
        "FM": "从该时刻开始转为以下条件",
        "BECMG": "天气逐步转变为以下条件",
        "TEMPO": "短时波动时段",
        "PROB30": "有 30% 概率出现以下条件",
        "PROB40": "有 40% 概率出现以下条件",
    }
    return mapping.get(value, f"变化类型 {value}")


def _build_wind_text(period: TafForecastPeriod) -> str:
    if period.wind_speed_kt is None and period.wind_direction_deg is None:
        return ""
    parts = []
    if period.wind_direction_deg is not None:
        parts.append(f"风向 {period.wind_direction_deg} 度")
    if period.wind_speed_kt is not None:
        parts.append(f"风速 {period.wind_speed_kt} 节")
    if period.wind_gust_kt is not None:
        parts.append(f"阵风 {period.wind_gust_kt} 节")
    return "，".join(parts)


def _build_visibility_text(value: str | None) -> str:
    if not value:
        return ""
    if value == "6+":
        return "能见度较好，通常表示 6 英里或以上"
    return f"能见度 {value}"


def _build_weather_text(value: str | None) -> str:
    if not value:
        return "无显著天气现象"
    return f"天气现象 {value}"


def _build_cloud_text(value: str | None) -> str:
    clouds = _parse_json_field(value)
    if not isinstance(clouds, list) or not clouds:
        return "云况未明确"

    parts: list[str] = []
    for item in clouds:
        if not isinstance(item, dict):
            continue
        cover = _cloud_cover_to_zh(item.get("cover"))
        base = item.get("base")
        if base is None:
            parts.append(cover)
        else:
            parts.append(f"{cover}，云底约 {base} 英尺")
    return "；".join(parts) if parts else "云况未明确"


def _cloud_cover_to_zh(value: str | None) -> str:
    mapping = {
        "SKC": "晴空",
        "CLR": "无云",
        "FEW": "少云",
        "SCT": "疏云",
        "BKN": "多云",
        "OVC": "阴天",
        "VV": "垂直能见度受限",
    }
    return mapping.get(value, value or "云况未知")


def group_forecasts_by_date(
    forecasts: list[EnsembleForecast],
) -> list[tuple[str, list[EnsembleForecast]]]:
    grouped: dict[str, list[EnsembleForecast]] = {}
    for forecast in forecasts:
        key = forecast.forecast_date_local.isoformat()
        grouped.setdefault(key, []).append(forecast)
    return sorted(grouped.items(), key=lambda item: item[0])


def summarize_forecast_day(
    forecast_date_local: str,
    forecasts: list[EnsembleForecast],
) -> dict:
    values = sorted(item.max_temp_c for item in forecasts)
    member_count = len(values)
    average = round(sum(values) / member_count, 2) if values else None
    median = round(_quantile(values, 0.5), 2) if values else None
    p10 = round(_quantile(values, 0.1), 2) if values else None
    p90 = round(_quantile(values, 0.9), 2) if values else None
    min_value = round(values[0], 2) if values else None
    max_value = round(values[-1], 2) if values else None
    return {
        "forecast_date_local": forecast_date_local,
        "member_count": member_count,
        "avg_max_temp_c": average,
        "median_max_temp_c": median,
        "p10_max_temp_c": p10,
        "p90_max_temp_c": p90,
        "min_max_temp_c": min_value,
        "max_max_temp_c": max_value,
        "summary_zh": (
            f"{forecast_date_local} 的日最高温 ensemble 摘要："
            f"共 {member_count} 个成员，均值 {average}C，中位数 {median}C，"
            f"10% 分位 {p10}C，90% 分位 {p90}C，整体范围 {min_value}C 到 {max_value}C。"
        ),
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot compute quantile for empty values.")
    if len(values) == 1:
        return float(values[0])

    index = (len(values) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(values[lower])
    weight = index - lower
    return float(values[lower] * (1 - weight) + values[upper] * weight)


def _parse_json_field(value: str | None) -> list | dict | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat()
