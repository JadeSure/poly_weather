from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlmodel import Session, select

from src.common.time import ensure_utc, utc_now
from src.db.models import (
    EnsembleForecast,
    EnsembleRun,
    Market,
    MetarObservation,
    Position,
    PriceSnapshot,
    Signal,
    Station,
)
from src.engine.probability import Bucket, build_bucket_distribution
from src.engine.rounding import settlement_temperature
from src.engine.signal_filters import SignalFilterContext, is_tradeable
from src.market.contract_parser import is_highest_temp_market
from src.engine.trend_adjustment import (
    TemperatureObservation,
    TrendAdjustmentResult,
    apply_market_day_adjustment,
)


@dataclass(slots=True)
class SignalDecision:
    action: str
    edge: float
    is_actionable: bool
    reason: str


@dataclass(slots=True)
class SignalRunResult:
    generated: int
    actionable: int
    skipped: int


def compute_edge(model_probability: float, market_probability: float) -> float:
    return model_probability - market_probability


def generate_signal(
    model_probability: float,
    market_probability: float,
    has_position: bool = False,
    buy_threshold: float = 0.15,
    sell_threshold: float = -0.15,
) -> SignalDecision:
    edge = compute_edge(model_probability=model_probability, market_probability=market_probability)

    if edge > buy_threshold:
        return SignalDecision(
            action="BUY",
            edge=edge,
            is_actionable=True,
            reason="Model probability exceeds market probability by threshold.",
        )

    if has_position and edge < sell_threshold:
        return SignalDecision(
            action="SELL",
            edge=edge,
            is_actionable=True,
            reason="Held position has turned sufficiently unfavorable.",
        )

    return SignalDecision(
        action="SKIP",
        edge=edge,
        is_actionable=False,
        reason="Edge does not meet execution threshold.",
    )


def sync_signals(
    session: Session,
    forecast_horizon_days: int = 7,
    dedup_window_minutes: int = 30,
) -> SignalRunResult:
    latest_supported_date = utc_now().date() + timedelta(days=forecast_horizon_days)
    markets = session.exec(select(Market).where(Market.status == "active")).all()
    stations = {station.city_code: station for station in session.exec(select(Station)).all()}

    grouped_markets: dict[tuple[str, object, str | None], list[Market]] = defaultdict(list)
    for market in markets:
        if market.forecast_date_local is None or market.forecast_date_local > latest_supported_date:
            continue
        if not is_highest_temp_market(market.question):
            continue
        grouped_markets[(market.city_code, market.forecast_date_local, market.bucket_unit)].append(market)

    generated = 0
    actionable = 0
    skipped = 0
    for _, group in grouped_markets.items():
        signal_rows = build_group_signal_rows(session, group, stations.get(group[0].city_code))
        signal_rows = apply_group_selection(signal_rows)
        for signal_row in signal_rows:
            if not should_persist_signal(
                session,
                signal_row,
                dedup_window_minutes=dedup_window_minutes,
            ):
                continue
            session.add(signal_row)
            generated += 1
            actionable += 1 if signal_row.is_actionable else 0
            skipped += 0 if signal_row.is_actionable else 1

    session.commit()
    return SignalRunResult(generated=generated, actionable=actionable, skipped=skipped)


