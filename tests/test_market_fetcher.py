"""Tests for market_fetcher: price helpers, upsert logic, and snapshot persistence."""

import unittest

from sqlmodel import Session, SQLModel, create_engine, select

from src.db.models import Market, MarketToken, PriceSnapshot, Station
from src.market.market_fetcher import (
    _best_ask,
    _best_bid,
    _midpoint,
    save_price_snapshot,
    upsert_market_payload,
    upsert_market_token,
)


def _make_stations_in_db(engine):
    stations_data = [
        dict(city_code="london", city_name="London", icao_code="EGLC",
             country_code="GB", timezone_name="Europe/London",
             settlement_unit="C", wunderground_station_code="EGLC"),
        dict(city_code="chicago", city_name="Chicago", icao_code="KORD",
             country_code="US", timezone_name="America/Chicago",
             settlement_unit="F", wunderground_station_code="KORD"),
        dict(city_code="seoul", city_name="Seoul", icao_code="RKSI",
             country_code="KR", timezone_name="Asia/Seoul",
             settlement_unit="C", wunderground_station_code="RKSI"),
    ]
    with Session(engine) as session:
        for s in stations_data:
            session.add(Station(**s))
        session.commit()


class MarketFetcherTests(unittest.TestCase):
    def test_best_prices_do_not_assume_ordering(self) -> None:
        book = {
            "bids": [
                {"price": "0.48", "size": "100"},
                {"price": "0.52", "size": "100"},
            ],
            "asks": [
                {"price": "0.99", "size": "100"},
                {"price": "0.53", "size": "100"},
            ],
        }
        self.assertEqual(_best_bid(book), 0.52)
        self.assertEqual(_best_ask(book), 0.53)

    def test_midpoint_falls_back_to_last_trade(self) -> None:
        self.assertEqual(_midpoint(None, None, "0.44"), 0.44)

    def test_midpoint_with_bid_and_ask(self) -> None:
        self.assertAlmostEqual(_midpoint(0.50, 0.60, None), 0.55, places=3)

    def test_midpoint_none_when_all_missing(self) -> None:
        self.assertIsNone(_midpoint(None, None, None))

    def test_best_bid_empty_book(self) -> None:
        self.assertIsNone(_best_bid({"bids": []}))

    def test_best_ask_empty_book(self) -> None:
        self.assertIsNone(_best_ask({"asks": []}))


class UpsertMarketPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        _make_stations_in_db(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_upsert_creates_new_market(self) -> None:
        payload = {
            "id": "market-001",
            "question": "Will the highest temperature in London exceed 16°C on April 8?",
            "description": "Settles based on wunderground.com/history/daily/gb/london/EGLC",
            "resolutionSource": "https://wunderground.com/history/daily/gb/london/EGLC",
            "endDateIso": "2026-04-08T23:59:00Z",
            "active": True,
            "closed": False,
        }
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            market = upsert_market_payload(session, payload, stations)
            session.commit()
            session.refresh(market)
            self.assertEqual(market.city_code, "london")
            self.assertTrue(market.station_match_valid)
            self.assertEqual(market.status, "active")

    def test_upsert_updates_existing_market(self) -> None:
        payload_v1 = {
            "id": "market-002",
            "question": "Will the highest temperature in Chicago be 50°F or higher on April 8?",
            "description": "temperature",
            "resolutionSource": "https://wunderground.com/history/daily/us/chicago/KORD",
            "endDateIso": "2026-04-08T23:59:00Z",
            "active": True,
            "closed": False,
        }
        payload_v2 = {**payload_v1, "active": False, "closed": True}
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            upsert_market_payload(session, payload_v1, stations)
            session.commit()
            upsert_market_payload(session, payload_v2, stations)
            session.commit()
            markets = session.exec(select(Market)).all()
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].status, "closed")

    def test_upsert_returns_none_for_unknown_city(self) -> None:
        payload = {
            "id": "market-003",
            "question": "Will the highest temperature in Tokyo exceed 25°C?",
            "description": "temperature",
            "resolutionSource": "",
            "endDateIso": "2026-04-08T23:59:00Z",
            "active": True,
            "closed": False,
        }
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            market = upsert_market_payload(session, payload, stations)
        self.assertIsNone(market)

    def test_station_match_invalid_when_code_mismatches(self) -> None:
        payload = {
            "id": "market-004",
            "question": "Will the highest temperature in London exceed 16°C on April 8?",
            "description": "temperature",
            "resolutionSource": "https://wunderground.com/history/daily/gb/london/EGLL",
            "endDateIso": "2026-04-08T23:59:00Z",
            "active": True,
            "closed": False,
        }
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            market = upsert_market_payload(session, payload, stations)
            session.commit()
            self.assertIsNotNone(market)
            session.refresh(market)
            self.assertFalse(market.station_match_valid)

    def test_seoul_market_with_celsius_bucket(self) -> None:
        payload = {
            "id": "market-005",
            "question": "Will the highest temperature in Seoul be between 24-25°C on April 10?",
            "description": "temperature",
            "resolutionSource": "https://wunderground.com/history/daily/kr/seoul/RKSI",
            "endDateIso": "2026-04-10T23:59:00Z",
            "active": True,
            "closed": False,
        }
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            market = upsert_market_payload(session, payload, stations)
            session.commit()
            self.assertIsNotNone(market)
            session.refresh(market)
            self.assertEqual(market.city_code, "seoul")
            self.assertEqual(market.bucket_low, 24)
            self.assertEqual(market.bucket_high, 25)
            self.assertEqual(market.bucket_unit, "C")
            self.assertTrue(market.station_match_valid)

    def test_forecast_date_parsed_from_question_text(self) -> None:
        payload = {
            "id": "market-006",
            "question": "Will the highest temperature in Chicago be 40°F on April 15?",
            "description": "temperature",
            "resolutionSource": "https://wunderground.com/history/daily/us/chicago/KORD",
            "endDateIso": "2026-04-16T12:00:00Z",
            "active": True,
            "closed": False,
        }
        with Session(self.engine) as session:
            stations = list(session.exec(select(Station)).all())
            market = upsert_market_payload(session, payload, stations)
            session.commit()
            self.assertIsNotNone(market)
            session.refresh(market)
            # Should parse "April 15" from question, not "2026-04-16" from endDateIso
            from datetime import date
            self.assertEqual(market.forecast_date_local, date(2026, 4, 15))


