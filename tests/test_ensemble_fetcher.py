import unittest

from src.engine.ensemble_fetcher import aggregate_daily_member_maxima


class EnsembleFetcherTests(unittest.TestCase):
    def test_aggregate_daily_member_maxima(self) -> None:
        payload = {
            "hourly": {
                "time": [
                    "2026-04-08T00:00",
                    "2026-04-08T01:00",
                    "2026-04-09T00:00",
                    "2026-04-09T01:00",
                ],
                "temperature_2m": [10.0, 12.0, 11.0, 13.0],
                "temperature_2m_member01": [9.0, 14.0, 8.0, 7.0],
            }
        }
        rows = aggregate_daily_member_maxima(payload)
        pairs = {(row.member_name, row.forecast_date_local.isoformat()): row.max_temp_c for row in rows}
        self.assertEqual(pairs[("temperature_2m", "2026-04-08")], 12.0)
        self.assertEqual(pairs[("temperature_2m", "2026-04-09")], 13.0)
        self.assertEqual(pairs[("temperature_2m_member01", "2026-04-08")], 14.0)
        self.assertEqual(pairs[("temperature_2m_member01", "2026-04-09")], 8.0)


if __name__ == "__main__":
    unittest.main()

