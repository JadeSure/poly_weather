from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.settings import get_settings
from src.common.time import ensure_utc
from src.db.models import SystemHeartbeat

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="健康检查",
    description=(
        "返回系统健康状态和各 Worker 的最新心跳。\n\n"
        "**返回字段说明：**\n"
        "- `status` — 系统状态（ok）\n"
        "- `environment` — 运行环境（development / production）\n"
        "- `trading_mode` — 交易模式（paper / live / disabled）\n"
        "- `heartbeats[]` — 最近 10 个 Worker 心跳：\n"
        "  - `worker_name` — Worker 名称\n"
        "  - `status` — 状态（ok / error）\n"
        "  - `recorded_at` — 心跳时间 (ISO 8601 UTC)"
    ),
)
def health_check(session: Session = Depends(session_dep)) -> dict:
    settings = get_settings()
    heartbeats = session.exec(
        select(SystemHeartbeat).order_by(SystemHeartbeat.recorded_at.desc())
    ).all()
    return {
        "data": {
            "status": "ok",
            "environment": settings.app_env,
            "trading_mode": settings.trading_mode,
            "heartbeats": [
                {
                    "worker_name": item.worker_name,
                    "status": item.status,
                    "recorded_at": ensure_utc(item.recorded_at).isoformat(),
                }
                for item in heartbeats[:10]
            ],
        },
        "error": None,
    }

