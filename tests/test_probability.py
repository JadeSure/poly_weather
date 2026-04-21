import unittest

from src.engine.probability import Bucket, build_bucket_distribution, probability_at_or_above


class ProbabilityTests(unittest.TestCase):
    def test_probability_at_or_above(self) -> None:
        members = [18.2, 17.9, 16.3, 19.0]
        probability = probability_at_or_above(members, threshold=18, unit="C")
        self.assertEqual(probability, 0.5)

    def test_build_bucket_distribution(self) -> None:
        members = [18.2, 17.9, 16.3, 19.0]
        buckets = [
            Bucket(label="16", low=16, high=16),
            Bucket(label="17", low=17, high=17),
            Bucket(label="18", low=18, high=18),
            Bucket(label="19", low=19, high=19),
        ]
        distribution = build_bucket_distribution(members, buckets, unit="C")
        by_label = {item.label: item.probability for item in distribution}
        self.assertEqual(by_label["16"], 0.25)
        self.assertEqual(by_label["17"], 0.25)
        self.assertEqual(by_label["18"], 0.25)
        self.assertEqual(by_label["19"], 0.25)


if __name__ == "__main__":
    unittest.main()

