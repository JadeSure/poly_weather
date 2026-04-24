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


@router.get(
    "/stations",
    summary="列出所有气象站",
    description=(
        "返回系统中所有活跃气象站及其最新 METAR 地面观测数据。\n\n"
        "每个城市绑定一个 ICAO 气象站（通常为该城市主要国际机场），用于获取实时气温观测。"
        "气象站的选择需要与 Polymarket 合约中指定的结算数据源 (Weather Underground) 使用的站点保持一致，"
        "否则模型预测温度与结算温度可能存在系统性偏差。\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `city_code` | string | 城市唯一标识符，全小写英文，如 `chicago`、`london`、`seoul`、`paris`、`miami`。系统各处统一使用此值关联数据 |\n"
        "| `city_name` | string | 城市显示名称，如 `Chicago`、`London` |\n"
        "| `icao_code` | string | ICAO 四字母机场代码，如 `KORD`（芝加哥奥黑尔）、`EGLC`（伦敦城市机场）、`RKSI`（首尔仁川）。此代码决定系统从 NOAA AWC 获取 METAR/TAF 数据的站点 |\n"
        "| `settlement_unit` | string | Polymarket 合约使用的温度单位：`F`（华氏度，用于美国城市 Chicago/Miami）或 `C`（摄氏度，用于 London/Paris/Seoul）。模型内部统一使用摄氏度计算，输出时按此单位转换 |\n"
        "| `latest_observation` | object \\| null | 最新一条 METAR 地面观测数据，null 表示该站尚无观测入库 |\n\n"
        "**latest_observation 子字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `observed_at` | string | 观测时间，ISO 8601 格式带 UTC 时区（如 `2026-04-24T12:00:00+00:00`）。METAR 通常每小时发布一次 |\n"
        "| `temperature_c` | float \\| null | 观测到的气温（摄氏度），null 表示该条 METAR 未包含温度数据（罕见） |\n"
        "| `is_stale` | boolean | 观测是否过期。若该站最近 3 小时内没有新的 METAR 报文入库，则标记为 `true`。过期观测会导致该站的信号被降级为 SKIP（skip_reason=`weather_data_stale`） |"
    ),
)
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


