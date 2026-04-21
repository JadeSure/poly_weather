import unittest

from src.engine.rounding import celsius_to_fahrenheit, settlement_temperature, truncate_temperature


class RoundingTests(unittest.TestCase):
    def test_truncate_temperature_drops_fraction_without_rounding(self) -> None:
        self.assertEqual(truncate_temperature(23.7), 23)
        self.assertEqual(truncate_temperature(-1.9), -1)

    def test_settlement_temperature_in_fahrenheit(self) -> None:
        self.assertAlmostEqual(celsius_to_fahrenheit(0.0), 32.0)
        self.assertEqual(settlement_temperature(23.7, "C"), 23)
        self.assertEqual(settlement_temperature(20.0, "F"), 68)


if __name__ == "__main__":
    unittest.main()

