from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.common.time import ensure_utc


@dataclass(slots=True)
class TemperatureObservation:
    observed_at: datetime
    temperature_c: float


@dataclass(slots=True)
class TrendAdjustmentResult:
    adjusted_members_c: list[float]
    same_day: bool
    recent_trend_c_per_hour: float
    applied_adjustment_c: float
    applied_floor_c: float | None


def compute_recent_temperature_trend_c_per_hour(
    observations: list[TemperatureObservation],
    max_lookback_hours: float = 4.0,
) -> float:
    valid = [item for item in observations if item.temperature_c is not None]
    if len(valid) < 2:
        return 0.0

    latest = valid[0]
    latest_at = ensure_utc(latest.observed_at)
    oldest = latest
    for candidate in valid[1:]:
        candidate_at = ensure_utc(candidate.observed_at)
        hours_diff = (latest_at - candidate_at).total_seconds() / 3600.0
        if 0 < hours_diff <= max_lookback_hours:
            oldest = candidate
        else:
            break

    oldest_at = ensure_utc(oldest.observed_at)
    hours_diff = (latest_at - oldest_at).total_seconds() / 3600.0
    if hours_diff <= 0:
        return 0.0
    return (latest.temperature_c - oldest.temperature_c) / hours_diff


def apply_market_day_adjustment(
    ensemble_members_c: list[float],
    target_date_local: date | None,
    timezone_name: str,
    observations: list[TemperatureObservation],
    peak_hour_local: float = 15.0,
    projection_cap_hours: float = 3.0,
    trend_weight: float = 0.6,
    clamp_abs_c: float = 2.5,
) -> TrendAdjustmentResult:
    if not ensemble_members_c or target_date_local is None:
        return TrendAdjustmentResult(
            adjusted_members_c=list(ensemble_members_c),
            same_day=False,
            recent_trend_c_per_hour=0.0,
            applied_adjustment_c=0.0,
            applied_floor_c=None,
        )

    valid = [item for item in observations if item.temperature_c is not None]
    if not valid:
        return TrendAdjustmentResult(
            adjusted_members_c=list(ensemble_members_c),
            same_day=False,
            recent_trend_c_per_hour=0.0,
            applied_adjustment_c=0.0,
            applied_floor_c=None,
        )

    latest = valid[0]
    latest_local = ensure_utc(latest.observed_at).astimezone(ZoneInfo(timezone_name))
    same_day = latest_local.date() == target_date_local
    if not same_day:
        return TrendAdjustmentResult(
            adjusted_members_c=list(ensemble_members_c),
            same_day=False,
            recent_trend_c_per_hour=0.0,
            applied_adjustment_c=0.0,
            applied_floor_c=None,
        )

    recent_trend = max(0.0, compute_recent_temperature_trend_c_per_hour(valid))
    current_hour = latest_local.hour + latest_local.minute / 60.0
    hours_remaining = min(max(0.0, peak_hour_local - current_hour), projection_cap_hours)
    adjustment_c = min(clamp_abs_c, recent_trend * hours_remaining * trend_weight)
    adjusted = [value + adjustment_c for value in ensemble_members_c]
    floor_c = latest.temperature_c
    adjusted = [max(value, floor_c) for value in adjusted]
    return TrendAdjustmentResult(
        adjusted_members_c=adjusted,
        same_day=True,
        recent_trend_c_per_hour=recent_trend,
        applied_adjustment_c=adjustment_c,
        applied_floor_c=floor_c,
    )
