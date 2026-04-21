import unittest
from datetime import datetime, timezone

from src.data.metar_parser import parse_metar


class MetarParserTests(unittest.TestCase):
    def test_parse_standard_metar(self) -> None:
        report = "EGLC 080850Z 22008KT 9999 FEW040 18/09 Q1019"
        parsed = parse_metar(
            report,
            reference_time=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(parsed.station, "EGLC")
        self.assertEqual(parsed.temperature_c, 18.0)
        self.assertEqual(parsed.dewpoint_c, 9.0)
        self.assertEqual(parsed.wind_speed_kt, 8)
        self.assertEqual(parsed.pressure_hpa, 1019.0)
        self.assertEqual(parsed.observed_at.day, 8)

    def test_parse_negative_temperature(self) -> None:
        report = "CYYZ 080900Z 35012KT 9999 SCT025 M05/M10 Q1008"
        parsed = parse_metar(
            report,
            reference_time=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(parsed.temperature_c, -5.0)
        self.assertEqual(parsed.dewpoint_c, -10.0)


if __name__ == "__main__":
    unittest.main()