def build_group_signal_rows(
    session: Session,
    markets: list[Market],
    station: Station | None,
) -> list[Signal]:
    rows: list[Signal] = []
    if not markets:
        return rows

    forecast_date_local = markets[0].forecast_date_local
    now = utc_now()
    market_prob_results = {market.id: load_market_probability(session, market.id) for market in markets}
    if station is None:
        return [
            build_skip_signal(market.id, _prob_value(market_prob_results.get(market.id)), "missing_station")
            for market in markets
            if market.id is not None
        ]

    recent_observations = load_recent_observations(session, station.id)
    latest_observation = load_latest_metar_observation(session, station.id)

    forecast_result = load_latest_daily_forecast_members(
        session,
        station_id=station.id,
        forecast_date_local=forecast_date_local,
    )
    if not forecast_result.members:
        return [
            build_skip_signal(market.id, _prob_value(market_prob_results.get(market.id)), "missing_forecast")
            for market in markets
            if market.id is not None
        ]

    forecast_age_seconds = None
    if forecast_result.fetched_at is not None:
        forecast_age_seconds = (now - ensure_utc(forecast_result.fetched_at)).total_seconds()

    unit = markets[0].bucket_unit or station.settlement_unit
    adjusted = apply_market_day_adjustment(
        ensemble_members_c=forecast_result.members,
        target_date_local=forecast_date_local,
        timezone_name=station.timezone_name,
        observations=recent_observations,
    )
    group_probabilities = build_group_probabilities(markets, adjusted.adjusted_members_c, unit)

    for market in markets:
        prob_result = market_prob_results.get(market.id)
        if market.id is None:
            continue
        if prob_result is None:
            rows.append(build_skip_signal(market.id, 0.0, "missing_market_price"))
            continue

        market_probability = prob_result.probability
        market_age_seconds = None
        if prob_result.captured_at is not None:
            market_age_seconds = (now - ensure_utc(prob_result.captured_at)).total_seconds()

        bucket_probability_value = group_probabilities.get(market.id)
        if bucket_probability_value is None:
            rows.append(build_skip_signal(market.id, market_probability, "missing_bucket_probability"))
            continue

        tradeable, tradeable_reason = is_tradeable(
            SignalFilterContext(
                settlement_at=resolve_market_settlement_at(market),
                is_liquid=is_liquid_market(session, market.id),
                is_weather_stale=latest_observation.is_stale if latest_observation else True,
                station_match_valid=market.station_match_valid,
                forecast_age_seconds=forecast_age_seconds,
            )
        )
        decision = generate_signal(
            model_probability=bucket_probability_value,
            market_probability=market_probability,
            has_position=has_open_position(session, market.id),
        )
        final_action = decision.action if tradeable else "SKIP"
        final_reason = decision.reason if tradeable else tradeable_reason
        rows.append(
            build_signal_row(
                market=market,
                model_probability=bucket_probability_value,
                market_probability=market_probability,
                decision=decision,
                final_action=final_action,
                final_reason=final_reason,
                is_actionable=decision.is_actionable and tradeable,
                trend_result=adjusted,
                latest_observation=latest_observation,
                group_size=len(markets),
                forecast_age_seconds=forecast_age_seconds,
                market_age_seconds=market_age_seconds,
            )
        )
    return rows


def build_group_probabilities(
    markets: list[Market],
    adjusted_members_c: list[float],
    unit: str,
) -> dict[int, float]:
    bucketed_markets = [
        (market, build_bucket_for_market(market))
        for market in sorted(markets, key=market_sort_key)
    ]
    bucketed_markets = [(market, bucket) for market, bucket in bucketed_markets if bucket is not None]
    if not bucketed_markets:
        return {}

    distribution = build_bucket_distribution(
        adjusted_members_c,
        [bucket for _, bucket in bucketed_markets],
        unit,
    )
    probabilities: dict[int, float] = {}
    for (market, _), item in zip(bucketed_markets, distribution, strict=False):
        if market.id is not None:
            probabilities[market.id] = item.probability
    return probabilities


def apply_group_selection(signal_rows: list[Signal]) -> list[Signal]:
    actionable_rows = [
        row
        for row in signal_rows
        if row.is_actionable and row.signal_type in {"BUY", "SELL"}
    ]
    if len(actionable_rows) <= 1:
        return signal_rows

    best_row = max(actionable_rows, key=lambda row: abs(row.edge_bps))
    best_payload = extract_reasoning(best_row.reasoning_json)
    best_bucket = best_payload.get("bucket_label")
    for row in actionable_rows:
        if row.market_id == best_row.market_id:
            continue
        payload = extract_reasoning(row.reasoning_json)
        payload["reason"] = "group_dominated"
        payload["group_best_market_id"] = best_row.market_id
        payload["group_best_bucket"] = best_bucket
        row.signal_type = "SKIP"
        row.is_actionable = False
        row.reasoning_json = json.dumps(payload, ensure_ascii=True)
    return signal_rows


