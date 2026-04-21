from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_utc_datetime(value: str | int | float | None) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        # Support both epoch seconds and milliseconds.
        epoch = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)
