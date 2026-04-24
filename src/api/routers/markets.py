from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.time import ensure_utc
from src.db.models import Market, OrderbookLevel, PriceSnapshot

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get(
    "/active",
    summary="列出所有活跃市场",
    description=(
        "返回系统中所有状态为 active 的 Polymarket 天气预测市场及其最新价格快照。\n\n"
        "**业务背景：** Polymarket 上的天气市场通常以「某城市某天最高温是否落入某温度区间」为标的。"
        "例如「Will the highest temperature in Chicago be between 68-69°F on April 25?」"
        "同一城市同一日期会有多个 bucket 组成一个 family（互斥事件组），所有 bucket 概率之和理论上为 1。\n\n"
        "**响应顶层结构：** `{\"data\": [...], \"error\": null}`\n\n"
        "**data[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `market_id` | string | Polymarket 外部合约 ID（如 `2040294`）。此 ID 可直接用于 Polymarket 网站或 API 查找对应合约。**注意：** `/signals` 端点也返回此字段（同为字符串），两处含义一致 |\n"
        "| `question` | string | 合约问题文本，如 `Will the highest temperature in Chicago be between 68-69°F on April 25?` |\n"
        "| `city_code` | string | 城市标识符（如 `chicago`），与 `/weather/stations` 中的 `city_code` 对应 |\n"
        "| `forecast_date_local` | string \\| null | 合约对应的本地日期（YYYY-MM-DD），即结算日。null 表示解析失败 |\n"
        "| `bucket_label` | string \\| null | 温度区间标签，从合约问题中解析。例如 `68-69°F`、`43°F`（精确值）、`84°F`（含 or higher） |\n"
        "| `bucket_low` | integer \\| null | 温度区间数值下界。null 表示开放下界（如「43°F or below」→ `bucket_low=null, bucket_high=43`） |\n"
        "| `bucket_high` | integer \\| null | 温度区间数值上界。null 表示开放上界（如「84°F or higher」→ `bucket_low=84, bucket_high=null`） |\n"
        "| `bucket_unit` | string \\| null | 温度区间单位：`F`（华氏）或 `C`（摄氏），从合约问题中解析 |\n"
        "| `station_match_valid` | boolean | **关键字段。** 表示合约 `resolutionSource`（结算数据源 URL）中指定的 ICAO 站点代码是否与系统绑定的站点匹配。为 `false` 时意味着系统的预报数据来源与合约的结算数据来源可能不一致，此市场的信号全部被强制 SKIP。当前 Paris 因此问题全部为 false |\n"
        "| `latest_price` | object \\| null | 最新一次价格快照，null 表示该市场尚无价格数据入库 |\n\n"
        "**latest_price 子字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `captured_at` | string | 价格采集时间 (ISO 8601 UTC)。系统每 30 秒抓取一次 |\n"
        "| `yes_mid` | float \\| null | YES 代币中间价，= (yes_bid + yes_ask) / 2，取值范围 0-1。**这就是市场隐含概率**，例如 0.35 表示市场认为该 bucket 有 35% 概率发生。null 表示订单簿为空 |\n"
        "| `yes_spread` | float \\| null | YES 代币买卖价差，= yes_ask - yes_bid。价差越小流动性越好。null 表示只有单边挂单或无挂单 |\n"
        "| `no_mid` | float \\| null | NO 代币中间价。理论上 yes_mid + no_mid ≈ 1（扣除手续费）。与 YES 方向相反 |\n"
        "| `no_spread` | float \\| null | NO 代币买卖价差 |\n"
        "| `total_depth_usdc` | float \\| null | 订单簿两侧总挂单金额（USDC）。反映市场流动性深度，低于 50 USDC 时该市场信号被标记为 SKIP（skip_reason=`insufficient_liquidity`） |"
    ),
)
def list_active_markets(session: Session = Depends(session_dep)) -> dict:
    markets = session.exec(select(Market).where(Market.status == "active")).all()
    data = []
    for market in markets:
        latest_price = session.exec(
            select(PriceSnapshot)
            .where(PriceSnapshot.market_id == market.id)
            .order_by(PriceSnapshot.captured_at.desc())
        ).first()
        data.append(
            {
                "market_id": market.polymarket_market_id,
                "question": market.question,
                "city_code": market.city_code,
                "forecast_date_local": str(market.forecast_date_local) if market.forecast_date_local else None,
                "bucket_label": market.bucket_label,
                "bucket_low": market.bucket_low,
                "bucket_high": market.bucket_high,
                "bucket_unit": market.bucket_unit,
                "station_match_valid": market.station_match_valid,
                "latest_price": None
                if latest_price is None
                else {
                    "captured_at": ensure_utc(latest_price.captured_at).isoformat(),
                    "yes_mid": latest_price.yes_mid,
                    "yes_spread": latest_price.yes_spread,
                    "no_mid": latest_price.no_mid,
                    "no_spread": latest_price.no_spread,
                    "total_depth_usdc": latest_price.total_depth_usdc,
                },
            }
        )
    return {"data": data, "error": None}


