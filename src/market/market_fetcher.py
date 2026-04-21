from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from src.common.settings import get_settings
from src.common.time import parse_utc_datetime, utc_now
from src.db.models import Market, MarketToken, OrderbookLevel, PriceSnapshot, Station
from src.market.contract_parser import build_outcome_token_map, parse_contract_payload
from src.market.polymarket_client import PolymarketClient


@dataclass(slots=True)
class MarketFetchResult:
    discovered: int
    upserted_markets: int
    saved_price_snapshots: int


async def sync_markets(
    session: Session,
    client: PolymarketClient | None = None,
    page_size: int = 100,
    max_pages: int = 3,
    max_markets_per_station: int = 8,
) -> MarketFetchResult:
    settings = get_settings()
    stations = session.exec(
        select(Station).where(Station.is_active.is_(True)).order_by(Station.city_name)
    ).all()
    market_client = client or PolymarketClient(
        api_base=settings.polymarket_api_base,
        gamma_api_base=settings.polymarket_gamma_api_base,
    )
    payloads = await market_client.list_weather_markets(
        stations=stations,
        page_size=page_size,
        max_pages=max_pages,
        max_markets_per_station=max_markets_per_station,
    )

    upserted = 0
    price_snapshots = 0
    for payload in payloads:
        market = upsert_market_payload(session, payload, stations)
        if market is None:
            continue
        upserted += 1

        token_map = build_outcome_token_map(payload)
        yes_token_id = token_map.get("Yes")
        no_token_id = token_map.get("No")
        if yes_token_id:
            upsert_market_token(session, market.id, 0, "Yes", yes_token_id)
        if no_token_id:
            upsert_market_token(session, market.id, 1, "No", no_token_id)
        if yes_token_id and no_token_id:
            yes_book = await market_client.get_orderbook(yes_token_id)
            no_book = await market_client.get_orderbook(no_token_id)
            save_price_snapshot(session, market.id, yes_book, no_book)
            price_snapshots += 1

    session.commit()
    return MarketFetchResult(
        discovered=len(payloads),
        upserted_markets=upserted,
        saved_price_snapshots=price_snapshots,
    )


async def run_market_loop() -> None:
    raise NotImplementedError("Scheduling is handled by src.worker.main.")


def upsert_market_payload(
    session: Session,
    payload: dict,
    stations: list[Station],
) -> Market | None:
    parsed = parse_contract_payload(payload, stations)
    if parsed.city_code is None:
        return None

    existing = session.exec(
        select(Market).where(Market.polymarket_market_id == str(payload.get("id")))
    ).first()
    if existing is None:
        existing = Market(
            polymarket_market_id=str(payload.get("id")),
            question=parsed.question,
            city_code=parsed.city_code,
        )

    existing.question = parsed.question
    existing.city_code = parsed.city_code
    existing.forecast_date_local = parsed.forecast_date_local
    existing.end_at = parse_utc_datetime(payload.get("endDate"))
    existing.bucket_label = parsed.bucket_label
    existing.bucket_low = parsed.bucket_low
    existing.bucket_high = parsed.bucket_high
    existing.bucket_unit = parsed.bucket_unit
    existing.settlement_url = payload.get("resolutionSource")
    existing.parsed_station_code = parsed.parsed_station_code
    existing.station_match_valid = _station_match(parsed.city_code, parsed.parsed_station_code, stations)
    existing.status = "active" if payload.get("active", True) and not payload.get("closed", False) else "closed"
    existing.updated_at = utc_now()
    existing.last_seen_at = utc_now()
    session.add(existing)
    session.flush()
    return existing


def upsert_market_token(
    session: Session,
    market_id: int | None,
    outcome_index: int,
    outcome_name: str,
    token_id: str,
) -> None:
    if market_id is None:
        return

    existing = session.exec(select(MarketToken).where(MarketToken.token_id == token_id)).first()
    if existing is None:
        existing = MarketToken(
            market_id=market_id,
            outcome_index=outcome_index,
            outcome_name=outcome_name,
            token_id=token_id,
        )
    else:
        existing.market_id = market_id
        existing.outcome_index = outcome_index
        existing.outcome_name = outcome_name
        existing.updated_at = utc_now()
    session.add(existing)


