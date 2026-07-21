#!/usr/bin/env python3
from __future__ import annotations

import unittest

from swarm.safety.inter_drone_collision_monitor import (
    CollisionPredictor,
    PoseSample,
    Velocity,
)


class CollisionPredictorTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.predictor = CollisionPredictor(
            horizon_s=10.0,
            minimum_closing_speed_m_s=0.1,
            emergency_distance_m=3.0,
            critical_distance_m=5.0,
            warning_distance_m=8.0,
        )

    @staticmethod
    def sample(
        drone_id: str,
        x_m: float,
        y_m: float,
        z_m: float = 5.0,
    ) -> PoseSample:
        return PoseSample(
            drone_id=drone_id,
            model_name=drone_id,
            timestamp_s=1.0,
            x_m=x_m,
            y_m=y_m,
            z_m=z_m,
        )

    def test_clear_separation(self) -> None:
        first = self.sample(
            "drone_1",
            0.0,
            0.0,
        )
        second = self.sample(
            "drone_2",
            20.0,
            0.0,
        )

        current = self.predictor.distance(
            first,
            second,
        )
        _, closest, _ = (
            self.predictor.closest_approach(
                first,
                second,
                Velocity(0.0, 0.0, 0.0),
                Velocity(0.0, 0.0, 0.0),
            )
        )

        self.assertEqual(
            self.predictor.classify(
                current,
                closest,
            ),
            "clear",
        )

    def test_predicted_critical_approach(
        self,
    ) -> None:
        first = self.sample(
            "drone_1",
            0.0,
            0.0,
        )
        second = self.sample(
            "drone_2",
            10.0,
            0.0,
        )

        _, closest, closing = (
            self.predictor.closest_approach(
                first,
                second,
                Velocity(1.0, 0.0, 0.0),
                Velocity(-1.0, 0.0, 0.0),
            )
        )

        self.assertLessEqual(
            closest,
            5.0,
        )
        self.assertGreater(
            closing,
            0.0,
        )
        self.assertIn(
            self.predictor.classify(
                10.0,
                closest,
            ),
            {
                "critical",
                "emergency_stop",
            },
        )

    def test_emergency_current_distance(
        self,
    ) -> None:
        first = self.sample(
            "drone_1",
            0.0,
            0.0,
        )
        second = self.sample(
            "drone_2",
            2.0,
            0.0,
        )

        current = self.predictor.distance(
            first,
            second,
        )

        self.assertEqual(
            self.predictor.classify(
                current,
                current,
            ),
            "emergency_stop",
        )


if __name__ == "__main__":
    unittest.main()
