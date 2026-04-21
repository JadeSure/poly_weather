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
from src.db.runtime import set_setting

router = APIRouter(prefix="/system", tags=["system"])


class TradingPauseRequest(BaseModel):
    paused: bool


@router.post("/trading/pause")
def set_trading_pause(
    request: TradingPauseRequest,
    session: Session = Depends(session_dep),
) -> dict:
    setting = set_setting(session, "trading_paused", "true" if request.paused else "false")
    return {
        "data": {
            "key": setting.key,
            "value": setting.value,
            "updated_at": setting.updated_at.isoformat(),
        },
        "error": None,
    }


@router.get("/stats")
def system_stats(session: Session = Depends(session_dep)) -> dict:
    def _count(model):
        return session.exec(select(func.count()).select_from(model)).one()

    def _time_range(model, col):
        min_val = session.exec(select(func.min(col))).one()
        max_val = session.exec(select(func.max(col))).one()
        return {
            "earliest": min_val.isoformat() if min_val else None,
            "latest": max_val.isoformat() if max_val else None,
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
                    "recorded_at": hb.recorded_at.isoformat(),
                }
                for hb in heartbeats
            ],
        },
        "error": None,
    }
