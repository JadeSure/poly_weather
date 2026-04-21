import unittest

from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine

from src.common.time import utc_now
from src.engine.probability import Bucket
from src.engine.signal_generator import (
    apply_group_selection,
    apply_observation_floor,
    bucket_probability,
    generate_signal,
    should_persist_signal,
)
from src.db.models import Signal


class SignalGeneratorTests(unittest.TestCase):
    def test_apply_observation_floor(self) -> None:
        adjusted = apply_observation_floor([18.0, 19.0, 20.0], latest_observation_c=19.5)
        self.assertEqual(adjusted, [19.5, 19.5, 20.0])

    def test_bucket_probability(self) -> None:
        probability = bucket_probability(
            [18.2, 17.9, 18.6, 19.1],
            Bucket(label="18C", low=18, high=18),
            unit="C",
        )
        self.assertEqual(probability, 0.5)

    def test_generate_signal_thresholds(self) -> None:
        signal = generate_signal(0.7, 0.5)
        self.assertEqual(signal.action, "BUY")
        self.assertTrue(signal.is_actionable)

    def test_apply_group_selection_keeps_only_strongest_actionable(self) -> None:
        strong = Signal(
            market_id=1,
            signal_type="BUY",
            model_probability=0.4,
            market_probability=0.1,
            edge_bps=3000,
            confidence=1.0,
            reasoning_json='{"reason":"candidate","bucket_label":"12C"}',
            is_actionable=True,
        )
        weak = Signal(
            market_id=2,
            signal_type="BUY",
            model_probability=0.3,
            market_probability=0.1,
            edge_bps=2000,
            confidence=1.0,
            reasoning_json='{"reason":"candidate","bucket_label":"11C"}',
            is_actionable=True,
        )
        rows = apply_group_selection([strong, weak])
        by_market = {row.market_id: row for row in rows}
        self.assertTrue(by_market[1].is_actionable)
        self.assertEqual(by_market[2].signal_type, "SKIP")
        self.assertFalse(by_market[2].is_actionable)
        self.assertIn("group_dominated", by_market[2].reasoning_json or "")

    def test_should_persist_signal_deduplicates_similar_recent_signal(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        now = utc_now()
        existing = Signal(
            market_id=1,
            signal_at=now - timedelta(minutes=5),
            signal_type="BUY",
            model_probability=0.45,
            market_probability=0.20,
            edge_bps=2500,
            confidence=1.0,
            reasoning_json='{"reason":"candidate"}',
            is_actionable=True,
        )
        candidate = Signal(
            market_id=1,
            signal_at=now,
            signal_type="BUY",
            model_probability=0.46,
            market_probability=0.20,
            edge_bps=2520,
            confidence=1.0,
            reasoning_json='{"reason":"candidate"}',
            is_actionable=True,
        )
        with Session(engine) as session:
            session.add(existing)
            session.commit()
            self.assertFalse(should_persist_signal(session, candidate))
        engine.dispose()

    def test_should_persist_signal_checks_pending_session_rows_without_autoflush(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        now = utc_now()
        existing = Signal(
            market_id=1,
            signal_at=now - timedelta(minutes=1),
            signal_type="SKIP",
            model_probability=0.0,
            market_probability=0.999,
            edge_bps=0,
            confidence=0.0,
            reasoning_json='{"reason":"missing_forecast"}',
            is_actionable=False,
        )
        candidate = Signal(
            market_id=1,
            signal_at=now,
            signal_type="SKIP",
            model_probability=0.0,
            market_probability=0.999,
            edge_bps=0,
            confidence=0.0,
            reasoning_json='{"reason":"missing_forecast"}',
            is_actionable=False,
        )
        with Session(engine) as session:
            session.add(existing)
            self.assertFalse(should_persist_signal(session, candidate))
            self.assertEqual(len(session.new), 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
