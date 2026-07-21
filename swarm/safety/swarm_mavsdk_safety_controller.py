#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rclpy
import yaml
from rclpy.node import Node
from std_msgs.msg import String


class SwarmMavsdkSafetyController(Node):
    def __init__(self, config_path: Path) -> None:
        self.config = yaml.safe_load(config_path.read_text())

        controller_config = self.config["controller"]

        super().__init__(controller_config["node_name"])

        self.mode = str(controller_config["mode"])
        self.command_cooldown_s = float(
            controller_config["command_cooldown_s"]
        )
        self.status_timeout_s = float(
            controller_config["status_timeout_s"]
        )
        self.startup_grace_period_s = float(
            controller_config.get("startup_grace_period_s", 15.0)
        )
        self.startup_monotonic = time.monotonic()

        self.actions = self.config["actions"]
        self.drones = {
            drone["drone_id"]: drone
            for drone in self.config["drones"]
        }

        self.latest_status: dict[str, dict[str, Any]] = {}
        self.last_command_time: dict[str, float] = {}
        self.last_command_state: dict[str, str] = {}
        self.status_subscriptions = []

        self.log_path = Path(
            controller_config["decision_log_csv"]
        )
        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize_log()

        for drone_id, drone_config in self.drones.items():
            subscription = self.create_subscription(
                String,
                drone_config["status_topic"],
                lambda message, selected_drone=drone_id:
                    self._status_callback(
                        message,
                        selected_drone,
                    ),
                10,
            )

            self.status_subscriptions.append(subscription)

            self.get_logger().info(
                f"{drone_id}: listening on "
                f"{drone_config['status_topic']}"
            )

        self.create_timer(
            1.0,
            self._check_stale_statuses,
        )

        self.get_logger().info(
            f"Safety controller mode: {self.mode}"
        )

        if self.mode == "dry_run":
            self.get_logger().warning(
                "DRY-RUN MODE: no MAVSDK commands will be sent."
            )

    def _initialize_log(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            return

        with self.log_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "timestamp_utc",
                    "drone_id",
                    "safety_state",
                    "command",
                    "speed_m_s",
                    "front_min_m",
                    "scan_age_s",
                    "controller_mode",
                    "result",
                ]
            )

    def _status_callback(
        self,
        message: String,
        drone_id: str,
    ) -> None:
        try:
            status = json.loads(message.data)
        except json.JSONDecodeError as error:
            self.get_logger().error(
                f"{drone_id}: invalid JSON status: {error}"
            )
            return

        self.latest_status[drone_id] = {
            "received_monotonic": time.monotonic(),
            "status": status,
        }

        safety_state = str(
            status.get("safety_state", "no_data")
        )

        self._process_decision(
            drone_id=drone_id,
            safety_state=safety_state,
            status=status,
        )

    def _check_stale_statuses(self) -> None:
        now = time.monotonic()

        if (
            now - self.startup_monotonic
            < self.startup_grace_period_s
        ):
            return

        for drone_id in self.drones:
            latest = self.latest_status.get(drone_id)

            if latest is None:
                self._process_decision(
                    drone_id=drone_id,
                    safety_state="no_data",
                    status={},
                )
                continue

            status_age_s = (
                now - latest["received_monotonic"]
            )

            if status_age_s > self.status_timeout_s:
                stale_status = dict(latest["status"])
                stale_status["scan_age_s"] = round(
                    status_age_s,
                    3,
                )

                self._process_decision(
                    drone_id=drone_id,
                    safety_state="no_data",
                    status=stale_status,
                )

    def _process_decision(
        self,
        drone_id: str,
        safety_state: str,
        status: dict[str, Any],
    ) -> None:
        action_config = self.actions.get(
            safety_state,
            self.actions["no_data"],
        )

        command = str(action_config["command"])
        speed_m_s = action_config.get("speed_m_s")

        previous_state = self.last_command_state.get(
            drone_id
        )
        last_time = self.last_command_time.get(
            drone_id,
            0.0,
        )

        state_changed = previous_state != safety_state
        cooldown_complete = (
            time.monotonic() - last_time
            >= self.command_cooldown_s
        )

        if not state_changed and not cooldown_complete:
            return

        if not state_changed and command == "none":
            return

        if self.mode == "dry_run":
            result = "dry_run_logged"
        else:
            result = "live_mode_not_enabled"

        front_distance = status.get("front_min_m")
        scan_age_s = status.get("scan_age_s")

        command_description = command

        if command == "set_current_speed":
            command_description = (
                f"{command}({speed_m_s} m/s)"
            )

        self.get_logger().info(
            f"{drone_id}: state={safety_state} | "
            f"front={front_distance} m | "
            f"decision={command_description} | "
            f"result={result}"
        )

        self._write_log(
            drone_id=drone_id,
            safety_state=safety_state,
            command=command,
            speed_m_s=speed_m_s,
            front_min_m=front_distance,
            scan_age_s=scan_age_s,
            result=result,
        )

        self.last_command_state[drone_id] = safety_state
        self.last_command_time[drone_id] = time.monotonic()

    def _write_log(
        self,
        drone_id: str,
        safety_state: str,
        command: str,
        speed_m_s: Any,
        front_min_m: Any,
        scan_age_s: Any,
        result: str,
    ) -> None:
        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with self.log_path.open("a", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    timestamp,
                    drone_id,
                    safety_state,
                    command,
                    speed_m_s,
                    front_min_m,
                    scan_age_s,
                    self.mode,
                    result,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default=(
            "configs/safety/"
            "v1_swarm_mavsdk_safety_controller.yaml"
        ),
    )

    arguments = parser.parse_args()

    rclpy.init()

    node = SwarmMavsdkSafetyController(
        Path(arguments.config)
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