@router.get(
    "/taf/latest",
    summary="获取最新 TAF 预报原始数据",
    description=(
        "返回各气象站最新的 TAF（Terminal Aerodrome Forecast）预报，包含原始报文和结构化时段数据。\n\n"
        "**返回字段说明：**\n"
        "- `city_code` / `city_name` / `icao_code` — 站点标识\n"
        "- `latest_taf` — 最新 TAF 报文：\n"
        "  - `issue_time` — 发布时间 (ISO 8601 UTC)\n"
        "  - `valid_time_from` / `valid_time_to` — 有效时间范围\n"
        "  - `raw_taf` — 原始 TAF 报文文本\n"
        "  - `periods[]` — 各预报时段：\n"
        "    - `time_from` / `time_to` — 时段起止\n"
        "    - `fcst_change` — 变化类型（FM/BECMG/TEMPO/PROB30/PROB40）\n"
        "    - `wind_direction_deg` / `wind_speed_kt` / `wind_gust_kt` — 风况\n"
        "    - `visibility` — 能见度\n"
        "    - `weather_string` — 天气现象代码\n"
        "    - `clouds` — 云层信息 JSON\n"
        "    - `temperature` — 温度信息 JSON"
    ),
)
def list_latest_taf(
    city_code: str | None = Query(default=None, description="按城市代码过滤（如 chicago, london）"),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_taf_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get(
    "/taf/summary",
    summary="获取最新 TAF 预报中文摘要",
    description=(
        "与 `/taf/latest` 相同数据，额外提供中文翻译摘要。\n\n"
        "**额外字段：**\n"
        "- `explanation_zh` — TAF 整体说明\n"
        "- `summary_lines_zh` — 各时段中文摘要列表\n"
        "- 各 period 内增加 `change_label_zh`（变化类型中文）和 `summary_zh`（时段完整摘要）"
    ),
)
def list_latest_taf_summary(
    city_code: str | None = Query(default=None, description="按城市代码过滤（如 chicago, london）"),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_taf_summary_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get(
    "/forecast/latest",
    summary="获取最新 Ensemble 集合预报原始数据",
    description=(
        "返回各站点最新的 Open-Meteo GFS ensemble 集合预报，包含每个成员的逐日最高温原始值。\n\n"
        "**什么是 Ensemble 预报？** GFS ensemble 预报使用 31 个略有不同的初始条件运行同一个气象模型，"
        "产生 31 条独立的温度预测轨迹。这些轨迹的分散程度反映了预测的不确定性。"
        "系统用「落入某温度区间的成员数 / 31」作为该区间的模型概率。\n\n"
        "**数据新鲜度：** `fetched_at` 是判断预报是否过期的关键字段。"
        "如果 `fetched_at` 距当前时间超过 24 小时，该预报被视为过期（stale），"
        "基于此预报生成的所有信号将被强制标记为 SKIP（skip_reason=`forecast_stale`）。"
        "正常情况下预报每 3 小时刷新一次。\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `city_code` | string | 城市标识符 |\n"
        "| `city_name` | string | 城市显示名称 |\n"
        "| `icao_code` | string | ICAO 站点代码 |\n"
        "| `latest_forecast` | object \\| null | 最新一次 ensemble 预报运行数据，null 表示该站尚无预报 |\n\n"
        "**latest_forecast 子字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `model_name` | string | 预报模型标识，固定为 `gfs_seamless`（Open-Meteo 的 GFS 全球预报系统） |\n"
        "| `timezone_name` | string | 站点本地时区 IANA 名称，如 `America/Chicago`、`Asia/Seoul`。用于将 UTC 时间序列转换为本地日期以计算「本地日最高温」 |\n"
        "| `forecast_days` | integer | 预报覆盖的未来天数，默认 7 天 |\n"
        "| `fetched_at` | string | 此次预报数据从 Open-Meteo API 抓取的时间 (ISO 8601 UTC)。**重要：若此值距今超过 24 小时，意味着预报数据可能过期，信号可信度下降** |\n"
        "| `temperature_unit` | string | 温度单位，固定为 `C`（摄氏度）。系统内部统一用摄氏度，展示和结算时再按 `settlement_unit` 转换 |\n"
        "| `days` | array | 按本地日期分组的预报数据 |\n\n"
        "**days[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `forecast_date_local` | string | 本地日期 (YYYY-MM-DD)，如 `2026-04-25`。这是 Polymarket 合约对应的结算日期 |\n"
        "| `member_count` | integer | 该日的 ensemble 成员数，通常为 31（1 个控制运行 + 30 个扰动成员） |\n"
        "| `members` | array | 各成员的预测数据 |\n\n"
        "**members[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `member_index` | integer | 成员编号：0 = 控制运行（control run，使用最佳估计初始条件），1-30 = 扰动成员（perturbed members，初始条件有微小随机扰动） |\n"
        "| `member_name` | string | Open-Meteo 变量名：`temperature_2m`（控制运行）或 `temperature_2m_member01` ~ `temperature_2m_member30` |\n"
        "| `max_temp_c` | float | 该成员在该日期的预测日最高温（摄氏度）。计算方式：取该成员该日期所有小时值中的最大值 |"
    ),
)
def list_latest_forecast(
    city_code: str | None = Query(default=None, description="按城市代码过滤（如 chicago, london）"),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Station).order_by(Station.city_name)
    if city_code:
        statement = statement.where(Station.city_code == city_code.strip().lower())

    stations = session.exec(statement).all()
    data = [build_station_forecast_data(session, station) for station in stations]
    return {"data": data, "error": None}


@router.get(
    "/forecast/summary",
    summary="获取 Ensemble 集合预报统计摘要",
    description=(
        "返回 ensemble 预报的统计摘要视图。与 `/forecast/latest` 使用相同数据源，"
        "但不返回每个成员的原始值，而是返回聚合统计量（均值、中位数、分位数等），便于快速评估预报分布。\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 顶层字段：** 同 `/forecast/latest`（city_code, city_name, icao_code, latest_forecast）\n\n"
        "**latest_forecast 子字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `model_name` | string | 预报模型标识，固定 `gfs_seamless` |\n"
        "| `timezone_name` | string | 站点本地时区 |\n"
        "| `forecast_days` | integer | 预报覆盖天数 |\n"
        "| `fetched_at` | string | 预报抓取时间 (ISO 8601 UTC) |\n"
        "| `temperature_unit` | string | 温度单位，固定 `C` |\n"
        "| `explanation_zh` | string | Ensemble 摘要的中文说明文本 |\n"
        "| `days` | array | 按日期分组的统计数据 |\n"
        "| `summary_lines_zh` | array[string] | 所有日期的中文摘要列表，方便批量展示 |\n\n"
        "**days[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `forecast_date_local` | string | 本地日期 (YYYY-MM-DD) |\n"
        "| `member_count` | integer | 参与统计的 ensemble 成员数（通常 31） |\n"
        "| `avg_max_temp_c` | float | 所有成员日最高温的**算术平均值**（摄氏度）。代表模型的「共识预测」 |\n"
        "| `median_max_temp_c` | float | **中位数**，即第 16 个成员的值。比均值更抗异常值 |\n"
        "| `p10_max_temp_c` | float | **10% 分位数**，即偏冷情景下的温度。90% 的成员预测高于此值 |\n"
        "| `p90_max_temp_c` | float | **90% 分位数**，即偏热情景下的温度。90% 的成员预测低于此值 |\n"
        "| `min_max_temp_c` | float | 所有成员中的**最低预测值**，代表极端偏冷情景 |\n"
        "| `max_max_temp_c` | float | 所有成员中的**最高预测值**，代表极端偏热情景 |\n"
        "| `summary_zh` | string | 该日的中文摘要，格式如：「2026-04-25 的日最高温 ensemble 摘要：共 31 个成员，均值 16.25C，中位数 15.9C，...」 |\n\n"
        "**如何使用：** p10-p90 区间覆盖了 80% 的可能性。如果某个 Polymarket bucket 完全落在 p10 以下或 p90 以上，"
        "说明该 bucket 有很高/很低的概率发生，可与市场价格对比寻找 edge。"
    ),
)
def list_latest_forecast_summary(
    city_code: str | None = Query(default=None, description="按城市代码过滤（如 chicago, london）"),
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
