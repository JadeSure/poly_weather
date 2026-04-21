import json
import unittest
from datetime import date
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from src.api.routers.weather import (
    build_station_forecast_data,
    build_station_forecast_summary_data,
    build_station_taf_data,
    build_station_taf_summary_data,
)
from src.db.models import EnsembleForecast, EnsembleRun, Station, TafForecastPeriod, TafReport


class WeatherApiTests(unittest.TestCase):
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

    def test_build_station_taf_data_returns_latest_report_with_periods(self) -> None:
        issue_time_1 = datetime(2026, 4, 8, 10, 20, tzinfo=timezone.utc)
        issue_time_2 = datetime(2026, 4, 8, 11, 20, tzinfo=timezone.utc)
        valid_from = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        valid_to = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        period_one_from = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        period_one_to = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        period_two_from = datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc)
        period_two_to = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)

        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.city_code == "london")).one()
            first = TafReport(
                station_id=station.id,
                issue_time=issue_time_1,
                valid_time_from=valid_from,
                valid_time_to=valid_to,
                raw_taf="TAF EGLC 081020Z 0812/0912 16010KT P6SM FEW040",
            )
            latest = TafReport(
                station_id=station.id,
                issue_time=issue_time_2,
                valid_time_from=valid_from,
                valid_time_to=valid_to,
                raw_taf="TAF EGLC 081120Z 0812/0912 19015KT P6SM BKN200 FM081400 20022G32KT P6SM SCT250",
            )
            session.add(first)
            session.add(latest)
            session.commit()
            session.refresh(latest)

            session.add(
                TafForecastPeriod(
                    taf_report_id=latest.id,
                    station_id=station.id,
                    time_from=period_one_from,
                    time_to=period_one_to,
                    fcst_change=None,
                    wind_direction_deg=190,
                    wind_speed_kt=15,
                    visibility="6+",
                    clouds_json=json.dumps([{"cover": "BKN", "base": 20000}], ensure_ascii=True),
                    temperature_json=json.dumps([], ensure_ascii=True),
                )
            )
            session.add(
                TafForecastPeriod(
                    taf_report_id=latest.id,
                    station_id=station.id,
                    time_from=period_two_from,
                    time_to=period_two_to,
                    fcst_change="FM",
                    wind_direction_deg=200,
                    wind_speed_kt=22,
                    wind_gust_kt=32,
                    visibility="6+",
                    clouds_json=json.dumps([{"cover": "SCT", "base": 25000}], ensure_ascii=True),
                    temperature_json=json.dumps([], ensure_ascii=True),
                )
            )
            session.commit()

            payload = build_station_taf_data(session, station)

        self.assertEqual(payload["city_code"], "london")
        self.assertEqual(payload["icao_code"], "EGLC")
        self.assertIsNotNone(payload["latest_taf"])
        self.assertIn("081120Z", payload["latest_taf"]["raw_taf"])
        self.assertEqual(len(payload["latest_taf"]["periods"]), 2)
        self.assertEqual(payload["latest_taf"]["periods"][1]["fcst_change"], "FM")
        self.assertEqual(payload["latest_taf"]["periods"][1]["clouds"][0]["cover"], "SCT")

    def test_build_station_taf_data_returns_none_when_no_report_exists(self) -> None:
        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.city_code == "london")).one()
            payload = build_station_taf_data(session, station)
        self.assertIsNone(payload["latest_taf"])

    def test_build_station_taf_summary_data_adds_chinese_explanations(self) -> None:
        issue_time = datetime(2026, 4, 8, 11, 20, tzinfo=timezone.utc)
        valid_from = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
        valid_to = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)

        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.city_code == "london")).one()
            report = TafReport(
                station_id=station.id,
                issue_time=issue_time,
                valid_time_from=valid_from,
                valid_time_to=valid_to,
                raw_taf="TAF EGLC 081120Z 0812/0912 19015KT P6SM BKN200 FM081400 20022G32KT P6SM SCT250",
            )
            session.add(report)
            session.commit()
            session.refresh(report)

            session.add(
                TafForecastPeriod(
                    taf_report_id=report.id,
                    station_id=station.id,
                    time_from=valid_from,
                    time_to=valid_to,
                    fcst_change="FM",
                    wind_direction_deg=200,
                    wind_speed_kt=22,
                    wind_gust_kt=32,
                    visibility="6+",
                    weather_string=None,
                    clouds_json=json.dumps([{"cover": "SCT", "base": 25000}], ensure_ascii=True),
                    temperature_json=json.dumps([], ensure_ascii=True),
                )
            )
            session.commit()

            payload = build_station_taf_summary_data(session, station)

        latest_taf = payload["latest_taf"]
        self.assertIsNotNone(latest_taf)
        self.assertIn("中文解释", latest_taf["explanation_zh"])
        self.assertEqual(len(latest_taf["summary_lines_zh"]), 1)
        self.assertIn("从该时刻开始转为以下条件", latest_taf["summary_lines_zh"][0])
        self.assertIn("风向 200 度", latest_taf["summary_lines_zh"][0])
        self.assertIn("疏云", latest_taf["summary_lines_zh"][0])

    def test_build_station_forecast_data_returns_latest_run_grouped_by_day(self) -> None:
        fetched_at_1 = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        fetched_at_2 = datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc)

        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.city_code == "london")).one()
            old_run = EnsembleRun(
                station_id=station.id,
                model_name="gfs_seamless",
                timezone_name="Europe/London",
                forecast_days=7,
                fetched_at=fetched_at_1,
            )
            latest_run = EnsembleRun(
                station_id=station.id,
                model_name="gfs_seamless",
                timezone_name="Europe/London",
                forecast_days=7,
                fetched_at=fetched_at_2,
            )
            session.add(old_run)
            session.add(latest_run)
            session.commit()
            session.refresh(latest_run)

            session.add(
                EnsembleForecast(
                    ensemble_run_id=latest_run.id,
                    station_id=station.id,
                    forecast_date_local=date(2026, 4, 9),
                    member_index=0,
                    member_name="temperature_2m",
                    max_temp_c=18.0,
                )
            )
            session.add(
                EnsembleForecast(
                    ensemble_run_id=latest_run.id,
                    station_id=station.id,
                    forecast_date_local=date(2026, 4, 9),
                    member_index=1,
                    member_name="temperature_2m_member01",
                    max_temp_c=20.0,
                )
            )
            session.add(
                EnsembleForecast(
                    ensemble_run_id=latest_run.id,
                    station_id=station.id,
                    forecast_date_local=date(2026, 4, 10),
                    member_index=0,
                    member_name="temperature_2m",
                    max_temp_c=17.0,
                )
            )
            session.commit()

            payload = build_station_forecast_data(session, station)

        latest_forecast = payload["latest_forecast"]
        self.assertIsNotNone(latest_forecast)
        self.assertEqual(latest_forecast["fetched_at"], fetched_at_2.isoformat())
        self.assertEqual(len(latest_forecast["days"]), 2)
        self.assertEqual(latest_forecast["days"][0]["forecast_date_local"], "2026-04-09")
        self.assertEqual(latest_forecast["days"][0]["member_count"], 2)
        self.assertEqual(latest_forecast["days"][0]["members"][1]["max_temp_c"], 20.0)

    def test_build_station_forecast_summary_data_adds_chinese_summary(self) -> None:
        fetched_at = datetime(2026, 4, 8, 6, 0, tzinfo=timezone.utc)

        with Session(self.engine) as session:
            station = session.exec(select(Station).where(Station.city_code == "london")).one()
            run = EnsembleRun(
                station_id=station.id,
                model_name="gfs_seamless",
                timezone_name="Europe/London",
                forecast_days=7,
                fetched_at=fetched_at,
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            for member_index, value in enumerate([17.0, 18.0, 20.0], start=0):
                session.add(
                    EnsembleForecast(
                        ensemble_run_id=run.id,
                        station_id=station.id,
                        forecast_date_local=date(2026, 4, 9),
                        member_index=member_index,
                        member_name=f"member_{member_index}",
                        max_temp_c=value,
                    )
                )
            session.commit()

            payload = build_station_forecast_summary_data(session, station)

        latest_forecast = payload["latest_forecast"]
        self.assertIsNotNone(latest_forecast)
        self.assertIn("Open-Meteo ensemble", latest_forecast["explanation_zh"])
        self.assertEqual(len(latest_forecast["days"]), 1)
        self.assertEqual(latest_forecast["days"][0]["avg_max_temp_c"], 18.33)
        self.assertEqual(latest_forecast["days"][0]["median_max_temp_c"], 18.0)
        self.assertIn("2026-04-09 的日最高温 ensemble 摘要", latest_forecast["summary_lines_zh"][0])


if __name__ == "__main__":
    unittest.main()
