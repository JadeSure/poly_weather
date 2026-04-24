from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.time import ensure_utc
from src.db.models import Position

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get(
    "",
    summary="列出所有持仓",
    description=(
        "返回系统中的所有持仓记录。\n\n"
        "**注意：** 当前系统尚未启用交易执行层，此端点通常返回空数组。\n\n"
        "**返回字段说明：**\n"
        "- `id` — 持仓内部 ID\n"
        "- `market_id` — 关联的内部市场 ID\n"
        "- `entry_side` — 入场方向（buy/sell）\n"
        "- `avg_entry_price` — 平均入场价格\n"
        "- `size` — 持仓大小\n"
        "- `exposure_usdc` — USDC 风险敞口\n"
        "- `status` — 持仓状态（open/closed）\n"
        "- `opened_at` — 开仓时间 (ISO 8601 UTC)"
    ),
)
def list_positions(session: Session = Depends(session_dep)) -> dict:
    positions = session.exec(select(Position).order_by(Position.opened_at.desc())).all()
    return {
        "data": [
            {
                "id": position.id,
                "market_id": position.market_id,
                "entry_side": position.entry_side,
                "avg_entry_price": position.avg_entry_price,
                "size": position.size,
                "exposure_usdc": position.exposure_usdc,
                "status": position.status,
                "opened_at": ensure_utc(position.opened_at).isoformat(),
            }
            for position in positions
        ],
        "error": None,
    }

