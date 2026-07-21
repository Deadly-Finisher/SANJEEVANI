#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pymavlink import mavutil


EARTH_RADIUS_M = 6378137.0


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: str | Path) -> dict:
    data = yaml.safe_load(
        Path(path).read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Invalid YAML mapping: {path}"
        )

    return data


def endpoint_from(address: str) -> str:
    if address.startswith("udpin://"):
        return "udpin:" + address[len("udpin://"):]

    if address.startswith("udp://"):
        return "udpin:" + address[len("udp://"):]

    return address


def offset_lat_lon(
    latitude_deg: float,
    longitude_deg: float,
    north_m: float,
    east_m: float,
) -> tuple[float, float]:
    latitude_rad = math.radians(latitude_deg)

    new_latitude = (
        latitude_deg
        + math.degrees(
            north_m / EARTH_RADIUS_M
        )
    )

    longitude_divisor = (
        EARTH_RADIUS_M
        * max(
            math.cos(latitude_rad),
            1e-6,
        )
    )

    new_longitude = (
        longitude_deg
        + math.degrees(
            east_m / longitude_divisor
        )
    )

    return new_latitude, new_longitude


def horizontal_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = math.radians(lon2 - lon1)

    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2.0) ** 2
    )

    return (
        2.0
        * EARTH_RADIUS_M
        * math.asin(
            min(
                1.0,
                math.sqrt(value),
            )
        )
    )


