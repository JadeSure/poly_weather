from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class SignalFilterContext:
    settlement_at: datetime
    is_liquid: bool
    is_weather_stale: bool
    station_match_valid: bool


def is_tradeable(
    context: SignalFilterContext,
    min_hours_to_settlement: int = 6,
) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    if context.settlement_at <= now + timedelta(hours=min_hours_to_settlement):
        return False, "less_than_min_hours_to_settlement"
    if not context.is_liquid:
        return False, "insufficient_liquidity"
    if context.is_weather_stale:
        return False, "weather_data_stale"
    if not context.station_match_valid:
        return False, "station_mapping_invalid"
    return True, "ok"

