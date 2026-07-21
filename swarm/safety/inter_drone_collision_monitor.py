#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class PoseSample:
    drone_id: str
    model_name: str
    timestamp_s: float
    x_m: float
    y_m: float
    z_m: float


@dataclass(frozen=True)
class Velocity:
    x_m_s: float
    y_m_s: float
    z_m_s: float


class CollisionPredictor:
    def __init__(
        self,
        *,
        horizon_s: float,
        minimum_closing_speed_m_s: float,
        emergency_distance_m: float,
        critical_distance_m: float,
        warning_distance_m: float,
    ) -> None:
        self.horizon_s = float(horizon_s)
        self.minimum_closing_speed_m_s = float(
            minimum_closing_speed_m_s
        )
        self.emergency_distance_m = float(
            emergency_distance_m
        )
        self.critical_distance_m = float(
            critical_distance_m
        )
        self.warning_distance_m = float(
            warning_distance_m
        )

        if not (
            0.0
            < self.emergency_distance_m
            < self.critical_distance_m
            < self.warning_distance_m
        ):
            raise ValueError(
                "Collision thresholds must satisfy "
                "0 < emergency < critical < warning"
            )

    @staticmethod
    def distance(
        first: PoseSample,
        second: PoseSample,
    ) -> float:
        return math.sqrt(
            (first.x_m - second.x_m) ** 2
            + (first.y_m - second.y_m) ** 2
            + (first.z_m - second.z_m) ** 2
        )

    @staticmethod
    def velocity(
        previous: PoseSample | None,
        current: PoseSample,
    ) -> Velocity:
        if previous is None:
            return Velocity(0.0, 0.0, 0.0)

        delta_t = (
            current.timestamp_s
            - previous.timestamp_s
        )

        if delta_t <= 0.0:
            return Velocity(0.0, 0.0, 0.0)

        return Velocity(
            (current.x_m - previous.x_m)
            / delta_t,
            (current.y_m - previous.y_m)
            / delta_t,
            (current.z_m - previous.z_m)
            / delta_t,
        )

    def closest_approach(
        self,
        first: PoseSample,
        second: PoseSample,
        first_velocity: Velocity,
        second_velocity: Velocity,
    ) -> tuple[float, float, float]:
        relative_position = (
            first.x_m - second.x_m,
            first.y_m - second.y_m,
            first.z_m - second.z_m,
        )
        relative_velocity = (
            first_velocity.x_m_s
            - second_velocity.x_m_s,
            first_velocity.y_m_s
            - second_velocity.y_m_s,
            first_velocity.z_m_s
            - second_velocity.z_m_s,
        )

        speed_squared = sum(
            value * value
            for value in relative_velocity
        )
        closing_speed_m_s = 0.0

        current_distance_m = math.sqrt(
            sum(
                value * value
                for value in relative_position
            )
        )

        if speed_squared <= 1e-9:
            return (
                0.0,
                current_distance_m,
                closing_speed_m_s,
            )

        dot = sum(
            position * velocity
            for position, velocity in zip(
                relative_position,
                relative_velocity,
            )
        )

        relative_speed = math.sqrt(
            speed_squared
        )

        if current_distance_m > 1e-9:
            closing_speed_m_s = max(
                0.0,
                -dot / current_distance_m,
            )

        time_to_closest_s = max(
            0.0,
            min(
                self.horizon_s,
                -dot / speed_squared,
            ),
        )

        closest_vector = tuple(
            position
            + velocity * time_to_closest_s
            for position, velocity in zip(
                relative_position,
                relative_velocity,
            )
        )

        closest_distance_m = math.sqrt(
            sum(
                value * value
                for value in closest_vector
            )
        )

        if (
            relative_speed
            < self.minimum_closing_speed_m_s
        ):
            time_to_closest_s = 0.0
            closest_distance_m = current_distance_m

        return (
            time_to_closest_s,
            closest_distance_m,
            closing_speed_m_s,
        )

    def classify(
        self,
        current_distance_m: float,
        closest_distance_m: float,
    ) -> str:
        effective_distance_m = min(
            current_distance_m,
            closest_distance_m,
        )

        if (
            effective_distance_m
            <= self.emergency_distance_m
        ):
            return "emergency_stop"

        if (
            effective_distance_m
            <= self.critical_distance_m
        ):
            return "critical"

        if (
            effective_distance_m
            <= self.warning_distance_m
        ):
            return "warning"

        return "clear"


