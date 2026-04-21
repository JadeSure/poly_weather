"""Cross-validation tests across all 5 configured cities.

Covers: METAR parsing per station, contract parsing with different bucket
formats, temperature rounding for C/F, timezone edge cases, and negative
temperature handling.
"""

import unittest
from datetime import date, datetime, timezone

from src.data.metar_parser import parse_metar, observed_local_time
from src.db.models import Station
from src.engine.rounding import (
    celsius_to_fahrenheit,
    settlement_temperature,
    truncate_temperature,
)
from src.market.contract_parser import (
    infer_city_code,
    is_weather_market_payload,
    parse_bucket_from_text,
    parse_station_code_from_url,
    _parse_forecast_date_from_text,
)


ALL_STATIONS = [
    Station(
        id=1,
        city_code="london",
        city_name="London",
        icao_code="EGLC",
        country_code="GB",
        timezone_name="Europe/London",
        settlement_unit="C",
        wunderground_station_code="EGLC",
    ),
    Station(
        id=2,
        city_code="seoul",
        city_name="Seoul",
        icao_code="RKSI",
        country_code="KR",
        timezone_name="Asia/Seoul",
        settlement_unit="C",
        wunderground_station_code="RKSI",
    ),
    Station(
        id=3,
        city_code="chicago",
        city_name="Chicago",
        icao_code="KORD",
        country_code="US",
        timezone_name="America/Chicago",
        settlement_unit="F",
        wunderground_station_code="KORD",
    ),
    Station(
        id=4,
        city_code="miami",
        city_name="Miami",
        icao_code="KMIA",
        country_code="US",
        timezone_name="America/New_York",
        settlement_unit="F",
        wunderground_station_code="KMIA",
    ),
    Station(
        id=5,
        city_code="paris",
        city_name="Paris",
        icao_code="LFPG",
        country_code="FR",
        timezone_name="Europe/Paris",
        settlement_unit="C",
        wunderground_station_code="LFPG",
    ),
]


class MetarMultiCityTests(unittest.TestCase):
    """METAR parsing for all 5 stations including edge cases."""

    def test_london_standard(self) -> None:
        report = "EGLC 081250Z 22008KT 9999 FEW040 18/09 Q1019"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 13, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.station, "EGLC")
        self.assertEqual(parsed.temperature_c, 18.0)
        self.assertEqual(parsed.wind_speed_kt, 8)

    def test_seoul_negative_winter_temp(self) -> None:
        report = "RKSI 150300Z 32010KT 9999 SCT020 M08/M15 Q1030"
        parsed = parse_metar(report, reference_time=datetime(2026, 1, 15, 4, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.station, "RKSI")
        self.assertEqual(parsed.temperature_c, -8.0)
        self.assertEqual(parsed.dewpoint_c, -15.0)

    def test_chicago_vrb_wind(self) -> None:
        report = "KORD 081500Z VRB03KT 10SM FEW250 05/M02 Q1015"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.station, "KORD")
        self.assertEqual(parsed.temperature_c, 5.0)
        self.assertIsNone(parsed.wind_direction_deg)
        self.assertEqual(parsed.wind_speed_kt, 3)

    def test_miami_high_temp(self) -> None:
        report = "KMIA 081800Z 15010KT 10SM SCT045 33/22 Q1014"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.station, "KMIA")
        self.assertEqual(parsed.temperature_c, 33.0)
        self.assertEqual(parsed.dewpoint_c, 22.0)

    def test_paris_moderate_temp(self) -> None:
        report = "LFPG 081400Z 25012KT 9999 SCT030 14/07 Q1021"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.station, "LFPG")
        self.assertEqual(parsed.temperature_c, 14.0)

    def test_seoul_timezone_utc_plus_9(self) -> None:
        """Seoul UTC+9: a 15:00Z observation is midnight local (next day)."""
        report = "RKSI 081500Z 01005KT 9999 FEW020 02/M01 Q1025"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc))
        local = observed_local_time(parsed, "Asia/Seoul")
        self.assertEqual(local.day, 9)
        self.assertEqual(local.hour, 0)

    def test_chicago_timezone_utc_minus_5(self) -> None:
        """Chicago CDT (UTC-5): a 04:00Z observation is 23:00 local (previous day)."""
        report = "KORD 090400Z 18008KT 10SM CLR 08/02 Q1018"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 9, 5, 0, tzinfo=timezone.utc))
        local = observed_local_time(parsed, "America/Chicago")
        self.assertEqual(local.day, 8)
        self.assertEqual(local.hour, 23)

    def test_paris_timezone_utc_plus_2_summer(self) -> None:
        """Paris CEST (UTC+2 in summer): 22:00Z = midnight local."""
        report = "LFPG 082200Z 20005KT 9999 FEW040 11/06 Q1020"
        parsed = parse_metar(report, reference_time=datetime(2026, 4, 8, 23, 0, tzinfo=timezone.utc))
        local = observed_local_time(parsed, "Europe/Paris")
        self.assertEqual(local.day, 9)
        self.assertEqual(local.hour, 0)


