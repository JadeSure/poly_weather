from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.db.models import (
    EnsembleForecast,
    EnsembleRun,
    Market,
    MetarObservation,
    OrderbookLevel,
    PriceSnapshot,
    Signal,
    Station,
    SystemHeartbeat,
    TafReport,
)
from src.common.time import ensure_utc
from src.db.runtime import set_setting

router = APIRouter(prefix="/system", tags=["system"])


class TradingPauseRequest(BaseModel):
    paused: bool


@router.post(
    "/trading/pause",
    summary="设置交易暂停状态",
    description=(
        "手动暂停或恢复交易（kill switch）。\n\n"
        "**请求体：**\n"
        "- `paused` — true=暂停所有交易, false=恢复交易\n\n"
        "**返回字段：**\n"
        "- `key` — 设置项名称（trading_paused）\n"
        "- `value` — 当前值（true/false）\n"
        "- `updated_at` — 更新时间 (ISO 8601 UTC)"
    ),
)
def set_trading_pause(
    request: TradingPauseRequest,
    session: Session = Depends(session_dep),
) -> dict:
    setting = set_setting(session, "trading_paused", "true" if request.paused else "false")
    return {
        "data": {
            "key": setting.key,
            "value": setting.value,
            "updated_at": ensure_utc(setting.updated_at).isoformat(),
        },
        "error": None,
    }


@router.get(
    "/stats",
    summary="系统统计信息",
    description=(
        "返回系统运行状态的全局统计数据。这是监控系统健康度的核心端点，可以一目了然地判断各数据管道是否正常运行。\n\n"
        "**响应顶层结构：** `{\"data\": {...}, \"error\": null}`\n\n"
        "---\n\n"
        "**row_counts — 各数据表的行数**\n\n"
        "| 字段 | 说明 |\n"
        "| --- | --- |\n"
        "| `stations` | 系统管理的气象站总数（通常 5 个：Chicago/London/Miami/Paris/Seoul） |\n"
        "| `metar_observations` | METAR 地面观测记录总数。每个站点每小时约增加 1 条 |\n"
        "| `taf_reports` | TAF 终端预报总数。每个站点每 6 小时发布一份 |\n"
        "| `ensemble_runs` | Ensemble 预报运行次数。每次 forecast_fetcher 成功运行会为每个站点生成 1 条 |\n"
        "| `ensemble_forecasts` | Ensemble 预报成员级记录总数。每次运行 = 站点数 × 预报天数 × 成员数（如 5×7×31=1085） |\n"
        "| `markets` | 已入库的 Polymarket 天气市场总数（包含历史已过期的市场） |\n"
        "| `price_snapshots` | 价格快照总数。每 30 秒采集一次所有活跃市场 |\n"
        "| `orderbook_levels` | 订单簿层级记录总数。每次订单簿采集会记录所有 bid/ask 层级 |\n"
        "| `signals` | 信号总数（含 BUY/SELL/SKIP 所有类型） |\n\n"
        "---\n\n"
        "**time_ranges — 关键数据的时间跨度**\n\n"
        "每个子对象含 `earliest`（最早记录时间）和 `latest`（最新记录时间），均为 ISO 8601 UTC 格式。\n\n"
        "| 字段 | 说明 | 健康判断 |\n"
        "| --- | --- | --- |\n"
        "| `metar` | METAR 观测时间范围 | `latest` 应在 1-2 小时内，否则表示 weather_fetcher 停了 |\n"
        "| `snapshots` | 价格快照时间范围 | `latest` 应在 1 分钟内，否则表示 market_fetcher 停了 |\n"
        "| `signals` | 信号生成时间范围 | `latest` 应在调度间隔内（通常 ≤3 小时），否则表示 signal_engine 停了 |\n\n"
        "---\n\n"
        "**heartbeats[] — Worker 心跳列表**\n\n"
        "每个 Worker 在每次成功/失败执行后记录一条心跳。通过对比 `recorded_at` 与当前时间可以判断 Worker 是否存活。\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `worker` | string | Worker 名称，可能值见下表 |\n"
        "| `status` | string | `ok`=最近一次执行成功，`error`=最近一次执行失败 |\n"
        "| `message` | string | 最近一次运行摘要。成功时包含统计信息（如 `stations=5 forecast_days=35`），失败时包含错误描述 |\n"
        "| `recorded_at` | string | 心跳记录时间 (ISO 8601 UTC)。**这是判断 Worker 是否存活的关键字段** |\n\n"
        "**Worker 名称说明：**\n\n"
        "| worker | 调度频率 | 职责 |\n"
        "| --- | --- | --- |\n"
        "| `weather_fetcher` | 每 15 分钟 | 从 NOAA AWC 抓取 METAR 观测和 TAF 预报 |\n"
        "| `market_fetcher` | 每 30 秒 | 从 Polymarket 抓取市场列表和最新价格 |\n"
        "| `orderbook_fetcher` | 每 5 分钟 | 从 Polymarket 抓取完整订单簿快照 |\n"
        "| `forecast_fetcher` | 每 3 小时 | 从 Open-Meteo 抓取 GFS ensemble 集合预报。**如果此 Worker 停止超过 24 小时，所有信号将因 forecast_stale 被降级为 SKIP** |\n"
        "| `signal_engine` | 每 30 秒 | 对比模型概率与市场概率，生成交易信号 |\n"
        "| `data_cleanup` | 每 6 小时 | 清理过期的 METAR 和价格快照数据，防止数据库膨胀 |"
    ),
)
def system_stats(session: Session = Depends(session_dep)) -> dict:
    def _count(model):
        return session.exec(select(func.count()).select_from(model)).one()

    def _time_range(model, col):
        min_val = session.exec(select(func.min(col))).one()
        max_val = session.exec(select(func.max(col))).one()
        return {
            "earliest": ensure_utc(min_val).isoformat() if min_val else None,
            "latest": ensure_utc(max_val).isoformat() if max_val else None,
        }

    heartbeats = session.exec(
        select(SystemHeartbeat).order_by(SystemHeartbeat.recorded_at.desc())
    ).all()

    return {
        "data": {
            "row_counts": {
                "stations": _count(Station),
                "metar_observations": _count(MetarObservation),
                "taf_reports": _count(TafReport),
                "ensemble_runs": _count(EnsembleRun),
                "ensemble_forecasts": _count(EnsembleForecast),
                "markets": _count(Market),
                "price_snapshots": _count(PriceSnapshot),
                "orderbook_levels": _count(OrderbookLevel),
                "signals": _count(Signal),
            },
            "time_ranges": {
                "metar": _time_range(MetarObservation, MetarObservation.observed_at),
                "snapshots": _time_range(PriceSnapshot, PriceSnapshot.captured_at),
                "signals": _time_range(Signal, Signal.signal_at),
            },
            "heartbeats": [
                {
                    "worker": hb.worker_name,
                    "status": hb.status,
                    "message": hb.message,
                    "recorded_at": ensure_utc(hb.recorded_at).isoformat(),
                }
                for hb in heartbeats
            ],
        },
        "error": None,
    }
