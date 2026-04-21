from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.db.models import Market, OrderbookLevel, PriceSnapshot

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("/active")
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
                    "captured_at": latest_price.captured_at.isoformat(),
                    "yes_mid": latest_price.yes_mid,
                    "yes_spread": latest_price.yes_spread,
                    "no_mid": latest_price.no_mid,
                    "no_spread": latest_price.no_spread,
                    "total_depth_usdc": latest_price.total_depth_usdc,
                },
            }
        )
    return {"data": data, "error": None}


@router.get("/{market_id}/price-history")
def market_price_history(
    market_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
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
                    "captured_at": s.captured_at.isoformat(),
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


@router.get("/{market_id}/orderbook")
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
                "captured_at": latest_snapshot.captured_at.isoformat(),
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
