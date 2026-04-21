from dataclasses import dataclass

from src.engine.rounding import settlement_temperature


@dataclass(slots=True)
class Bucket:
    label: str
    low: int | None = None
    high: int | None = None

    def contains(self, value: int) -> bool:
        lower_ok = self.low is None or value >= self.low
        upper_ok = self.high is None or value <= self.high
        return lower_ok and upper_ok


@dataclass(slots=True)
class BucketProbability:
    label: str
    probability: float


def probability_at_or_above(ensemble_members_c: list[float], threshold: int, unit: str) -> float:
    if not ensemble_members_c:
        raise ValueError("ensemble_members_c cannot be empty")
    hits = sum(1 for value_c in ensemble_members_c if settlement_temperature(value_c, unit) >= threshold)
    return hits / len(ensemble_members_c)


def build_bucket_distribution(
    ensemble_members_c: list[float],
    buckets: list[Bucket],
    unit: str,
) -> list[BucketProbability]:
    if not ensemble_members_c:
        raise ValueError("ensemble_members_c cannot be empty")
    if not buckets:
        raise ValueError("buckets cannot be empty")

    counts = {bucket.label: 0 for bucket in buckets}
    for value_c in ensemble_members_c:
        settled = settlement_temperature(value_c, unit)
        for bucket in buckets:
            if bucket.contains(settled):
                counts[bucket.label] += 1
                break

    total = len(ensemble_members_c)
    return [
        BucketProbability(label=bucket.label, probability=counts[bucket.label] / total)
        for bucket in buckets
    ]