class InterDroneCollisionMonitor:
    def __init__(
        self,
        config_path: str | Path,
    ) -> None:
        self.config_path = Path(
            config_path
        )
        config = yaml.safe_load(
            self.config_path.read_text()
        )

        monitor = config["monitor"]
        prediction = config["prediction"]
        thresholds = config["thresholds"]
        outputs = config["outputs"]

        self.mode = str(monitor["mode"])
        self.topic = str(
            monitor["gazebo_pose_topic"]
        )
        self.poll_timeout_s = float(
            monitor["poll_timeout_s"]
        )
        self.stale_pose_timeout_s = float(
            monitor["stale_pose_timeout_s"]
        )
        self.minimum_update_interval_s = float(
            monitor["minimum_update_interval_s"]
        )
        self.log_every_evaluation = bool(
            monitor["log_every_evaluation"]
        )

        self.actions = {
            str(key): str(value)
            for key, value
            in config["actions"].items()
        }

        self.drone_by_model = {
            str(item["model_name"]): {
                "drone_id": str(
                    item["drone_id"]
                ),
                "priority": int(
                    item["priority"]
                ),
            }
            for item in config["drones"]
        }
        self.priority_by_drone = {
            value["drone_id"]:
                int(value["priority"])
            for value
            in self.drone_by_model.values()
        }

        self.predictor = CollisionPredictor(
            horizon_s=float(
                prediction["horizon_s"]
            ),
            minimum_closing_speed_m_s=float(
                prediction[
                    "minimum_closing_speed_m_s"
                ]
            ),
            emergency_distance_m=float(
                thresholds[
                    "emergency_distance_m"
                ]
            ),
            critical_distance_m=float(
                thresholds[
                    "critical_distance_m"
                ]
            ),
            warning_distance_m=float(
                thresholds[
                    "warning_distance_m"
                ]
            ),
        )

        self.event_log_path = Path(
            outputs["event_log_csv"]
        )
        self.status_path = Path(
            outputs["status_json"]
        )
        self.event_log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.status_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_log()
        self.previous_samples: dict[
            str,
            PoseSample,
        ] = {}
        self.current_samples: dict[
            str,
            PoseSample,
        ] = {}
        self.stop_requested = False

    def _initialize_log(self) -> None:
        if (
            self.event_log_path.exists()
            and self.event_log_path.stat().st_size
        ):
            return

        with self.event_log_path.open(
            "w",
            newline="",
        ) as file:
            csv.writer(file).writerow([
                "timestamp_utc",
                "drone_a",
                "drone_b",
                "current_distance_m",
                "closest_distance_m",
                "time_to_closest_s",
                "closing_speed_m_s",
                "state",
                "yielding_drone",
                "recommended_action",
                "mode",
            ])

    def request_stop(
        self,
        *_: Any,
    ) -> None:
        self.stop_requested = True

    def _yielding_drone(
        self,
        first_drone: str,
        second_drone: str,
    ) -> str:
        first_priority = (
            self.priority_by_drone[
                first_drone
            ]
        )
        second_priority = (
            self.priority_by_drone[
                second_drone
            ]
        )

        if first_priority == second_priority:
            return max(
                first_drone,
                second_drone,
            )

        return (
            first_drone
            if first_priority > second_priority
            else second_drone
        )

    def evaluate(
        self,
        samples: dict[str, PoseSample],
        previous_samples: dict[
            str,
            PoseSample,
        ],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for first_id, second_id in combinations(
            sorted(samples),
            2,
        ):
            first = samples[first_id]
            second = samples[second_id]

            first_velocity = (
                self.predictor.velocity(
                    previous_samples.get(
                        first_id
                    ),
                    first,
                )
            )
            second_velocity = (
                self.predictor.velocity(
                    previous_samples.get(
                        second_id
                    ),
                    second,
                )
            )

            current_distance_m = (
                self.predictor.distance(
                    first,
                    second,
                )
            )
            (
                time_to_closest_s,
                closest_distance_m,
                closing_speed_m_s,
            ) = self.predictor.closest_approach(
                first,
                second,
                first_velocity,
                second_velocity,
            )
            state = self.predictor.classify(
                current_distance_m,
                closest_distance_m,
            )

            yielding_drone = (
                None
                if state == "clear"
                else self._yielding_drone(
                    first_id,
                    second_id,
                )
            )

            results.append({
                "drone_a": first_id,
                "drone_b": second_id,
                "current_distance_m":
                    round(
                        current_distance_m,
                        3,
                    ),
                "closest_distance_m":
                    round(
                        closest_distance_m,
                        3,
                    ),
                "time_to_closest_s":
                    round(
                        time_to_closest_s,
                        3,
                    ),
                "closing_speed_m_s":
                    round(
                        closing_speed_m_s,
                        3,
                    ),
                "state": state,
                "yielding_drone":
                    yielding_drone,
                "recommended_action":
                    self.actions[state],
                "mode": self.mode,
            })

        return results

    def _write_results(
        self,
        results: list[dict[str, Any]],
    ) -> None:
        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        if self.log_every_evaluation:
            with self.event_log_path.open(
                "a",
                newline="",
            ) as file:
                writer = csv.writer(file)

                for result in results:
                    writer.writerow([
                        timestamp,
                        result["drone_a"],
                        result["drone_b"],
                        result[
                            "current_distance_m"
                        ],
                        result[
                            "closest_distance_m"
                        ],
                        result[
                            "time_to_closest_s"
                        ],
                        result[
                            "closing_speed_m_s"
                        ],
                        result["state"],
                        result[
                            "yielding_drone"
                        ],
                        result[
                            "recommended_action"
                        ],
                        result["mode"],
                    ])

        payload = {
            "timestamp_utc": timestamp,
            "mode": self.mode,
            "pairs": results,
        }

        self._atomic_json_write(
            self.status_path,
            payload,
        )

    @staticmethod
    def _atomic_json_write(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=path.parent,
        ) as file:
            json.dump(
                payload,
                file,
                indent=2,
            )
            temporary_path = Path(
                file.name
            )

        os.replace(
            temporary_path,
            path,
        )

    def _consume_pose_stream(
        self,
        lines: Iterable[str],
    ) -> None:
        target_models = set(
            self.drone_by_model
        )
        in_pose = False
        in_position = False
        current_name: str | None = None
        coordinates: dict[str, float] = {}
        brace_depth = 0
        last_evaluation_time = 0.0

        for raw_line in lines:
            if self.stop_requested:
                break

            line = raw_line.strip()

            if line == "pose {":
                in_pose = True
                in_position = False
                current_name = None
                coordinates = {}
                brace_depth = 1
                continue

            if not in_pose:
                continue

            brace_depth += line.count("{")
            brace_depth -= line.count("}")

            if line.startswith("name:"):
                current_name = (
                    line.split(
                        ":",
                        1,
                    )[1]
                    .strip()
                    .strip('"')
                )

            if line == "position {":
                in_position = True

            elif (
                in_position
                and line.startswith(
                    ("x:", "y:", "z:")
                )
            ):
                key, value = line.split(
                    ":",
                    1,
                )
                coordinates[
                    key.strip()
                ] = float(
                    value.strip()
                )

            elif (
                in_position
                and line == "}"
            ):
                in_position = False

            if brace_depth > 0:
                continue

            in_pose = False

            if (
                current_name
                not in target_models
            ):
                continue

            if not all(
                key in coordinates
                for key in ("x", "y", "z")
            ):
                continue

            now = time.monotonic()
            drone_data = (
                self.drone_by_model[
                    current_name
                ]
            )
            drone_id = str(
                drone_data["drone_id"]
            )

            sample = PoseSample(
                drone_id=drone_id,
                model_name=current_name,
                timestamp_s=now,
                x_m=coordinates["x"],
                y_m=coordinates["y"],
                z_m=coordinates["z"],
            )

            old_current = (
                self.current_samples.get(
                    drone_id
                )
            )
            if old_current is not None:
                self.previous_samples[
                    drone_id
                ] = old_current

            self.current_samples[
                drone_id
            ] = sample

            if (
                now - last_evaluation_time
                < self.minimum_update_interval_s
            ):
                continue

            expected_count = len(
                self.priority_by_drone
            )
            if (
                len(self.current_samples)
                < expected_count
            ):
                continue

            fresh_samples = {
                key: value
                for key, value
                in self.current_samples.items()
                if (
                    now - value.timestamp_s
                    <= self.stale_pose_timeout_s
                )
            }

            if (
                len(fresh_samples)
                < expected_count
            ):
                continue

            results = self.evaluate(
                fresh_samples,
                self.previous_samples,
            )
            self._write_results(
                results
            )
            last_evaluation_time = now

            summary = " | ".join(
                (
                    f"{item['drone_a']}-"
                    f"{item['drone_b']}:"
                    f"{item['state']} "
                    f"{item['current_distance_m']:.2f}m"
                )
                for item in results
            )
            print(
                f"[collision-monitor] {summary}",
                flush=True,
            )

    def run(self) -> None:
        print(
            "[collision-monitor] mode="
            f"{self.mode}",
            flush=True,
        )
        print(
            "[collision-monitor] topic="
            f"{self.topic}",
            flush=True,
        )

        command = [
            "gz",
            "topic",
            "-e",
            "-t",
            self.topic,
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            assert process.stdout is not None
            self._consume_pose_stream(
                process.stdout
            )
        finally:
            process.terminate()

            try:
                process.wait(
                    timeout=3
                )
            except subprocess.TimeoutExpired:
                process.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Configuration-driven inter-drone "
            "collision prediction monitor"
        )
    )
    parser.add_argument(
        "--config",
        default=(
            "configs/safety/"
            "v1_swarm_inter_drone_collision.yaml"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    monitor = InterDroneCollisionMonitor(
        args.config
    )

    signal.signal(
        signal.SIGINT,
        monitor.request_stop,
    )
    signal.signal(
        signal.SIGTERM,
        monitor.request_stop,
    )

    monitor.run()


if __name__ == "__main__":
    main()