class UpsertMarketTokenTests(unittest.TestCase):
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

    def test_upsert_creates_token(self) -> None:
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            upsert_market_token(session, market.id, 0, "Yes", "token-yes-1")
            session.commit()
            tokens = session.exec(select(MarketToken)).all()
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].outcome_name, "Yes")

    def test_upsert_token_is_idempotent(self) -> None:
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            upsert_market_token(session, market.id, 0, "Yes", "token-yes-2")
            session.commit()
            upsert_market_token(session, market.id, 0, "Yes", "token-yes-2")
            session.commit()
            tokens = session.exec(select(MarketToken)).all()
        self.assertEqual(len(tokens), 1)

    def test_upsert_token_none_market_id_is_noop(self) -> None:
        with Session(self.engine) as session:
            upsert_market_token(session, None, 0, "Yes", "token-noop")
            session.commit()
            tokens = session.exec(select(MarketToken)).all()
        self.assertEqual(len(tokens), 0)


class SavePriceSnapshotTests(unittest.TestCase):
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

    def test_save_snapshot_from_orderbook(self) -> None:
        yes_book = {
            "bids": [{"price": "0.55", "size": "100"}, {"price": "0.50", "size": "200"}],
            "asks": [{"price": "0.60", "size": "150"}],
        }
        no_book = {
            "bids": [{"price": "0.35", "size": "80"}],
            "asks": [{"price": "0.45", "size": "120"}],
        }
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            save_price_snapshot(session, market.id, yes_book, no_book)
            session.commit()
            snapshots = session.exec(select(PriceSnapshot)).all()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].yes_bid, 0.55)
        self.assertEqual(snapshots[0].yes_ask, 0.60)
        self.assertAlmostEqual(snapshots[0].yes_mid, 0.575, places=3)
        self.assertAlmostEqual(snapshots[0].yes_spread, 0.05, places=3)
        self.assertAlmostEqual(snapshots[0].no_spread, 0.10, places=3)
        self.assertAlmostEqual(snapshots[0].total_depth_usdc, 650.0, places=1)

    def test_save_snapshot_with_empty_book(self) -> None:
        yes_book = {"bids": [], "asks": [], "last_trade_price": "0.52"}
        no_book = {"bids": [], "asks": [], "last_trade_price": "0.48"}
        with Session(self.engine) as session:
            market = session.exec(select(Market)).one()
            save_price_snapshot(session, market.id, yes_book, no_book)
            session.commit()
            snapshots = session.exec(select(PriceSnapshot)).all()
        self.assertEqual(len(snapshots), 1)
        self.assertIsNone(snapshots[0].yes_bid)
        self.assertEqual(snapshots[0].yes_mid, 0.52)

    def test_save_snapshot_none_market_id_is_noop(self) -> None:
        with Session(self.engine) as session:
            save_price_snapshot(session, None, {}, {})
            session.commit()
            snapshots = session.exec(select(PriceSnapshot)).all()
        self.assertEqual(len(snapshots), 0)


if __name__ == "__main__":
    unittest.main()
