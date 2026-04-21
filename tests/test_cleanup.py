"""Tests for data retention cleanup."""

import unittest
from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from src.common.time import utc_now
from src.db.models import Market, MetarObservation, OrderbookLevel, PriceSnapshot, Station
from src.db.runtime import cleanup_old_data


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(Station(
                city_code="london", city_name="London", icao_code="EGLC",
                country_code="GB", timezone_name="Europe/London",
                settlement_unit="C", wunderground_station_code="EGLC",
            ))
            session.add(Market(
                polymarket_market_id="m1", question="test", city_code="london",
            ))
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_cleanup_removes_old_metars(self) -> None:
        now = utc_now()
        with Session(self.engine) as session:
            station = session.exec(select(Station)).one()
            session.add(MetarObservation(
                station_id=station.id,
                observed_at=now - timedelta(days=100),
                raw_report="old",
            ))
            session.add(MetarObservation(
                station_id=station.id,
                observed_at=now - timedelta(days=1),
                raw_report="recent",
            ))
            session.commit()
            result = cleanup_old_data(session, metar_retention_days=90)
        self.assertEqual(result["metar_deleted"], 1)
        with Session(self.engine) as session:
            remaining = session.exec(select(MetarObservation)).all()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].raw_report, "recent")

    def test_cleanup_removes_old_snapshots(self) -> None:
        now = utc_now()
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            session.add(PriceSnapshot(
                market_id=market.id,
                captured_at=now - timedelta(days=70),
            ))
            session.add(PriceSnapshot(
                market_id=market.id,
                captured_at=now - timedelta(days=5),
            ))
            session.commit()
            result = cleanup_old_data(session, snapshot_retention_days=60)
        self.assertEqual(result["snapshot_deleted"], 1)

    def test_cleanup_removes_old_orderbook_levels(self) -> None:
        now = utc_now()
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            old_snap = PriceSnapshot(
                market_id=market.id,
                captured_at=now - timedelta(days=20),
            )
            recent_snap = PriceSnapshot(
                market_id=market.id,
                captured_at=now - timedelta(days=1),
            )
            session.add(old_snap)
            session.add(recent_snap)
            session.commit()
            session.refresh(old_snap)
            session.refresh(recent_snap)
            session.add(OrderbookLevel(
                snapshot_id=old_snap.id, side="bid", outcome="yes",
                price=0.50, size=100.0, level_index=0,
            ))
            session.add(OrderbookLevel(
                snapshot_id=recent_snap.id, side="bid", outcome="yes",
                price=0.55, size=200.0, level_index=0,
            ))
            session.commit()
            result = cleanup_old_data(session, orderbook_level_retention_days=14)
        self.assertEqual(result["level_deleted"], 1)
        with Session(self.engine) as session:
            remaining = session.exec(select(OrderbookLevel)).all()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].price, 0.55)

    def test_cleanup_no_data_returns_zeros(self) -> None:
        with Session(self.engine) as session:
            result = cleanup_old_data(session)
        self.assertEqual(result["metar_deleted"], 0)
        self.assertEqual(result["snapshot_deleted"], 0)
        self.assertEqual(result["level_deleted"], 0)


if __name__ == "__main__":
    unittest.main()
