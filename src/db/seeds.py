from pathlib import Path

import yaml
from sqlmodel import Session, select

from src.common.time import utc_now
from src.db.models import Station


def seed_stations(session: Session, stations_path: Path) -> int:
    if not stations_path.exists():
        return 0

    with stations_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}

    inserted = 0
    for item in payload.get("stations", []):
        existing = session.exec(
            select(Station).where(Station.icao_code == item["icao_code"])
        ).first()
        if existing:
            existing.city_name = item["city_name"]
            existing.city_code = item["city_code"]
            existing.country_code = item["country_code"]
            existing.timezone_name = item["timezone_name"]
            existing.settlement_unit = item["settlement_unit"]
            existing.wunderground_station_code = item["wunderground_station_code"]
            existing.latitude = item.get("latitude")
            existing.longitude = item.get("longitude")
            existing.is_active = bool(item.get("is_active", True))
            existing.updated_at = utc_now()
            session.add(existing)
            continue

        session.add(Station(**item))
        inserted += 1

    session.commit()
    return inserted

