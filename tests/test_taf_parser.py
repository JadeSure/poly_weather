import unittest

from src.data.taf_parser import parse_taf_payload


class TafParserTests(unittest.TestCase):
    def test_parse_taf_payload_extracts_periods(self) -> None:
        payload = {
            "rawTAF": "TAF KMCI 081120Z 0812/0912 19015G23KT P6SM BKN200 FM081400 20022G32KT P6SM SCT250",
            "fcsts": [
                {
                    "timeFrom": 1775649600,
                    "timeTo": 1775656800,
                    "timeBec": None,
                    "fcstChange": None,
                    "probability": None,
                    "wdir": 190,
                    "wspd": 15,
                    "wgst": 23,
                    "visib": "6+",
                    "wxString": None,
                    "clouds": [{"cover": "BKN", "base": 20000}],
                    "temp": [],
                },
                {
                    "timeFrom": 1775656800,
                    "timeTo": 1775696400,
                    "timeBec": None,
                    "fcstChange": "FM",
                    "probability": None,
                    "wdir": 200,
                    "wspd": 22,
                    "wgst": 32,
                    "visib": "6+",
                    "wxString": None,
                    "clouds": [{"cover": "SCT", "base": 25000}],
                    "temp": [],
                },
            ],
        }

        periods = parse_taf_payload(payload)
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0].wind_direction_deg, 190)
        self.assertEqual(periods[0].wind_speed_kt, 15)
        self.assertEqual(periods[1].fcst_change, "FM")
        self.assertIn("SCT", periods[1].clouds_json or "")


if __name__ == "__main__":
    unittest.main()