def should_persist_signal(
    session: Session,
    signal_row: Signal,
    dedup_window_minutes: int = 30,
    edge_tolerance_bps: int = 50,
    probability_tolerance: float = 0.02,
) -> bool:
    latest = _find_latest_pending_signal(session, signal_row.market_id)
    if latest is None:
        with session.no_autoflush:
            latest = session.exec(
                select(Signal)
                .where(Signal.market_id == signal_row.market_id)
                .order_by(Signal.signal_at.desc())
            ).first()
    if latest is None:
        return True
    if ensure_utc(latest.signal_at) < utc_now() - timedelta(minutes=dedup_window_minutes):
        return True
    if latest.signal_type != signal_row.signal_type or latest.is_actionable != signal_row.is_actionable:
        return True
    if abs(latest.edge_bps - signal_row.edge_bps) > edge_tolerance_bps:
        return True
    if abs(latest.model_probability - signal_row.model_probability) > probability_tolerance:
        return True
    if abs(latest.market_probability - signal_row.market_probability) > probability_tolerance:
        return True
    if extract_reasoning(latest.reasoning_json).get("reason") != extract_reasoning(signal_row.reasoning_json).get("reason"):
        return True
    return False


def _prob_value(result: MarketProbabilityResult | None) -> float:
    return result.probability if result is not None else 0.0


def build_signal_row(
    market: Market,
    model_probability: float,
    market_probability: float,
    decision: SignalDecision,
    final_action: str,
    final_reason: str,
    is_actionable: bool,
    trend_result: TrendAdjustmentResult,
    latest_observation: MetarObservation | None,
    group_size: int,
    forecast_age_seconds: float | None = None,
    market_age_seconds: float | None = None,
) -> Signal:
    return Signal(
        market_id=market.id,
        signal_at=utc_now(),
        signal_type=final_action,
        model_probability=model_probability,
        market_probability=market_probability,
        edge_bps=int(round(decision.edge * 10000)),
        confidence=min(1.0, abs(decision.edge) / 0.25),
        reasoning_json=json.dumps(
            {
                "reason": final_reason,
                "market_question": market.question,
                "bucket_label": market.bucket_label,
                "group_size": group_size,
                "latest_observation_c": latest_observation.temperature_c if latest_observation else None,
                "same_day_adjustment": trend_result.same_day,
                "recent_trend_c_per_hour": round(trend_result.recent_trend_c_per_hour, 4),
                "applied_adjustment_c": round(trend_result.applied_adjustment_c, 4),
                "applied_floor_c": trend_result.applied_floor_c,
                "forecast_age_seconds": round(forecast_age_seconds) if forecast_age_seconds is not None else None,
                "market_age_seconds": round(market_age_seconds) if market_age_seconds is not None else None,
            },
            ensure_ascii=True,
        ),
        is_actionable=is_actionable,
    )


def market_sort_key(market: Market) -> tuple[float, float]:
    lower = float("-inf") if market.bucket_low is None else float(market.bucket_low)
    upper = float("inf") if market.bucket_high is None else float(market.bucket_high)
    return (lower, upper)


def build_bucket_for_market(market: Market) -> Bucket | None:
    if market.bucket_label is None:
        return None
    return Bucket(label=market.bucket_label, low=market.bucket_low, high=market.bucket_high)


def bucket_probability(ensemble_members_c: list[float], bucket: Bucket, unit: str) -> float:
    if not ensemble_members_c:
        return 0.0
    hits = 0
    for value in ensemble_members_c:
        if bucket.contains(settlement_temperature(value, unit)):
            hits += 1
    return hits / len(ensemble_members_c)


def apply_observation_floor(
    ensemble_members_c: list[float],
    latest_observation_c: float | None,
) -> list[float]:
    if latest_observation_c is None:
        return list(ensemble_members_c)
    return [max(value, latest_observation_c) for value in ensemble_members_c]


@dataclass(slots=True)
class MarketProbabilityResult:
    probability: float
    captured_at: datetime | None