@router.get(
    "/{market_id}/price-history",
    summary="获取市场价格历史",
    description=(
        "返回指定市场的历史价格快照序列，按时间**正序**排列（最早在前），用于绘制价格走势图或分析市场定价变化。\n\n"
        "系统每 30 秒抓取一次所有活跃市场的价格，因此每个市场每天约有 ~2880 条快照。\n\n"
        "**路径参数：**\n\n"
        "| 参数 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `market_id` | string | Polymarket 外部合约 ID（与 `/markets/active` 返回的 `market_id` 一致） |\n\n"
        "**响应结构：** `{\"data\": {...}, \"error\": null}`。如果 market_id 不存在返回 `{\"data\": null, \"error\": \"market not found\"}`\n\n"
        "**data 对象字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `market_id` | string | Polymarket 合约 ID（回显） |\n"
        "| `question` | string | 合约问题文本 |\n"
        "| `city_code` | string | 城市标识符 |\n"
        "| `count` | integer | 返回的快照条数 |\n"
        "| `snapshots` | array | 价格快照序列（时间正序） |\n\n"
        "**snapshots[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `captured_at` | string | 采集时间 (ISO 8601 UTC) |\n"
        "| `yes_bid` | float \\| null | YES 代币最高买价。null 表示当时无买单 |\n"
        "| `yes_ask` | float \\| null | YES 代币最低卖价。null 表示当时无卖单 |\n"
        "| `yes_mid` | float \\| null | YES 代币中间价 = (bid+ask)/2，即市场隐含概率 |\n"
        "| `yes_spread` | float \\| null | YES 代币价差 = ask-bid，反映流动性 |\n"
        "| `no_bid` | float \\| null | NO 代币最高买价 |\n"
        "| `no_ask` | float \\| null | NO 代币最低卖价 |\n"
        "| `no_mid` | float \\| null | NO 代币中间价 |\n"
        "| `no_spread` | float \\| null | NO 代币价差 |\n"
        "| `total_depth_usdc` | float \\| null | 订单簿总深度 (USDC) |"
    ),
)
def market_price_history(
    market_id: str,
    limit: int = Query(default=500, ge=1, le=5000, description="返回快照数量上限"),
    session: Session = Depends(session_dep),
) -> dict:
    market = session.exec(
        select(Market).where(Market.polymarket_market_id == market_id)
    ).first()
    if market is None:
        return {"data": None, "error": "market not found"}

    snapshots = session.exec(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market.id)
        .order_by(PriceSnapshot.captured_at.desc())
        .limit(limit)
    ).all()

    return {
        "data": {
            "market_id": market.polymarket_market_id,
            "question": market.question,
            "city_code": market.city_code,
            "count": len(snapshots),
            "snapshots": [
                {
                    "captured_at": ensure_utc(s.captured_at).isoformat(),
                    "yes_bid": s.yes_bid,
                    "yes_ask": s.yes_ask,
                    "yes_mid": s.yes_mid,
                    "yes_spread": s.yes_spread,
                    "no_bid": s.no_bid,
                    "no_ask": s.no_ask,
                    "no_mid": s.no_mid,
                    "no_spread": s.no_spread,
                    "total_depth_usdc": s.total_depth_usdc,
                }
                for s in reversed(snapshots)  # chronological order
            ],
        },
        "error": None,
    }


