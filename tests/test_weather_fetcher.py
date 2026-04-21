import asyncio
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from src.common.time import utc_now
from src.db.models import MetarObservation, Station, TafForecastPeriod, TafReport
from src.data import weather_fetcher
from src.data.weather_fetcher import (
    sync_weather,
    refresh_station_stale_flag,
    save_metar_payload,
    save_taf_payload,
)


class WeatherFetcherPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            station = Station(
                city_code="london",
                city_name="London",
                icao_code="EGLC",
                country_code="GB",
                timezone_name="Europe/London",
                settlement_unit="C",
                wunderground_station_code="EGLC",
            )
            session.add(station)
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_save_metar_payload_is_idempotent(self) -> None:
        payload = {
            "reportTime": "2026-04-08T12:00:00.000Z",
            "temp": 18.2,
            "dewp": 9.3,
            "wspd": 8,
            "wdir": 220,
            "altim": 1019.0,
            "visib": "9999",
            "rawOb": "METAR EGLC 081200Z 22008KT 9999 FEW040 18/09 Q1019",
        }
        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.icao_code == "EGLC")).one()
            self.assertEqual(save_metar_payload(session, station, payload), 1)
            self.assertEqual(save_metar_payload(session, station, payload), 0)
            session.commit()
            observations = session.exec(select(MetarObservation)).all()
            self.assertEqual(len(observations), 1)

    def test_save_taf_payload_creates_report_and_periods(self) -> None:
        payload = {
            "issueTime": "2026-04-08T11:20:00.000Z",
            "validTimeFrom": 1775649600,
            "validTimeTo": 1775736000,
            "rawTAF": "TAF EGLC 081120Z 0812/0912 19015KT P6SM BKN200",
            "fcsts": [
                {
                    "timeFrom": 1775649600,
                    "timeTo": 1775656800,
                    "timeBec": None,
                    "fcstChange": None,
                    "probability": None,
                    "wdir": 190,
                    "wspd": 15,
                    "wgst": None,
                    "visib": "6+",
                    "wxString": None,
                    "clouds": [{"cover": "BKN", "base": 20000}],
                    "temp": [],
                }
            ],
        }
        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.icao_code == "EGLC")).one()
            self.assertEqual(save_taf_payload(session, station, payload), 1)
            self.assertEqual(save_taf_payload(session, station, payload), 0)
            session.commit()
            reports = session.exec(select(TafReport)).all()
            periods = session.exec(select(TafForecastPeriod)).all()
            self.assertEqual(len(reports), 1)
            self.assertEqual(len(periods), 1)

    def test_refresh_station_stale_flag(self) -> None:
        old_observed = utc_now().replace(year=2025)
        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.icao_code == "EGLC")).one()
            session.add(
                MetarObservation(
                    station_id=station.id,
                    observed_at=old_observed,
                    raw_report="raw",
                )
            )
            session.commit()
            self.assertTrue(refresh_station_stale_flag(session, station.id))

    def test_sync_weather_uses_shared_session_for_sqlite(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Station(
                    city_code="paris",
                    city_name="Paris",
                    icao_code="LFPG",
                    country_code="FR",
                    timezone_name="Europe/Paris",
                    settlement_unit="C",
                    wunderground_station_code="LFPG",
                )
            )
            session.commit()

        class FakeClient:
            async def fetch_metar(self, station_codes: list[str]) -> list[dict]:
                return [
                    {
                        "reportTime": "2026-04-08T12:00:00.000Z",
                        "temp": 18.2 if station_codes[0] == "EGLC" else 14.1,
                        "dewp": 9.3,
                        "wspd": 8,
                        "wdir": 220,
                        "altim": 1019.0,
                        "visib": "9999",
                        "rawOb": f"METAR {station_codes[0]} 081200Z 22008KT 9999 FEW040 18/09 Q1019",
                    }
                ]

            async def fetch_taf(self, station_codes: list[str]) -> list[dict]:
                return [
                    {
                        "issueTime": "2026-04-08T11:20:00.000Z",
                        "validTimeFrom": 1775649600,
                        "validTimeTo": 1775736000,
                        "rawTAF": f"TAF {station_codes[0]} 081120Z 0812/0912 19015KT P6SM BKN200",
                        "fcsts": [
                            {
                                "timeFrom": 1775649600,
                                "timeTo": 1775656800,
                                "timeBec": None,
                                "fcstChange": None,
                                "probability": None,
                                "wdir": 190,
                                "wspd": 15,
                                "wgst": None,
                                "visib": "6+",
                                "wxString": None,
                                "clouds": [{"cover": "BKN", "base": 20000}],
                                "temp": [],
                            }
                        ],
                    }
                ]

        with Session(self.engine) as session:
            results = asyncio.run(sync_weather(session, client=FakeClient(), engine=self.engine))
            self.assertEqual(len(results), 2)
            self.assertEqual(sum(item.metar_count for item in results), 2)
            self.assertEqual(sum(item.taf_count for item in results), 2)

            metars = session.exec(select(MetarObservation)).all()
            tafs = session.exec(select(TafReport)).all()
            self.assertEqual(len(metars), 2)
            self.assertEqual(len(tafs), 2)

    def test_sync_weather_retries_sqlite_locked_write(self) -> None:
        class FakeClient:
            async def fetch_metar(self, station_codes: list[str]) -> list[dict]:
                return [
                    {
                        "reportTime": "2026-04-08T12:00:00.000Z",
                        "temp": 18.2,
                        "dewp": 9.3,
                        "wspd": 8,
                        "wdir": 220,
                        "altim": 1019.0,
                        "visib": "9999",
                        "rawOb": f"METAR {station_codes[0]} 081200Z 22008KT 9999 FEW040 18/09 Q1019",
                    }
                ]

            async def fetch_taf(self, station_codes: list[str]) -> list[dict]:
                return [
                    {
                        "issueTime": "2026-04-08T11:20:00.000Z",
                        "validTimeFrom": 1775649600,
                        "validTimeTo": 1775736000,
                        "rawTAF": f"TAF {station_codes[0]} 081120Z 0812/0912 19015KT P6SM BKN200",
                        "fcsts": [
                            {
                                "timeFrom": 1775649600,
                                "timeTo": 1775656800,
                                "timeBec": None,
                                "fcstChange": None,
                                "probability": None,
                                "wdir": 190,
                                "wspd": 15,
                                "wgst": None,
                                "visib": "6+",
                                "wxString": None,
                                "clouds": [{"cover": "BKN", "base": 20000}],
                                "temp": [],
                            }
                        ],
                    }
                ]

        original = weather_fetcher._persist_weather_payloads
        attempts = {"count": 0}

        def flaky_persist(session, station, metar_payloads, taf_payloads):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OperationalError(
                    None,
                    None,
                    sqlite3.OperationalError("database is locked"),
                )
            return original(session, station, metar_payloads, taf_payloads)

        with (
            Session(self.engine) as session,
            patch("src.data.weather_fetcher._persist_weather_payloads", side_effect=flaky_persist),
            patch("src.data.weather_fetcher.asyncio.sleep", new=AsyncMock()) as sleep_mock,
        ):
            results = asyncio.run(sync_weather(session, client=FakeClient(), engine=self.engine))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].metar_count, 1)
            self.assertEqual(results[0].taf_count, 1)
            self.assertEqual(attempts["count"], 2)
            sleep_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
