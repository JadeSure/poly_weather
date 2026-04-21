import unittest
from datetime import timedelta

from src.worker.main import build_scheduler


class WorkerSchedulerTests(unittest.TestCase):
    def test_build_scheduler_staggers_initial_writer_jobs(self) -> None:
        scheduler = build_scheduler()

        weather_job = scheduler.get_job("weather_job")
        market_job = scheduler.get_job("market_job")
        forecast_job = scheduler.get_job("forecast_job")

        self.assertIsNotNone(weather_job)
        self.assertIsNotNone(market_job)
        self.assertIsNotNone(forecast_job)
        self.assertEqual(market_job.next_run_time - weather_job.next_run_time, timedelta(seconds=10))
        self.assertEqual(
            forecast_job.next_run_time - weather_job.next_run_time,
            timedelta(seconds=5),
        )


if __name__ == "__main__":
    unittest.main()