def load_market_probability(session: Session, market_id: int | None) -> MarketProbabilityResult | None:
    if market_id is None:
        return None
    snapshot = session.exec(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.captured_at.desc())
    ).first()
    if snapshot is None:
        return None
    prob = snapshot.yes_mid or snapshot.yes_bid or snapshot.yes_ask
    if prob is None:
        return None
    return MarketProbabilityResult(probability=prob, captured_at=snapshot.captured_at)


def load_recent_observations(
    session: Session,
    station_id: int | None,
    limit: int = 3,
) -> list[TemperatureObservation]:
    if station_id is None:
        return []
    rows = session.exec(
        select(MetarObservation)
        .where(MetarObservation.station_id == station_id, MetarObservation.temperature_c.is_not(None))
        .order_by(MetarObservation.observed_at.desc())
        .limit(limit)
    ).all()
    return [
        TemperatureObservation(observed_at=row.observed_at, temperature_c=row.temperature_c)
        for row in rows
        if row.temperature_c is not None
    ]


def load_latest_metar_observation(
    session: Session,
    station_id: int | None,
) -> MetarObservation | None:
    if station_id is None:
        return None
    return session.exec(
        select(MetarObservation)
        .where(MetarObservation.station_id == station_id)
        .order_by(MetarObservation.observed_at.desc())
    ).first()


@dataclass(slots=True)
class ForecastMembersResult:
    members: list[float]
    fetched_at: datetime | None


def load_latest_daily_forecast_members(
    session: Session,
    station_id: int | None,
    forecast_date_local,
) -> ForecastMembersResult:
    if station_id is None or forecast_date_local is None:
        return ForecastMembersResult(members=[], fetched_at=None)
    latest_run = session.exec(
        select(EnsembleRun)
        .where(EnsembleRun.station_id == station_id)
        .order_by(EnsembleRun.fetched_at.desc())
    ).first()
    if latest_run is None:
        return ForecastMembersResult(members=[], fetched_at=None)
    rows = session.exec(
        select(EnsembleForecast)
        .where(
            EnsembleForecast.ensemble_run_id == latest_run.id,
            EnsembleForecast.forecast_date_local == forecast_date_local,
        )
        .order_by(EnsembleForecast.member_index.asc())
    ).all()
    return ForecastMembersResult(
        members=[row.max_temp_c for row in rows],
        fetched_at=latest_run.fetched_at,
    )


def is_liquid_market(session: Session, market_id: int | None, minimum_depth_usdc: float = 50.0) -> bool:
    if market_id is None:
        return False
    snapshot = session.exec(
        select(PriceSnapshot)
        .where(PriceSnapshot.market_id == market_id)
        .order_by(PriceSnapshot.captured_at.desc())
    ).first()
    if snapshot is None or snapshot.total_depth_usdc is None:
        return False
    return snapshot.total_depth_usdc >= minimum_depth_usdc


def has_open_position(session: Session, market_id: int | None) -> bool:
    if market_id is None:
        return False
    position = session.exec(
        select(Position).where(Position.market_id == market_id, Position.status == "open")
    ).first()
    return position is not None


def resolve_market_settlement_at(market: Market) -> datetime:
    if market.end_at is not None:
        return ensure_utc(market.end_at)
    if market.forecast_date_local is not None:
        return datetime.combine(market.forecast_date_local, time(23, 59), tzinfo=timezone.utc)
    return utc_now()


def build_skip_signal(market_id: int | None, market_probability: float, reason: str) -> Signal:
    return Signal(
        market_id=market_id,
        signal_at=utc_now(),
        signal_type="SKIP",
        model_probability=0.0,
        market_probability=market_probability,
        edge_bps=0,
        confidence=0.0,
        reasoning_json=json.dumps({"reason": reason}, ensure_ascii=True),
        is_actionable=False,
    )


def extract_reasoning(reasoning_json: str | None) -> dict:
    if not reasoning_json:
        return {}
    try:
        payload = json.loads(reasoning_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_latest_pending_signal(session: Session, market_id: int | None) -> Signal | None:
    pending_signals = [
        instance
        for instance in session.new
        if isinstance(instance, Signal) and instance.market_id == market_id
    ]
    if not pending_signals:
        return None
    return max(pending_signals, key=lambda signal: ensure_utc(signal.signal_at))
