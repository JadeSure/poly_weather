import unittest

from src.db.models import Station
from src.market.contract_parser import (
    build_outcome_token_map,
    infer_city_code,
    is_weather_market_payload,
    parse_bucket_from_text,
    parse_station_code_from_url,
)


class ContractParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stations = [
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
                city_code="chicago",
                city_name="Chicago",
                icao_code="KORD",
                country_code="US",
                timezone_name="America/Chicago",
                settlement_unit="F",
                wunderground_station_code="KORD",
            ),
        ]

    def test_parse_station_code_from_resolution_url(self) -> None:
        self.assertEqual(
            parse_station_code_from_url("https://wunderground.com/history/daily/gb/london/EGLC"),
            "EGLC",
        )

    def test_parse_bucket_from_text(self) -> None:
        label, low, high, unit = parse_bucket_from_text("Will London exceed 16C today?")
        self.assertEqual(label, "16C")
        self.assertEqual(low, 16)
        self.assertEqual(high, 16)
        self.assertEqual(unit, "C")

    def test_parse_open_ended_bucket_from_text(self) -> None:
        label, low, high, unit = parse_bucket_from_text("Will London be 16°C or below on April 7?")
        self.assertEqual(label, "16°C")
        self.assertIsNone(low)
        self.assertEqual(high, 16)
        self.assertEqual(unit, "C")

    def test_build_outcome_token_map(self) -> None:
        payload = {
            "outcomes": "[\"Yes\", \"No\"]",
            "clobTokenIds": "[\"1\", \"2\"]",
        }
        self.assertEqual(build_outcome_token_map(payload), {"Yes": "1", "No": "2"})

    def test_weather_market_heuristic(self) -> None:
        payload = {
            "question": "Will the high temperature in London exceed 16C?",
            "description": "Settles based on wunderground.com/history/daily/gb/london/EGLC",
            "resolutionSource": "https://wunderground.com/history/daily/gb/london/EGLC",
        }
        self.assertEqual(infer_city_code(payload["question"], self.stations), "london")
        self.assertTrue(is_weather_market_payload(payload, self.stations))


if __name__ == "__main__":
    unittest.main()
