from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from src.api.deps import session_dep
from src.db.models import Position

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("")
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
                "opened_at": position.opened_at.isoformat(),
            }
            for position in positions
        ],
        "error": None,
    }

