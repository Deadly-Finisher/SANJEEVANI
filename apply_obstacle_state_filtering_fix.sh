#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

cd "$PROJECT_ROOT"

MONITOR="swarm/safety/swarm_obstacle_monitor.py"
CONFIG="configs/safety/v1_swarm_obstacle_monitor.yaml"
BACKUP_DIR="backups/obstacle_avoidance"

mkdir -p "$BACKUP_DIR"

cp "$MONITOR" \
  "$BACKUP_DIR/swarm_obstacle_monitor_before_filtering.py"

cp "$CONFIG" \
  "$BACKUP_DIR/v1_swarm_obstacle_monitor_before_filtering.yaml"

cat > "$CONFIG" <<'YAML'
monitor:
  node_name: v1_swarm_obstacle_monitor
  publish_rate_hz: 2.0
  stale_scan_timeout_s: 12.0
  log_every_publish: true
  log_csv: outputs/swarm/v1_three_drone_swarm/safety/obstacle_distance_log.csv

sectors:
  front:
    minimum_angle_deg: -35.0
    maximum_angle_deg: 35.0
  left:
    minimum_angle_deg: 35.0
    maximum_angle_deg: 135.0
  right:
    minimum_angle_deg: -135.0
    maximum_angle_deg: -35.0

thresholds:
  emergency_stop_m: 5.0
  critical_m: 8.0
  warning_m: 12.0

filtering:
  minimum_cluster_points: 2
  startup_consecutive_scans: 2
  enter_consecutive_scans: 2
  clear_consecutive_scans: 2
  hysteresis_m:
    emergency_stop: 0.75
    critical: 1.0
    warning: 1.0

state_actions:
  clear: continue_mission
  warning: reduce_speed
  critical: hover_and_replan
  emergency_stop: immediate_hover
  no_data: hold_position

drones:
  - drone_id: drone_1
    scan_topic: /drone_1/scan
    status_topic: /drone_1/obstacle_status
  - drone_id: drone_2
    scan_topic: /drone_2/scan
    status_topic: /drone_2/obstacle_status
  - drone_id: drone_3
    scan_topic: /drone_3/scan
    status_topic: /drone_3/obstacle_status

control_limits:
  maximum_test_speed_m_s: 0.3
  reduced_speed_m_s: 0.15
  hover_duration_s: 5.0
  minimum_clearance_m: 5.0
  command_cooldown_s: 3.0
YAML

cat > "$MONITOR" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