@router.get(
    "/{market_id}/orderbook",
    summary="获取市场订单簿",
    description=(
        "返回指定市场最新的订单簿快照，包含 YES/NO 两侧的 bid/ask 完整挂单阶梯（ladder）。\n\n"
        "**什么是 Polymarket 订单簿？** 每个合约有 YES 和 NO 两种代币，各自有独立的买卖挂单。"
        "YES 代币价格 0.60 表示市场认为事件有 60% 概率发生。"
        "订单簿深度决定了你能以多少滑点执行交易。\n\n"
        "**路径参数：**\n\n"
        "| 参数 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `market_id` | string | Polymarket 外部合约 ID |\n\n"
        "**响应结构：** `{\"data\": {...}, \"error\": null}`\n\n"
        "**data 对象字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `market_id` | string | 合约 ID（回显） |\n"
        "| `question` | string | 合约问题文本 |\n"
        "| `snapshot` | object \\| null | 最新订单簿快照，null 表示无数据 |\n\n"
        "**snapshot 子字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `captured_at` | string | 采集时间 (ISO 8601 UTC) |\n"
        "| `yes_mid` | float \\| null | YES 代币中间价 |\n"
        "| `yes_spread` | float \\| null | YES 代币价差 |\n"
        "| `no_mid` | float \\| null | NO 代币中间价 |\n"
        "| `no_spread` | float \\| null | NO 代币价差 |\n"
        "| `total_depth_usdc` | float \\| null | 总挂单深度 (USDC) |\n"
        "| `yes` | object | YES 代币订单簿，包含 `bids` 和 `asks` 两个数组 |\n"
        "| `no` | object | NO 代币订单簿，包含 `bids` 和 `asks` 两个数组 |\n\n"
        "**bids[] / asks[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `price` | float | 挂单价格（0-1），如 0.35 表示愿意以 $0.35 买入/卖出一个代币 |\n"
        "| `size` | float | 挂单数量（代币数），代表在此价位可交易的量 |\n"
        "| `level` | integer | 层级编号，0=最优价（best bid/ask），1=次优，依次递增。bids 按价格从高到低排列，asks 按价格从低到高排列 |"
    ),
)
def market_orderbook(
    market_id: str,
    session: Session = Depends(session_dep),
) -> dict:
    market = session.exec(
        select(Market).where(Market.polymarket_market_id == market_id)
    ).first()
    if market is None:
        return {"data": None, "error": "market not found"}

    latest_snapshot = session.exec(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market.id)
        .order_by(PriceSnapshot.captured_at.desc())
    ).first()
    if latest_snapshot is None:
        return {
            "data": {"market_id": market_id, "snapshot": None},
            "error": None,
        }

    levels = session.exec(
        select(OrderbookLevel)
        .where(OrderbookLevel.snapshot_id == latest_snapshot.id)
        .order_by(OrderbookLevel.outcome, OrderbookLevel.side, OrderbookLevel.level_index)
    ).all()

    def _group_levels(outcome: str, side: str) -> list[dict]:
        return [
            {"price": lv.price, "size": lv.size, "level": lv.level_index}
            for lv in levels
            if lv.outcome == outcome and lv.side == side
        ]

    return {
        "data": {
            "market_id": market_id,
            "question": market.question,
            "snapshot": {
                "captured_at": ensure_utc(latest_snapshot.captured_at).isoformat(),
                "yes_mid": latest_snapshot.yes_mid,
                "yes_spread": latest_snapshot.yes_spread,
                "no_mid": latest_snapshot.no_mid,
                "no_spread": latest_snapshot.no_spread,
                "total_depth_usdc": latest_snapshot.total_depth_usdc,
                "yes": {
                    "bids": _group_levels("yes", "bid"),
                    "asks": _group_levels("yes", "ask"),
                },
                "no": {
                    "bids": _group_levels("no", "bid"),
                    "asks": _group_levels("no", "ask"),
                },
            },
        },
        "error": None,
    }
