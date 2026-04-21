from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.db.models import Market, Signal

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(
    actionable: bool | None = Query(default=None),
    city_code: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
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
                "market_id": signal.market_id,
                "question": getattr(_get_market(signal.market_id), "question", None),
                "city_code": getattr(_get_market(signal.market_id), "city_code", None),
                "signal_type": signal.signal_type,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge_bps": signal.edge_bps,
                "is_actionable": signal.is_actionable,
                "signal_at": signal.signal_at.isoformat(),
            }
            for signal in signals
        ],
        "error": None,
    }


@router.get("/summary")
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
        "by_date": defaultdict(lambda: {"total": 0, "actionable": 0, "edge_sum": 0}),
    })

    for signal in signals:
        market = markets.get(signal.market_id)
        if market is None:
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
            "by_date": days,
        })

    return {"data": summary, "error": None}