class SwarmObstacleMonitor(Node):
    SEVERITY = {
        "no_data": -1,
        "clear": 0,
        "warning": 1,
        "critical": 2,
        "emergency_stop": 3,
    }

    def __init__(self, config_path: Path) -> None:
        self.config = yaml.safe_load(config_path.read_text())
        monitor_config = self.config["monitor"]
        super().__init__(monitor_config["node_name"])

        self.publish_rate_hz = float(monitor_config["publish_rate_hz"])
        self.stale_timeout_s = float(monitor_config["stale_scan_timeout_s"])
        self.log_every_publish = bool(monitor_config["log_every_publish"])

        self.sectors = self.config["sectors"]
        self.thresholds = self.config["thresholds"]
        self.state_actions = self.config["state_actions"]

        filtering = self.config["filtering"]
        self.minimum_cluster_points = int(filtering["minimum_cluster_points"])
        self.startup_consecutive_scans = int(filtering["startup_consecutive_scans"])
        self.enter_consecutive_scans = int(filtering["enter_consecutive_scans"])
        self.clear_consecutive_scans = int(filtering["clear_consecutive_scans"])
        self.hysteresis = {
            key: float(value)
            for key, value in filtering["hysteresis_m"].items()
        }

        self.latest: dict[str, dict[str, Any]] = {}
        self.previous_states: dict[str, str] = {}
        self.stable_states: dict[str, str] = {}
        self.pending_states: dict[str, str] = {}
        self.pending_counts: dict[str, int] = {}
        self.status_publishers = {}

        self.log_path = Path(monitor_config["log_csv"])
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_log()

        for drone in self.config["drones"]:
            drone_id = drone["drone_id"]
            self.stable_states[drone_id] = "no_data"
            self.pending_states[drone_id] = "no_data"
            self.pending_counts[drone_id] = 0

            self.status_publishers[drone_id] = self.create_publisher(
                String,
                drone["status_topic"],
                10,
            )

            self.create_subscription(
                LaserScan,
                drone["scan_topic"],
                lambda message, drone_config=drone: self._scan_callback(
                    message,
                    drone_config,
                ),
                qos_profile_sensor_data,
            )

            self.get_logger().info(
                f"{drone_id}: subscribed to {drone['scan_topic']}"
            )

        self.create_timer(1.0 / self.publish_rate_hz, self._publish_statuses)
        self.get_logger().info(
            "Temporal confirmation, cluster filtering, and hysteresis are enabled."
        )

    def _initialize_log(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size > 0:
            return

        with self.log_path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                "timestamp_utc",
                "drone_id",
                "front_min_m",
                "left_min_m",
                "right_min_m",
                "safety_state",
                "recommended_action",
                "scan_age_s",
            ])

    def _sector_distance(
        self,
        scan: LaserScan,
        minimum_angle_deg: float,
        maximum_angle_deg: float,
    ) -> float:
        samples: list[tuple[int, float]] = []

        for index, distance in enumerate(scan.ranges):
            angle_rad = scan.angle_min + (index * scan.angle_increment)
            angle_deg = math.degrees(angle_rad)
            inside_sector = minimum_angle_deg <= angle_deg <= maximum_angle_deg
            valid_distance = (
                math.isfinite(distance)
                and scan.range_min <= distance <= scan.range_max
            )

            if inside_sector and valid_distance:
                samples.append((index, float(distance)))

        if not samples:
            return float(scan.range_max)

        clusters: list[list[float]] = []
        current_cluster: list[float] = []
        previous_index: int | None = None

        for index, distance in samples:
            if previous_index is None or index == previous_index + 1:
                current_cluster.append(distance)
            else:
                if current_cluster:
                    clusters.append(current_cluster)
                current_cluster = [distance]
            previous_index = index

        if current_cluster:
            clusters.append(current_cluster)

        valid_clusters = [
            cluster
            for cluster in clusters
            if len(cluster) >= self.minimum_cluster_points
        ]

        if not valid_clusters:
            return float(scan.range_max)

        return min(min(cluster) for cluster in valid_clusters)

    def _candidate_state(
        self,
        front_distance: float,
        current_state: str,
    ) -> str:
        emergency = float(self.thresholds["emergency_stop_m"])
        critical = float(self.thresholds["critical_m"])
        warning = float(self.thresholds["warning_m"])

        if front_distance <= emergency:
            return "emergency_stop"
        if (
            current_state == "emergency_stop"
            and front_distance <= emergency + self.hysteresis["emergency_stop"]
        ):
            return "emergency_stop"

        if front_distance <= critical:
            return "critical"
        if (
            current_state == "critical"
            and front_distance <= critical + self.hysteresis["critical"]
        ):
            return "critical"

        if front_distance <= warning:
            return "warning"
        if (
            current_state == "warning"
            and front_distance <= warning + self.hysteresis["warning"]
        ):
            return "warning"

        return "clear"

    def _confirmed_state(self, drone_id: str, candidate_state: str) -> str:
        stable_state = self.stable_states[drone_id]

        if candidate_state == stable_state:
            self.pending_states[drone_id] = candidate_state
            self.pending_counts[drone_id] = 0
            return stable_state

        if self.pending_states[drone_id] == candidate_state:
            self.pending_counts[drone_id] += 1
        else:
            self.pending_states[drone_id] = candidate_state
            self.pending_counts[drone_id] = 1

        if stable_state == "no_data":
            required_scans = self.startup_consecutive_scans
        elif self.SEVERITY[candidate_state] > self.SEVERITY[stable_state]:
            required_scans = self.enter_consecutive_scans
        else:
            required_scans = self.clear_consecutive_scans

        if self.pending_counts[drone_id] >= required_scans:
            self.stable_states[drone_id] = candidate_state
            self.pending_counts[drone_id] = 0
            return candidate_state

        return stable_state

    def _scan_callback(
        self,
        scan: LaserScan,
        drone_config: dict[str, Any],
    ) -> None:
        drone_id = drone_config["drone_id"]
        distances = {}

        for sector_name, sector_config in self.sectors.items():
            distances[sector_name] = self._sector_distance(
                scan,
                float(sector_config["minimum_angle_deg"]),
                float(sector_config["maximum_angle_deg"]),
            )

        candidate_state = self._candidate_state(
            distances["front"],
            self.stable_states[drone_id],
        )
        safety_state = self._confirmed_state(drone_id, candidate_state)

        self.latest[drone_id] = {
            "received_monotonic": time.monotonic(),
            "front_min_m": distances["front"],
            "left_min_m": distances["left"],
            "right_min_m": distances["right"],
            "raw_safety_state": candidate_state,
            "safety_state": safety_state,
            "confirmation_count": self.pending_counts[drone_id],
            "recommended_action": self.state_actions[safety_state],
        }

    def _publish_statuses(self) -> None:
        now_monotonic = time.monotonic()
        timestamp_utc = datetime.now(timezone.utc).isoformat()

        for drone in self.config["drones"]:
            drone_id = drone["drone_id"]
            latest = self.latest.get(drone_id)

            if latest is None:
                status = {
                    "timestamp_utc": timestamp_utc,
                    "drone_id": drone_id,
                    "front_min_m": None,
                    "left_min_m": None,
                    "right_min_m": None,
                    "raw_safety_state": "no_data",
                    "safety_state": "no_data",
                    "confirmation_count": 0,
                    "recommended_action": self.state_actions["no_data"],
                    "scan_age_s": None,
                }
            else:
                scan_age_s = now_monotonic - latest["received_monotonic"]

                if scan_age_s > self.stale_timeout_s:
                    safety_state = "no_data"
                    recommended_action = self.state_actions["no_data"]
                else:
                    safety_state = latest["safety_state"]
                    recommended_action = latest["recommended_action"]

                status = {
                    "timestamp_utc": timestamp_utc,
                    "drone_id": drone_id,
                    "front_min_m": round(latest["front_min_m"], 3),
                    "left_min_m": round(latest["left_min_m"], 3),
                    "right_min_m": round(latest["right_min_m"], 3),
                    "raw_safety_state": latest["raw_safety_state"],
                    "safety_state": safety_state,
                    "confirmation_count": latest["confirmation_count"],
                    "recommended_action": recommended_action,
                    "scan_age_s": round(scan_age_s, 3),
                }

            message = String()
            message.data = json.dumps(status)
            self.status_publishers[drone_id].publish(message)

            previous_state = self.previous_states.get(drone_id)
            current_state = status["safety_state"]

            if previous_state != current_state:
                self.get_logger().info(
                    f"{drone_id}: {current_state} | "
                    f"raw={status['raw_safety_state']} | "
                    f"front={status['front_min_m']} m | "
                    f"action={status['recommended_action']}"
                )
                self.previous_states[drone_id] = current_state

            if self.log_every_publish:
                self._write_log(status)

    def _write_log(self, status: dict[str, Any]) -> None:
        with self.log_path.open("a", newline="") as file:
            writer = csv.writer(file)
            writer.writerow([
                status["timestamp_utc"],
                status["drone_id"],
                status["front_min_m"],
                status["left_min_m"],
                status["right_min_m"],
                status["safety_state"],
                status["recommended_action"],
                status["scan_age_s"],
            ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/safety/v1_swarm_obstacle_monitor.yaml",
    )
    arguments = parser.parse_args()

    rclpy.init()
    node = SwarmObstacleMonitor(Path(arguments.config))

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
PY

"$PYTHON_BIN" -m py_compile "$MONITOR"

echo
echo "===== FILTER CONFIG ====="
grep -nA12 "^filtering:" "$CONFIG"

echo
echo "===== MONITOR CHECK ====="
grep -nE \
  "minimum_cluster_points|startup_consecutive_scans|enter_consecutive_scans|clear_consecutive_scans|hysteresis|raw_safety_state" \
  "$MONITOR"

echo
echo "Obstacle-state filtering patch applied successfully."