class TemperatureRoundingMultiCityTests(unittest.TestCase):
    """Settlement temperature conversion across C and F cities."""

    def test_london_celsius_truncation(self) -> None:
        self.assertEqual(settlement_temperature(18.9, "C"), 18)
        self.assertEqual(settlement_temperature(-0.3, "C"), 0)
        self.assertEqual(settlement_temperature(-2.7, "C"), -2)

    def test_seoul_negative_celsius_truncation(self) -> None:
        self.assertEqual(settlement_temperature(-8.6, "C"), -8)
        self.assertEqual(settlement_temperature(-15.1, "C"), -15)

    def test_chicago_fahrenheit_conversion_and_truncation(self) -> None:
        # 5.0°C = 41.0°F → truncated = 41
        self.assertEqual(settlement_temperature(5.0, "F"), 41)
        # 5.5°C = 41.9°F → truncated = 41
        self.assertEqual(settlement_temperature(5.5, "F"), 41)
        # -1.0°C = 30.2°F → truncated = 30
        self.assertEqual(settlement_temperature(-1.0, "F"), 30)

    def test_miami_fahrenheit_high_temp(self) -> None:
        # 33.0°C = 91.4°F → truncated = 91
        self.assertEqual(settlement_temperature(33.0, "F"), 91)
        # 33.8°C = 92.84°F → truncated = 92
        self.assertEqual(settlement_temperature(33.8, "F"), 92)

    def test_paris_celsius_boundary(self) -> None:
        self.assertEqual(settlement_temperature(14.0, "C"), 14)
        self.assertEqual(settlement_temperature(14.99, "C"), 14)

    def test_freezing_point_both_units(self) -> None:
        self.assertEqual(settlement_temperature(0.0, "C"), 0)
        self.assertEqual(settlement_temperature(0.0, "F"), 32)

    def test_negative_fahrenheit(self) -> None:
        # -20°C = -4°F → truncated = -4
        self.assertEqual(settlement_temperature(-20.0, "F"), -4)
        # -17.9°C = -0.22°F → truncated = 0
        self.assertEqual(truncate_temperature(celsius_to_fahrenheit(-17.9)), 0)


