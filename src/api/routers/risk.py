from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.settings import get_settings
from src.common.time import ensure_utc
from src.db.models import Position, RiskEvent
from src.db.runtime import get_setting

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get(
    "/state",
    summary="获取风控状态",
    description=(
        "返回当前系统的风控状态，包括交易开关、持仓信息和风控事件。\n\n"
        "**当前系统状态：** 系统处于「armed but idle」状态 —— 风控框架已就位，但交易执行层尚未实现"
        "（`execute_signal()` 会抛出 NotImplementedError）。因此 `open_positions` 始终为 0。\n\n"
        "**响应顶层结构：** `{\"data\": {...}, \"error\": null}`\n\n"
        "**data 对象字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `allow_new_trades` | boolean | 是否允许开新仓。= `!trading_paused`。当为 `false` 时，信号引擎仍会生成信号，但执行层（未来实现）不会下单 |\n"
        "| `trading_paused` | boolean | 交易是否被手动暂停。通过 `POST /system/trading/pause` 设置。这是人工 kill switch，紧急情况下可一键停止所有交易 |\n"
        "| `open_positions` | integer | 当前持有的未平仓头寸数量。当前系统无执行层，此值始终为 0 |\n"
        "| `max_concurrent_positions` | integer | 系统配置允许的最大同时持仓数（默认 20）。达到上限后不再开新仓 |\n"
        "| `recent_risk_events` | array | 最近 20 条风控事件记录 |\n\n"
        "**recent_risk_events[] 中每个对象的字段：**\n\n"
        "| 字段 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| `event_type` | string | 事件类型（如 position_limit_reached, unusual_edge_spike 等） |\n"
        "| `severity` | string | 严重程度：`info` / `warning` / `critical` |\n"
        "| `triggered_at` | string | 事件触发时间 (ISO 8601 UTC) |"
    ),
)
def risk_state(session: Session = Depends(session_dep)) -> dict:
    settings = get_settings()
    open_positions = session.exec(
        select(Position).where(Position.status == "open")
    ).all()
    recent_events = session.exec(
        select(RiskEvent).order_by(RiskEvent.triggered_at.desc()).limit(20)
    ).all()
    paused = get_setting(session, "trading_paused", "false") == "true"
    return {
        "data": {
            "allow_new_trades": not paused,
            "trading_paused": paused,
            "open_positions": len(open_positions),
            "max_concurrent_positions": settings.max_concurrent_positions,
            "recent_risk_events": [
                {
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "triggered_at": ensure_utc(event.triggered_at).isoformat(),
                }
                for event in recent_events
            ],
        },
        "error": None,
    }

