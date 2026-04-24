import json
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.time import ensure_utc
from src.db.models import Market, Signal

router = APIRouter(prefix="/signals", tags=["signals"])


def _extract_skip_reason(reasoning_json: str | None) -> str | None:
    if not reasoning_json:
        return None
    try:
        payload = json.loads(reasoning_json)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload.get("reason")
    return None


@router.get(
    "",
    summary="列出交易信号",
    description=(
        "返回系统生成的交易信号列表，按生成时间**倒序**排列（最新在前）。\n\n"
        "**信号生成原理：**\n"
        "1. 对于每个活跃市场（每个城市×日期×温度bucket），系统计算「模型概率」和「市场概率」\n"
        "2. **模型概率** = 31 个 ensemble 成员中，预测日最高温落入该 bucket 的成员数 / 31。"
        "例如 13 个成员预测温度在 68-69°F → model_probability = 13/31 ≈ 0.419\n"
        "3. **市场概率** = 该 bucket 对应的 YES 代币中间价（yes_mid），反映市场定价\n"
        "4. **Edge** = model_probability - market_probability。正值表示模型认为市场低估了该 bucket 发生的概率\n"
        "5. 当 edge > 15%（1500 bps）且通过所有过滤条件时，信号标记为 BUY + is_actionable=true\n\n"
        "**过滤条件（任一不满足则 SKIP）：**\n"
        "- 距结算时间 ≥ 6 小时\n"
        "- 订单簿深度 ≥ 50 USDC\n"
        "- METAR 观测数据未过期\n"
        "- 站点匹配有效（station_match_valid=true）\n"
        "- 预报数据未过期（fetched_at 距今 < 24 小时）\n"
        "- 同 family 内未被更优 bucket 覆盖\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `id` | integer | 信号内部 ID，自增主键 |\n"
        "| `internal_market_id` | integer | 内部数据库市场 ID（外键）。仅用于调试和数据库关联，外部使用者应使用 `market_id` |\n"
        "| `market_id` | string \\| null | **Polymarket 外部合约 ID**（如 `2040295`），与 `/markets/active` 返回的 `market_id` 一致，可直接用于 Polymarket 查询。null 表示关联市场已被删除 |\n"
        "| `question` | string \\| null | 合约问题文本（如 `Will the highest temperature in Chicago be between 68-69°F on April 25?`） |\n"
        "| `city_code` | string \\| null | 城市标识符（如 `chicago`） |\n"
        "| `station_match_valid` | boolean \\| null | 该市场的站点匹配是否有效。为 `false` 时，该市场的所有信号均为 SKIP，其 edge 值不可信 |\n"
        "| `signal_type` | string | 信号类型：`BUY`（模型概率显著高于市场，建议买入 YES）、`SELL`（持仓方向不利，建议卖出）、`SKIP`（不操作） |\n"
        "| `model_probability` | float | 模型预测概率（0-1）。计算方式：ensemble 31 个成员中落入该 bucket 的比例。例如 0.41935 = 13/31。对于 SKIP 信号中因 missing_forecast/missing_station 跳过的，此值为 0.0 |\n"
        "| `market_probability` | float | 市场隐含概率（0-1）。取自该合约最新 YES 代币中间价（yes_mid）。例如 0.006 表示市场认为该 bucket 只有 0.6% 概率发生 |\n"
        "| `edge_bps` | integer | Edge 值（基点，1 bp = 0.01%）。计算公式：`round((model_probability - market_probability) × 10000)`。正值=模型看多，负值=模型看空。例如 `4134` 表示模型概率比市场价格高 41.34 个百分点 |\n"
        "| `is_actionable` | boolean | 是否可操作。`true` 表示该信号通过了所有过滤条件且 edge 超过阈值（±1500 bps），理论上可以下单。`false` 表示因某种原因被跳过 |\n"
        "| `skip_reason` | string \\| null | 跳过原因，仅当 `is_actionable=false` 时返回。可能值见下表。当 `is_actionable=true` 时固定为 null |\n"
        "| `signal_at` | string | 信号生成时间 (ISO 8601 UTC，如 `2026-04-24T06:26:22.133755+00:00`) |\n\n"
        "**skip_reason 枚举值详解：**\n\n"
        "| 值 | 含义 |\n"
        "| --- | --- |\n"
        "| `missing_station` | 该市场的 city_code 无法匹配到系统中的任何气象站 |\n"
        "| `missing_forecast` | 该站点/日期组合没有可用的 ensemble 预报数据 |\n"
        "| `missing_market_price` | 该合约没有价格快照（从未被 Polymarket 采集到价格） |\n"
        "| `missing_bucket_probability` | 无法将合约的温度区间映射到 ensemble 分布上（通常因 bucket 解析失败） |\n"
        "| `less_than_min_hours_to_settlement` | 距合约结算时间不足 6 小时，市场即将关闭，不宜新建仓位 |\n"
        "| `insufficient_liquidity` | 合约订单簿总深度 < 50 USDC，流动性不足以执行交易 |\n"
        "| `weather_data_stale` | 该站点的 METAR 观测数据超过 3 小时未更新 |\n"
        "| `station_mapping_invalid` | 合约结算源 URL 中的 ICAO 站点代码与系统绑定的站点不匹配 |\n"
        "| `forecast_stale` | Ensemble 预报数据超过 24 小时未刷新，模型概率不可信 |\n"
        "| `group_dominated` | 同一 family（城市+日期+单位）内有另一个 bucket 的 edge 更大，此 bucket 被让位 |\n"
        "| `Edge does not meet execution threshold.` | Edge 绝对值未达到 ±1500 bps 的执行阈值 |"
    ),
)
def list_signals(
    actionable: bool | None = Query(default=None, description="按是否可操作过滤：true=仅可操作, false=仅跳过"),
    city_code: str | None = Query(default=None, description="按城市代码过滤（如 chicago, london）"),
    limit: int = Query(default=50, ge=1, le=200, description="返回信号数量上限"),
    session: Session = Depends(session_dep),
) -> dict:
    statement = select(Signal).order_by(Signal.signal_at.desc())
    if actionable is not None:
        statement = statement.where(Signal.is_actionable == actionable)
    if city_code is not None:
        market_ids = [
            m.id for m in session.exec(
                select(Market).where(Market.city_code == city_code)
            ).all()
        ]
        if market_ids:
            statement = statement.where(Signal.market_id.in_(market_ids))
        else:
            return {"data": [], "error": None}
    signals = session.exec(statement.limit(limit)).all()

    market_cache: dict[int, Market] = {}

    def _get_market(mid: int) -> Market | None:
        if mid not in market_cache:
            market_cache[mid] = session.exec(
                select(Market).where(Market.id == mid)
            ).first()
        return market_cache[mid]

    return {
        "data": [
            {
                "id": signal.id,
                "internal_market_id": signal.market_id,
                "market_id": getattr(_get_market(signal.market_id), "polymarket_market_id", None),
                "question": getattr(_get_market(signal.market_id), "question", None),
                "city_code": getattr(_get_market(signal.market_id), "city_code", None),
                "station_match_valid": getattr(_get_market(signal.market_id), "station_match_valid", None),
                "signal_type": signal.signal_type,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge_bps": signal.edge_bps,
                "is_actionable": signal.is_actionable,
                "skip_reason": _extract_skip_reason(signal.reasoning_json) if not signal.is_actionable else None,
                "signal_at": ensure_utc(signal.signal_at).isoformat(),
            }
            for signal in signals
        ],
        "error": None,
    }


