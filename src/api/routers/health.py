from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.settings import get_settings
from src.db.models import SystemHeartbeat

router = APIRouter(tags=["health"])


@router.get("/health")
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
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in heartbeats[:10]
            ],
        },
        "error": None,
    }

