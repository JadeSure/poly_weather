import unittest
from datetime import datetime, timezone

from src.engine.trend_adjustment import (
    TemperatureObservation,
    apply_market_day_adjustment,
    compute_recent_temperature_trend_c_per_hour,
)


class TrendAdjustmentTests(unittest.TestCase):
    def test_recent_temperature_trend_uses_recent_observations(self) -> None:
        observations = [
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
                temperature_c=18.0,
            ),
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc),
                temperature_c=14.0,
            ),
        ]
        self.assertEqual(compute_recent_temperature_trend_c_per_hour(observations), 2.0)

    def test_same_day_adjustment_applies_floor_and_positive_shift(self) -> None:
        observations = [
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
                temperature_c=18.0,
            ),
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc),
                temperature_c=14.0,
            ),
        ]
        result = apply_market_day_adjustment(
            ensemble_members_c=[16.0, 17.0, 18.5],
            target_date_local=datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc).date(),
            timezone_name="UTC",
            observations=observations,
            peak_hour_local=15.0,
        )
        self.assertTrue(result.same_day)
        self.assertEqual(result.applied_floor_c, 18.0)
        self.assertGreater(result.applied_adjustment_c, 0.0)
        self.assertTrue(all(value >= 18.0 for value in result.adjusted_members_c))

    def test_future_day_does_not_apply_current_day_floor(self) -> None:
        observations = [
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc),
                temperature_c=18.0,
            ),
            TemperatureObservation(
                observed_at=datetime(2026, 4, 8, 8, 0, tzinfo=timezone.utc),
                temperature_c=14.0,
            ),
        ]
        result = apply_market_day_adjustment(
            ensemble_members_c=[10.0, 11.0, 12.0],
            target_date_local=datetime(2026, 4, 9, 0, 0, tzinfo=timezone.utc).date(),
            timezone_name="UTC",
            observations=observations,
        )
        self.assertFalse(result.same_day)
        self.assertEqual(result.adjusted_members_c, [10.0, 11.0, 12.0])
        self.assertIsNone(result.applied_floor_c)


if __name__ == "__main__":
    unittest.main()
