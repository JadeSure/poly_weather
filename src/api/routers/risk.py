from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.common.settings import get_settings
from src.db.models import Position, RiskEvent
from src.db.runtime import get_setting

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/state")
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
                    "triggered_at": event.triggered_at.isoformat(),
                }
                for event in recent_events
            ],
        },
        "error": None,
    }