@router.get(
    "/summary",
    summary="信号统计摘要",
    description=(
        "按城市聚合所有信号的统计数据，提供信号质量和机会分布的全局视图。\n\n"
        "**重要：** `station_match_valid=false` 的城市（如当前的 Paris）的信号**不计入统计**。"
        "这些城市因站点映射无效，其 edge 值不可信，计入会虚假地拉高平均 edge 和信号总数。"
        "这些城市仍会出现在返回中，但 total_signals=0，station_match_valid=false。\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `city_code` | string | 城市标识符 |\n"
        "| `total_signals` | integer | 该城市的有效信号总数。仅统计 station_match_valid=true 的市场的信号 |\n"
        "| `actionable_signals` | integer | 可操作信号数（is_actionable=true 的信号计数） |\n"
        "| `avg_edge_bps` | integer | 所有信号的平均 |edge|（基点，取绝对值后平均）。反映该城市整体的市场定价偏差程度 |\n"
        "| `max_edge_bps` | integer | 单笔信号的最大 |edge|（基点）。反映该城市出现过的最极端定价偏差 |\n"
        "| `station_match_valid` | boolean | 该城市的站点匹配是否有效。为 `false` 时 total_signals 为 0（信号被排除），提示该城市数据源可能存在问题 |\n"
        "| `by_date` | array | 按预报日期细分的统计 |\n\n"
        "**by_date[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `date` | string | 预报日期 (YYYY-MM-DD)，对应 Polymarket 合约的结算日 |\n"
        "| `total` | integer | 该日信号数 |\n"
        "| `actionable` | integer | 该日可操作信号数 |\n"
        "| `avg_edge_bps` | integer | 该日平均 |edge|（基点） |"
    ),
)
def signal_summary(
    session: Session = Depends(session_dep),
) -> dict:
    signals = session.exec(select(Signal).order_by(Signal.signal_at.desc())).all()
    markets = {
        m.id: m for m in session.exec(select(Market)).all()
    }

    by_city: dict[str, dict] = defaultdict(lambda: {
        "total": 0,
        "actionable": 0,
        "edge_sum": 0,
        "max_edge": 0,
        "station_match_valid": True,
        "by_date": defaultdict(lambda: {"total": 0, "actionable": 0, "edge_sum": 0}),
    })

    for signal in signals:
        market = markets.get(signal.market_id)
        if market is None:
            continue
        if not market.station_match_valid:
            by_city[market.city_code]["station_match_valid"] = False
            continue
        city = market.city_code
        entry = by_city[city]
        entry["total"] += 1
        entry["edge_sum"] += abs(signal.edge_bps)
        entry["max_edge"] = max(entry["max_edge"], abs(signal.edge_bps))
        if signal.is_actionable:
            entry["actionable"] += 1

        date_key = str(market.forecast_date_local) if market.forecast_date_local else "unknown"
        day = entry["by_date"][date_key]
        day["total"] += 1
        day["edge_sum"] += abs(signal.edge_bps)
        if signal.is_actionable:
            day["actionable"] += 1

    summary = []
    for city, entry in sorted(by_city.items()):
        avg_edge = round(entry["edge_sum"] / entry["total"]) if entry["total"] > 0 else 0
        days = []
        for date_key, day in sorted(entry["by_date"].items()):
            days.append({
                "date": date_key,
                "total": day["total"],
                "actionable": day["actionable"],
                "avg_edge_bps": round(day["edge_sum"] / day["total"]) if day["total"] > 0 else 0,
            })
        summary.append({
            "city_code": city,
            "total_signals": entry["total"],
            "actionable_signals": entry["actionable"],
            "avg_edge_bps": avg_edge,
            "max_edge_bps": entry["max_edge"],
            "station_match_valid": entry["station_match_valid"],
            "by_date": days,
        })

    return {"data": summary, "error": None}
