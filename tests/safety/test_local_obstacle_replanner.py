#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from swarm.safety.local_obstacle_replanner import (
    LocalObstacleReplanner,
)


class LocalObstacleReplannerTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        root = Path(
            self.temp_directory.name
        )

        config = {
            "replanner": {
                "mode": "dry_run",
                "poll_interval_s": 0.5,
                "decision_cooldown_s": 3.0,
                "maximum_attempts_per_waypoint": 3,
                "trigger_states": [
                    "critical",
                    "emergency_stop",
                ],
                "minimum_side_clearance_m": 8.0,
                "side_preference_margin_m": 1.0,
                "temporary_waypoint": {
                    "forward_offset_m": 2.0,
                    "lateral_offset_m": 5.0,
                    "altitude_offset_m": 0.0,
                },
                "blocked_sides_action":
                    "abort_replan",
                "event_log_csv": str(
                    root / "{drone_id}.csv"
                ),
            },
            "geometry": {
                "earth_radius_m": 6371000.0,
                "minimum_target_vector_m": 0.25,
            },
        }

        config_path = (
            root / "replanner.yaml"
        )
        config_path.write_text(
            yaml.safe_dump(
                config,
                sort_keys=False,
            )
        )

        self.replanner = (
            LocalObstacleReplanner(
                config_path,
                "drone_test",
            )
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_left_side_selected(self) -> None:
        plan = self.replanner.plan(
            current_north_m=0.0,
            current_east_m=0.0,
            current_altitude_m=3.0,
            target_north_m=10.0,
            target_east_m=0.0,
            yaw_deg=0.0,
            front_min_m=4.0,
            left_min_m=15.0,
            right_min_m=6.0,
            safety_state="emergency_stop",
        )

        self.assertTrue(
            plan["can_replan"]
        )
        self.assertEqual(
            plan["selected_side"],
            "left",
        )
        self.assertAlmostEqual(
            plan["temporary_north_m"],
            2.0,
        )
        self.assertAlmostEqual(
            plan["temporary_east_m"],
            5.0,
        )

    def test_right_side_selected(self) -> None:
        plan = self.replanner.plan(
            current_north_m=0.0,
            current_east_m=0.0,
            current_altitude_m=3.0,
            target_north_m=10.0,
            target_east_m=0.0,
            yaw_deg=0.0,
            front_min_m=4.0,
            left_min_m=9.0,
            right_min_m=16.0,
            safety_state="emergency_stop",
        )

        self.assertTrue(
            plan["can_replan"]
        )
        self.assertEqual(
            plan["selected_side"],
            "right",
        )
        self.assertAlmostEqual(
            plan["temporary_north_m"],
            2.0,
        )
        self.assertAlmostEqual(
            plan["temporary_east_m"],
            -5.0,
        )

    def test_both_sides_blocked(self) -> None:
        plan = self.replanner.plan(
            current_north_m=0.0,
            current_east_m=0.0,
            current_altitude_m=3.0,
            target_north_m=10.0,
            target_east_m=0.0,
            yaw_deg=0.0,
            front_min_m=4.0,
            left_min_m=7.0,
            right_min_m=6.0,
            safety_state="emergency_stop",
        )

        self.assertFalse(
            plan["can_replan"]
        )
        self.assertEqual(
            plan["result"],
            "abort_replan",
        )


if __name__ == "__main__":
    unittest.main()