class DirectMavlinkVehicle:
    def __init__(
        self,
        *,
        drone_id: str,
        endpoint: str,
        source_system: int,
        source_component: int,
        telemetry_path: Path,
        telemetry_interval_s: float,
    ) -> None:
        self.drone_id = drone_id

        self.master = (
            mavutil.mavlink_connection(
                endpoint,
                source_system=source_system,
                source_component=source_component,
                autoreconnect=True,
            )
        )

        self.target_system = 0
        self.target_component = 1

        self.armed = False
        self.position = None
        self.home = None

        self.mission_status = "connecting"
        self.current_zone = ""

        self.last_gcs_heartbeat = 0.0
        self.last_telemetry_write = 0.0

        self.telemetry_interval_s = (
            telemetry_interval_s
        )

        telemetry_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.telemetry_file = (
            telemetry_path.open(
                "w",
                newline="",
                encoding="utf-8",
            )
        )

        self.telemetry_writer = csv.DictWriter(
            self.telemetry_file,
            fieldnames=[
                "timestamp_utc",
                "drone_id",
                "mission_status",
                "current_zone",
                "latitude_deg",
                "longitude_deg",
                "absolute_altitude_m",
                "relative_altitude_m",
                "local_north_m",
                "local_east_m",
            ],
        )

        self.telemetry_writer.writeheader()

    def close(self) -> None:
        try:
            self.telemetry_file.close()
        finally:
            try:
                self.master.close()
            except Exception:
                pass

    def send_gcs_heartbeat(self) -> None:
        now = time.monotonic()

        if (
            now - self.last_gcs_heartbeat
            < 1.0
        ):
            return

        self.master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            mavutil.mavlink.MAV_STATE_ACTIVE,
        )

        self.last_gcs_heartbeat = now

    def process_message(self, message) -> None:
        message_type = message.get_type()

        if message_type == "HEARTBEAT":
            if self.target_system == 0:
                self.target_system = int(
                    message.get_srcSystem()
                )

                self.target_component = (
                    int(
                        message.get_srcComponent()
                    )
                    or 1
                )

            if (
                int(message.get_srcSystem())
                == self.target_system
            ):
                self.armed = bool(
                    int(message.base_mode)
                    & mavutil.mavlink
                    .MAV_MODE_FLAG_SAFETY_ARMED
                )

        elif (
            message_type
            == "GLOBAL_POSITION_INT"
        ):
            if (
                self.target_system
                and int(message.get_srcSystem())
                != self.target_system
            ):
                return

            self.position = {
                "lat": float(message.lat) / 1e7,
                "lon": float(message.lon) / 1e7,
                "absolute_altitude_m": (
                    float(message.alt)
                    / 1000.0
                ),
                "relative_altitude_m": (
                    float(message.relative_alt)
                    / 1000.0
                ),
            }

            if (
                self.home is None
                and self.position["lat"] != 0.0
                and self.position["lon"] != 0.0
            ):
                self.home = (
                    self.position["lat"],
                    self.position["lon"],
                )

            self.write_telemetry_if_due()

        elif message_type == "STATUSTEXT":
            text = message.text

            if isinstance(text, bytes):
                text = text.decode(
                    errors="replace"
                )

            text = str(text).rstrip("\x00")

            if text:
                print(
                    f"[{self.drone_id}] "
                    f"PX4: {text}",
                    flush=True,
                )

        elif message_type == "COMMAND_ACK":
            print(
                f"[{self.drone_id}] "
                f"ACK command="
                f"{int(message.command)} "
                f"result="
                f"{int(message.result)}",
                flush=True,
            )

    def write_telemetry_if_due(self) -> None:
        if (
            self.position is None
            or self.home is None
        ):
            return

        now = time.monotonic()

        if (
            now - self.last_telemetry_write
            < self.telemetry_interval_s
        ):
            return

        north_m = (
            math.radians(
                self.position["lat"]
                - self.home[0]
            )
            * EARTH_RADIUS_M
        )

        east_m = (
            math.radians(
                self.position["lon"]
                - self.home[1]
            )
            * EARTH_RADIUS_M
            * math.cos(
                math.radians(
                    self.home[0]
                )
            )
        )

        self.telemetry_writer.writerow({
            "timestamp_utc": now_utc(),
            "drone_id": self.drone_id,
            "mission_status":
                self.mission_status,
            "current_zone":
                self.current_zone,
            "latitude_deg":
                self.position["lat"],
            "longitude_deg":
                self.position["lon"],
            "absolute_altitude_m":
                self.position[
                    "absolute_altitude_m"
                ],
            "relative_altitude_m":
                self.position[
                    "relative_altitude_m"
                ],
            "local_north_m":
                round(north_m, 3),
            "local_east_m":
                round(east_m, 3),
        })

        self.telemetry_file.flush()
        self.last_telemetry_write = now

    def pump(
        self,
        timeout_s: float = 0.5,
    ):
        self.send_gcs_heartbeat()

        message = self.master.recv_match(
            blocking=True,
            timeout=timeout_s,
        )

        if message is not None:
            self.process_message(message)

        return message

    def wait_heartbeat(
        self,
        timeout_s: float,
    ) -> None:
        deadline = (
            time.monotonic()
            + timeout_s
        )

        while time.monotonic() < deadline:
            message = self.pump(0.5)

            if (
                message is not None
                and message.get_type()
                == "HEARTBEAT"
            ):
                print(
                    f"[{self.drone_id}] "
                    "direct MAVLink connected | "
                    f"system={self.target_system}",
                    flush=True,
                )

                return

        raise TimeoutError(
            "PX4 heartbeat not received"
        )

    def wait_position(
        self,
        timeout_s: float,
    ) -> None:
        deadline = (
            time.monotonic()
            + timeout_s
        )

        while time.monotonic() < deadline:
            self.pump(0.5)

            if (
                self.position is not None
                and self.home is not None
            ):
                print(
                    f"[{self.drone_id}] "
                    "global position ready",
                    flush=True,
                )

                return

        raise TimeoutError(
            "GLOBAL_POSITION_INT "
            "not received"
        )

    def hold(
        self,
        duration_s: float,
    ) -> None:
        deadline = (
            time.monotonic()
            + duration_s
        )

        while time.monotonic() < deadline:
            remaining = (
                deadline
                - time.monotonic()
            )

            self.pump(
                min(
                    0.5,
                    max(0.05, remaining),
                )
            )

    def command_long(
        self,
        command: int,
        parameters: list[float],
    ) -> None:
        values = (
            parameters
            + [0.0] * 7
        )[:7]

        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            command,
            0,
            *values,
        )

    def arm(
        self,
        *,
        force: bool,
        timeout_s: float,
        resend_interval_s: float,
    ) -> None:
        self.mission_status = "arming"

        deadline = (
            time.monotonic()
            + timeout_s
        )

        next_send = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()

            if now >= next_send:
                print(
                    f"[{self.drone_id}] "
                    "sending direct arm command "
                    f"(force={force})",
                    flush=True,
                )

                self.command_long(
                    mavutil.mavlink
                    .MAV_CMD_COMPONENT_ARM_DISARM,
                    [
                        1.0,
                        (
                            21196.0
                            if force
                            else 0.0
                        ),
                    ],
                )

                next_send = (
                    now
                    + resend_interval_s
                )

            self.pump(0.5)

            if self.armed:
                print(
                    f"[{self.drone_id}] "
                    "armed state confirmed",
                    flush=True,
                )

                return

        raise TimeoutError(
            "PX4 did not enter armed state"
        )

    def takeoff(
        self,
        *,
        altitude_m: float,
        confirmation_fraction: float,
        timeout_s: float,
        resend_interval_s: float,
    ) -> None:
        self.mission_status = "taking_off"

        deadline = (
            time.monotonic()
            + timeout_s
        )

        next_send = 0.0

        threshold_m = max(
            1.0,
            altitude_m
            * confirmation_fraction,
        )

        while time.monotonic() < deadline:
            now = time.monotonic()

            if now >= next_send:
                if self.position is None:
                    self.pump(0.5)
                    continue

                ground_absolute_altitude = (
                    self.position[
                        "absolute_altitude_m"
                    ]
                    - self.position[
                        "relative_altitude_m"
                    ]
                )

                target_absolute_altitude = (
                    ground_absolute_altitude
                    + altitude_m
                )

                print(
                    f"[{self.drone_id}] "
                    "sending direct takeoff "
                    f"to {altitude_m:.1f} m",
                    flush=True,
                )

                self.command_long(
                    mavutil.mavlink
                    .MAV_CMD_NAV_TAKEOFF,
                    [
                        0.0,
                        0.0,
                        0.0,
                        math.nan,
                        self.position["lat"],
                        self.position["lon"],
                        target_absolute_altitude,
                    ],
                )

                next_send = (
                    now
                    + resend_interval_s
                )

            self.pump(0.5)

            if (
                self.position is not None
                and self.position[
                    "relative_altitude_m"
                ]
                >= threshold_m
            ):
                print(
                    f"[{self.drone_id}] "
                    "takeoff confirmed",
                    flush=True,
                )

                return

        raise TimeoutError(
            "PX4 did not climb after "
            "takeoff command"
        )

    def goto(
        self,
        *,
        target_latitude: float,
        target_longitude: float,
        target_relative_altitude_m: float,
        yaw_deg: float,
        horizontal_tolerance_m: float,
        altitude_tolerance_m: float,
        timeout_s: float,
        resend_interval_s: float,
        report_interval_s: float,
    ) -> bool:
        self.mission_status = (
            "executing_waypoints"
        )

        deadline = (
            time.monotonic()
            + timeout_s
        )

        next_send = 0.0
        next_report = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()

            if now >= next_send:
                self.master.mav.command_int_send(
                    self.target_system,
                    self.target_component,
                    mavutil.mavlink
                    .MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                    mavutil.mavlink
                    .MAV_CMD_DO_REPOSITION,
                    0,
                    0,
                    -1.0,
                    1.0,
                    0.0,
                    math.radians(yaw_deg),
                    int(
                        round(
                            target_latitude
                            * 1e7
                        )
                    ),
                    int(
                        round(
                            target_longitude
                            * 1e7
                        )
                    ),
                    float(
                        target_relative_altitude_m
                    ),
                )

                next_send = (
                    now
                    + resend_interval_s
                )

            self.pump(0.5)

            if self.position is None:
                continue

            horizontal_error = (
                horizontal_distance_m(
                    self.position["lat"],
                    self.position["lon"],
                    target_latitude,
                    target_longitude,
                )
            )

            altitude_error = abs(
                self.position[
                    "relative_altitude_m"
                ]
                - target_relative_altitude_m
            )

            if now >= next_report:
                print(
                    f"[{self.drone_id}] "
                    "target error: "
                    f"horizontal="
                    f"{horizontal_error:.2f} m, "
                    f"altitude="
                    f"{altitude_error:.2f} m",
                    flush=True,
                )

                next_report = (
                    now
                    + report_interval_s
                )

            if (
                horizontal_error
                <= horizontal_tolerance_m
                and altitude_error
                <= altitude_tolerance_m
            ):
                return True

        return False

    def land(
        self,
        *,
        altitude_threshold_m: float,
        timeout_s: float,
        resend_interval_s: float,
        force_disarm_after_timeout: bool,
    ) -> None:
        self.mission_status = "landing"
        self.current_zone = "landing"

        deadline = (
            time.monotonic()
            + timeout_s
        )

        next_send = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()

            if now >= next_send:
                if self.position is None:
                    self.pump(0.5)
                    continue

                ground_absolute_altitude = (
                    self.position[
                        "absolute_altitude_m"
                    ]
                    - self.position[
                        "relative_altitude_m"
                    ]
                )

                print(
                    f"[{self.drone_id}] "
                    "sending direct land command",
                    flush=True,
                )

                self.command_long(
                    mavutil.mavlink
                    .MAV_CMD_NAV_LAND,
                    [
                        0.0,
                        0.0,
                        0.0,
                        math.nan,
                        self.position["lat"],
                        self.position["lon"],
                        ground_absolute_altitude,
                    ],
                )

                next_send = (
                    now
                    + resend_interval_s
                )

            self.pump(0.5)

            if (
                self.position is not None
                and self.position[
                    "relative_altitude_m"
                ]
                <= altitude_threshold_m
            ):
                print(
                    f"[{self.drone_id}] "
                    "landing confirmed",
                    flush=True,
                )

                return

        if force_disarm_after_timeout:
            print(
                f"[{self.drone_id}] "
                "landing timeout; "
                "sending forced disarm",
                flush=True,
            )

            self.command_long(
                mavutil.mavlink
                .MAV_CMD_COMPONENT_ARM_DISARM,
                [
                    0.0,
                    21196.0,
                ],
            )

            self.hold(2.0)
            return

        raise TimeoutError(
            "Landing was not confirmed"
        )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execution-config",
        default=(
            "configs/swarm/"
            "v1_swarm_mission_execution.yaml"
        ),
    )

    parser.add_argument(
        "--drone-id",
        required=True,
    )

    args = parser.parse_args()

    execution_config = load_yaml(
        args.execution_config
    )

    drone_entry = next(
        (
            drone
            for drone
            in execution_config["drones"]
            if drone["drone_id"]
            == args.drone_id
        ),
        None,
    )

    if drone_entry is None:
        raise RuntimeError(
            f"Unknown drone ID: "
            f"{args.drone_id}"
        )

    mission_config = load_yaml(
        drone_entry["mission_config"]
    )

    execution = (
        execution_config["execution"]
    )

    mission = mission_config["mission"]
    waypoints = mission_config["waypoints"]

    output_directory = Path(
        execution_config[
            "output"
        ]["run_log_dir"]
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path = (
        output_directory
        / (
            f"{args.drone_id}"
            "_mission_summary.json"
        )
    )

    drone_number = int(
        args.drone_id.rsplit(
            "_",
            1,
        )[1]
    )

    summary = {
        "drone_id": args.drone_id,
        "mission_name":
            mission["mission_name"],
        "transport":
            "direct_pymavlink",
        "status": "started",
        "started_at_utc": now_utc(),
        "completed_at_utc": None,
        "completed_waypoints": [],
        "error": None,
        "landing_error": None,
    }

    startup_delay_s = float(
        drone_entry["startup_delay_s"]
    )

    print(
        f"[{args.drone_id}] "
        f"startup delay: "
        f"{startup_delay_s} seconds",
        flush=True,
    )

    time.sleep(startup_delay_s)

    endpoint = endpoint_from(
        mission_config[
            "connection"
        ]["system_address"]
    )

    print(
        f"[{args.drone_id}] "
        f"direct MAVLink endpoint: "
        f"{endpoint}",
        flush=True,
    )

    vehicle = DirectMavlinkVehicle(
        drone_id=args.drone_id,
        endpoint=endpoint,
        source_system=(
            int(
                execution[
                    "gcs_source_system_base"
                ]
            )
            + drone_number
        ),
        source_component=int(
            execution[
                "gcs_source_component"
            ]
        ),
        telemetry_path=Path(
            mission_config[
                "logging"
            ]["telemetry_csv_path"]
        ),
        telemetry_interval_s=float(
            mission_config[
                "logging"
            ]["sample_interval_s"]
        ),
    )

    try:
        vehicle.wait_heartbeat(
            float(
                execution[
                    "connection_timeout_s"
                ]
            )
        )

        vehicle.wait_position(
            float(
                execution[
                    "position_timeout_s"
                ]
            )
        )

        home_latitude, home_longitude = (
            vehicle.home
        )

        vehicle.arm(
            force=bool(
                execution[
                    "force_arm_in_simulation"
                ]
            ),
            timeout_s=float(
                execution["arm_timeout_s"]
            ),
            resend_interval_s=float(
                execution[
                    "command_resend_interval_s"
                ]
            ),
        )

        vehicle.takeoff(
            altitude_m=float(
                mission[
                    "takeoff_altitude_m"
                ]
            ),
            confirmation_fraction=float(
                execution[
                    "takeoff_confirmation_fraction"
                ]
            ),
            timeout_s=float(
                execution[
                    "takeoff_timeout_s"
                ]
            ),
            resend_interval_s=float(
                execution[
                    "command_resend_interval_s"
                ]
            ),
        )

        vehicle.hold(
            float(
                mission["takeoff_wait_s"]
            )
        )

        for sequence_id, waypoint in enumerate(
            waypoints,
            start=1,
        ):
            zone_name = str(
                waypoint["zone_name"]
            )

            vehicle.current_zone = zone_name

            (
                target_latitude,
                target_longitude,
            ) = offset_lat_lon(
                home_latitude,
                home_longitude,
                float(waypoint["north_m"]),
                float(waypoint["east_m"]),
            )

            print(
                f"[{args.drone_id}] "
                f"waypoint {sequence_id}: "
                f"{zone_name}",
                flush=True,
            )

            arrived = vehicle.goto(
                target_latitude=
                    target_latitude,
                target_longitude=
                    target_longitude,
                target_relative_altitude_m=
                    float(
                        waypoint[
                            "altitude_m"
                        ]
                    ),
                yaw_deg=float(
                    waypoint["yaw_deg"]
                ),
                horizontal_tolerance_m=
                    float(
                        execution[
                            "horizontal_tolerance_m"
                        ]
                    ),
                altitude_tolerance_m=
                    float(
                        execution[
                            "altitude_tolerance_m"
                        ]
                    ),
                timeout_s=float(
                    execution[
                        "arrival_timeout_s"
                    ]
                ),
                resend_interval_s=float(
                    execution[
                        "reposition_resend_interval_s"
                    ]
                ),
                report_interval_s=float(
                    execution[
                        "arrival_report_interval_s"
                    ]
                ),
            )

            summary[
                "completed_waypoints"
            ].append({
                "sequence_id":
                    sequence_id,
                "zone_name":
                    zone_name,
                "arrived_within_tolerance":
                    arrived,
            })

            if not arrived:
                raise TimeoutError(
                    "Arrival timeout at "
                    f"{zone_name}"
                )

            vehicle.hold(
                float(waypoint["hold_s"])
            )

        if bool(execution["auto_land"]):
            vehicle.land(
                altitude_threshold_m=float(
                    execution[
                        "landed_altitude_threshold_m"
                    ]
                ),
                timeout_s=float(
                    execution[
                        "landing_timeout_s"
                    ]
                ),
                resend_interval_s=float(
                    execution[
                        "command_resend_interval_s"
                    ]
                ),
                force_disarm_after_timeout=
                    bool(
                        execution[
                            "force_disarm_after_"
                            "landing_timeout"
                        ]
                    ),
            )

        vehicle.mission_status = "completed"

        summary["status"] = "completed"
        summary["completed_at_utc"] = (
            now_utc()
        )

        print(
            f"[{args.drone_id}] "
            "mission completed",
            flush=True,
        )

        return 0

    except Exception as error:
        summary["status"] = (
            "completed_with_errors"
        )

        summary["completed_at_utc"] = (
            now_utc()
        )

        summary["error"] = str(error)

        print(
            f"[{args.drone_id}] "
            f"ERROR: {error}",
            flush=True,
        )

        try:
            vehicle.land(
                altitude_threshold_m=float(
                    execution[
                        "landed_altitude_threshold_m"
                    ]
                ),
                timeout_s=float(
                    execution[
                        "emergency_landing_timeout_s"
                    ]
                ),
                resend_interval_s=float(
                    execution[
                        "command_resend_interval_s"
                    ]
                ),
                force_disarm_after_timeout=True,
            )

        except Exception as landing_error:
            summary["landing_error"] = (
                str(landing_error)
            )

        return 1

    finally:
        vehicle.close()

        summary_path.write_text(
            json.dumps(
                summary,
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            f"[{args.drone_id}] "
            f"summary: {summary_path}",
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(main())
