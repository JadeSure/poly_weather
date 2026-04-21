from datetime import timedelta

from sqlmodel import Session, select

from src.common.time import utc_now
from src.db.models import (
    MetarObservation,
    OrderbookLevel,
    PriceSnapshot,
    SystemHeartbeat,
    SystemSetting,
)


def upsert_heartbeat(
    session: Session,
    worker_name: str,
    status: str = "ok",
    message: str | None = None,
) -> SystemHeartbeat:
    heartbeat = session.exec(
        select(SystemHeartbeat).where(SystemHeartbeat.worker_name == worker_name)
    ).first()
    if heartbeat is None:
        heartbeat = SystemHeartbeat(
            worker_name=worker_name,
            status=status,
            message=message,
        )
    else:
        heartbeat.status = status
        heartbeat.message = message
        heartbeat.recorded_at = utc_now()
    session.add(heartbeat)
    session.commit()
    session.refresh(heartbeat)
    return heartbeat


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    setting = session.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
    return setting.value if setting else default


def set_setting(session: Session, key: str, value: str) -> SystemSetting:
    setting = session.exec(select(SystemSetting).where(SystemSetting.key == key)).first()
    if setting is None:
        setting = SystemSetting(key=key, value=value)
    else:
        setting.value = value
        setting.updated_at = utc_now()
    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting


def cleanup_old_data(
    session: Session,
    metar_retention_days: int = 90,
    snapshot_retention_days: int = 60,
    orderbook_level_retention_days: int = 14,
) -> dict[str, int]:
    now = utc_now()
    metar_cutoff = now - timedelta(days=metar_retention_days)
    snapshot_cutoff = now - timedelta(days=snapshot_retention_days)
    level_cutoff = now - timedelta(days=orderbook_level_retention_days)

    old_metars = session.exec(
        select(MetarObservation).where(MetarObservation.observed_at < metar_cutoff)
    ).all()
    metar_deleted = len(old_metars)
    for row in old_metars:
        session.delete(row)

    # Delete orderbook levels for old snapshots first (FK dependency)
    old_snapshot_ids = [
        s.id for s in session.exec(
            select(PriceSnapshot).where(PriceSnapshot.captured_at < level_cutoff)
        ).all()
        if s.id is not None
    ]
    level_deleted = 0
    if old_snapshot_ids:
        old_levels = session.exec(
            select(OrderbookLevel).where(
                OrderbookLevel.snapshot_id.in_(old_snapshot_ids)
            )
        ).all()
        level_deleted = len(old_levels)
        for row in old_levels:
            session.delete(row)

    # Delete old snapshots (longer retention than levels)
    old_snapshots = session.exec(
        select(PriceSnapshot).where(PriceSnapshot.captured_at < snapshot_cutoff)
    ).all()
    snapshot_deleted = len(old_snapshots)
    for row in old_snapshots:
        session.delete(row)

    session.commit()
    return {
        "metar_deleted": metar_deleted,
        "snapshot_deleted": snapshot_deleted,
        "level_deleted": level_deleted,
    }