class ContractParserMultiCityTests(unittest.TestCase):
    """Contract parsing for all 5 cities with various bucket formats."""

    def test_infer_city_code_all_cities(self) -> None:
        cases = [
            ("Will the highest temperature in London exceed 16C?", "london"),
            ("Will the highest temperature in Seoul be 25°C or above?", "seoul"),
            ("Will the highest temperature in Chicago be between 40-41°F?", "chicago"),
            ("Will the highest temperature in Miami be 90°F or higher?", "miami"),
            ("Will the highest temperature in Paris be between 14-15°C?", "paris"),
        ]
        for question, expected_code in cases:
            with self.subTest(question=question):
                self.assertEqual(infer_city_code(question, ALL_STATIONS), expected_code)

    def test_fahrenheit_bucket_parsing(self) -> None:
        label, low, high, unit = parse_bucket_from_text(
            "Will the highest temperature in Chicago be between 40-41°F on April 8?"
        )
        self.assertEqual(low, 40)
        self.assertEqual(high, 41)
        self.assertEqual(unit, "F")

    def test_celsius_range_bucket(self) -> None:
        label, low, high, unit = parse_bucket_from_text(
            "Will the highest temperature in Seoul be between 24-25°C on April 10?"
        )
        self.assertEqual(low, 24)
        self.assertEqual(high, 25)
        self.assertEqual(unit, "C")

    def test_or_higher_fahrenheit_bucket(self) -> None:
        label, low, high, unit = parse_bucket_from_text(
            "Will the highest temperature in Miami be 95°F or higher on April 12?"
        )
        self.assertEqual(low, 95)
        self.assertIsNone(high)
        self.assertEqual(unit, "F")

    def test_or_below_celsius_bucket(self) -> None:
        label, low, high, unit = parse_bucket_from_text(
            "Will the highest temperature in Paris be 10°C or below on April 9?"
        )
        self.assertIsNone(low)
        self.assertEqual(high, 10)
        self.assertEqual(unit, "C")

    def test_negative_bucket(self) -> None:
        label, low, high, unit = parse_bucket_from_text(
            "Will the highest temperature in Seoul be -5°C or below on Jan 15?"
        )
        self.assertIsNone(low)
        self.assertEqual(high, -5)
        self.assertEqual(unit, "C")

    def test_station_code_from_url_all_cities(self) -> None:
        cases = [
            ("https://wunderground.com/history/daily/gb/london/EGLC", "EGLC"),
            ("https://wunderground.com/history/daily/kr/seoul/RKSI", "RKSI"),
            ("https://wunderground.com/history/daily/us/chicago/KORD", "KORD"),
            ("https://wunderground.com/history/daily/us/miami/KMIA", "KMIA"),
            ("https://wunderground.com/history/daily/fr/paris/LFPG", "LFPG"),
        ]
        for url, expected_code in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_station_code_from_url(url), expected_code)

    def test_weather_market_heuristic_all_cities(self) -> None:
        cases = [
            {
                "question": "Will the high temp in London exceed 16C?",
                "description": "wunderground.com/history/daily/gb/london/EGLC",
                "resolutionSource": "",
            },
            {
                "question": "Will the highest temperature in Seoul be 25°C?",
                "description": "temperature",
                "resolutionSource": "",
            },
            {
                "question": "Will the highest temperature in Chicago be 50°F?",
                "description": "temperature",
                "resolutionSource": "",
            },
            {
                "question": "Will the highest temperature in Miami be 90°F?",
                "description": "temperature",
                "resolutionSource": "",
            },
            {
                "question": "Will the highest temperature in Paris be 14°C?",
                "description": "temperature",
                "resolutionSource": "",
            },
        ]
        for payload in cases:
            with self.subTest(q=payload["question"]):
                self.assertTrue(is_weather_market_payload(payload, ALL_STATIONS))


class ForecastDateParsingTests(unittest.TestCase):
    """Validate date extraction from question text for different formats."""

    def test_standard_month_day(self) -> None:
        result = _parse_forecast_date_from_text(
            "Will the highest temperature in Chicago be 50°F or higher on April 8?"
        )
        self.assertEqual(result, date(2026, 4, 8))

    def test_abbreviated_month(self) -> None:
        result = _parse_forecast_date_from_text(
            "Will the highest temperature in Seoul be 25°C on Jan 15?"
        )
        self.assertEqual(result, date(2026, 1, 15))

    def test_no_date_returns_none(self) -> None:
        result = _parse_forecast_date_from_text(
            "Will the highest temperature in London exceed 16C?"
        )
        self.assertIsNone(result)

    def test_december_date(self) -> None:
        result = _parse_forecast_date_from_text(
            "Will the highest temperature in Paris be 5°C on December 25?"
        )
        self.assertEqual(result, date(2026, 12, 25))


if __name__ == "__main__":
    unittest.main()