def save_price_snapshot(
    session: Session,
    market_id: int | None,
    yes_book: dict,
    no_book: dict,
) -> None:
    if market_id is None:
        return

    yes_bid = _best_bid(yes_book)
    yes_ask = _best_ask(yes_book)
    no_bid = _best_bid(no_book)
    no_ask = _best_ask(no_book)
    yes_mid = _midpoint(yes_bid, yes_ask, yes_book.get("last_trade_price"))
    no_mid = _midpoint(no_bid, no_ask, no_book.get("last_trade_price"))
    yes_spread = _spread(yes_bid, yes_ask)
    no_spread = _spread(no_bid, no_ask)
    total_depth = _total_depth(yes_book) + _total_depth(no_book)

    snapshot = PriceSnapshot(
        market_id=market_id,
        captured_at=utc_now(),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        yes_mid=yes_mid,
        yes_spread=yes_spread,
        no_bid=no_bid,
        no_ask=no_ask,
        no_mid=no_mid,
        no_spread=no_spread,
        total_depth_usdc=total_depth,
    )
    session.add(snapshot)
    session.flush()

    _save_orderbook_levels(session, snapshot.id, yes_book, "yes")
    _save_orderbook_levels(session, snapshot.id, no_book, "no")


def _best_bid(book: dict) -> float | None:
    levels = [_coerce_price(level.get("price")) for level in book.get("bids", [])]
    valid = [value for value in levels if value is not None]
    return max(valid) if valid else None


def _best_ask(book: dict) -> float | None:
    levels = [_coerce_price(level.get("price")) for level in book.get("asks", [])]
    valid = [value for value in levels if value is not None]
    return min(valid) if valid else None


def _midpoint(
    bid: float | None,
    ask: float | None,
    last_trade_price: str | float | None,
) -> float | None:
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, 6)
    if last_trade_price is None:
        return None
    return _coerce_price(last_trade_price)


def _coerce_price(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _save_orderbook_levels(
    session: Session,
    snapshot_id: int | None,
    book: dict,
    outcome: str,
) -> None:
    if snapshot_id is None:
        return
    for side_name, sort_reverse in [("bid", True), ("ask", False)]:
        levels = []
        for entry in book.get(f"{side_name}s", []):
            price = _coerce_price(entry.get("price"))
            size = _coerce_price(entry.get("size"))
            if price is not None and size is not None:
                levels.append((price, size))
        levels.sort(key=lambda x: x[0], reverse=sort_reverse)
        for idx, (price, size) in enumerate(levels):
            session.add(OrderbookLevel(
                snapshot_id=snapshot_id,
                side=side_name,
                outcome=outcome,
                price=price,
                size=size,
                level_index=idx,
            ))


def _spread(bid: float | None, ask: float | None) -> float | None:
    if bid is not None and ask is not None:
        return round(ask - bid, 6)
    return None


def _total_depth(book: dict) -> float:
    total = 0.0
    for side in ("bids", "asks"):
        for level in book.get(side, []):
            try:
                total += float(level.get("size", 0.0))
            except (TypeError, ValueError):
                continue
    return total


async def snapshot_all_orderbooks(
    session: Session,
    client: PolymarketClient | None = None,
) -> int:
    """Fetch orderbook snapshots for all active markets with tokens."""
    settings = get_settings()
    market_client = client or PolymarketClient(
        api_base=settings.polymarket_api_base,
        gamma_api_base=settings.polymarket_gamma_api_base,
    )

    markets_with_tokens = session.exec(
        select(Market, MarketToken)
        .join(MarketToken, MarketToken.market_id == Market.id)
        .where(Market.status == "active")
        .order_by(Market.id, MarketToken.outcome_index)
    ).all()

    # Group tokens by market_id
    token_map: dict[int, dict[str, str]] = {}
    for market, token in markets_with_tokens:
        if market.id not in token_map:
            token_map[market.id] = {}
        token_map[market.id][token.outcome_name] = token.token_id

    snapshots_saved = 0
    for market_id, tokens in token_map.items():
        yes_token = tokens.get("Yes")
        no_token = tokens.get("No")
        if not yes_token or not no_token:
            continue
        try:
            yes_book = await market_client.get_orderbook(yes_token)
            no_book = await market_client.get_orderbook(no_token)
            save_price_snapshot(session, market_id, yes_book, no_book)
            snapshots_saved += 1
        except Exception:
            continue

    session.commit()
    return snapshots_saved


def _station_match(city_code: str, parsed_station_code: str | None, stations: list[Station]) -> bool:
    if parsed_station_code is None:
        return False
    for station in stations:
        if station.city_code == city_code:
            return station.icao_code == parsed_station_code
    return False
