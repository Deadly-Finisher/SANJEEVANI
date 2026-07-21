import argparse
import asyncio
import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from mavsdk import System


EARTH_RADIUS_M = 6_378_137.0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PX4 SITL waypoint navigation mission using YAML config."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML waypoint mission config file.",
    )

    return parser.parse_args()


def load_yaml_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML dictionary.")

    return config


def validate_config(config: dict[str, Any]) -> None:
    required_sections = ["connection", "mission", "waypoint", "telemetry", "safety"]

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")

    if "system_address" not in config["connection"]:
        raise ValueError("Missing connection.system_address")

    if "takeoff_altitude_m" not in config["mission"]:
        raise ValueError("Missing mission.takeoff_altitude_m")

    if "north_m" not in config["waypoint"]:
        raise ValueError("Missing waypoint.north_m")

    if "east_m" not in config["waypoint"]:
        raise ValueError("Missing waypoint.east_m")

    if "altitude_m" not in config["waypoint"]:
        raise ValueError("Missing waypoint.altitude_m")

    if "output_dir" not in config["telemetry"]:
        raise ValueError("Missing telemetry.output_dir")


def calculate_target_gps(
    start_latitude_deg: float,
    start_longitude_deg: float,
    north_m: float,
    east_m: float,
) -> tuple[float, float]:
    start_latitude_rad = math.radians(start_latitude_deg)

    delta_latitude_deg = math.degrees(north_m / EARTH_RADIUS_M)
    delta_longitude_deg = math.degrees(
        east_m / (EARTH_RADIUS_M * math.cos(start_latitude_rad))
    )

    target_latitude_deg = start_latitude_deg + delta_latitude_deg
    target_longitude_deg = start_longitude_deg + delta_longitude_deg

    return target_latitude_deg, target_longitude_deg


def haversine_distance_m(
    latitude_1_deg: float,
    longitude_1_deg: float,
    latitude_2_deg: float,
    longitude_2_deg: float,
) -> float:
    latitude_1_rad = math.radians(latitude_1_deg)
    latitude_2_rad = math.radians(latitude_2_deg)

    delta_latitude_rad = math.radians(latitude_2_deg - latitude_1_deg)
    delta_longitude_rad = math.radians(longitude_2_deg - longitude_1_deg)

    a = (
        math.sin(delta_latitude_rad / 2) ** 2
        + math.cos(latitude_1_rad)
        * math.cos(latitude_2_rad)
        * math.sin(delta_longitude_rad / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


async def wait_for_connection(drone: System) -> None:
    print("Waiting for drone connection...")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Drone connected.")
            return


async def wait_for_health(
    drone: System,
    require_global_position: bool,
    require_home_position: bool,
) -> None:
    print("Checking drone health...")

    async for health in drone.telemetry.health():
        global_ok = health.is_global_position_ok
        home_ok = health.is_home_position_ok

        global_condition = global_ok if require_global_position else True
        home_condition = home_ok if require_home_position else True

        if global_condition and home_condition:
            print("Required health checks passed.")
            return

        print(
            "Waiting for health | "
            f"global_position_ok={global_ok} | "
            f"home_position_ok={home_ok}"
        )

        await asyncio.sleep(1)


async def get_current_position(drone: System) -> Any:
    async for position in drone.telemetry.position():
        return position

    raise RuntimeError("Could not read drone position.")


async def wait_until_landed(drone: System) -> None:
    print("Waiting until drone lands...")

    async for is_in_air in drone.telemetry.in_air():
        if not is_in_air:
            print("Drone landed.")
            return


async def wait_until_waypoint_reached(
    drone: System,
    target_latitude_deg: float,
    target_longitude_deg: float,
    acceptance_radius_m: float,
    timeout_seconds: int,
) -> None:
    print("Waiting until waypoint is reached...")

    start_time = asyncio.get_running_loop().time()

    async for position in drone.telemetry.position():
        distance_to_target_m = haversine_distance_m(
            latitude_1_deg=position.latitude_deg,
            longitude_1_deg=position.longitude_deg,
            latitude_2_deg=target_latitude_deg,
            longitude_2_deg=target_longitude_deg,
        )

        print(f"Distance to waypoint: {distance_to_target_m:.2f} m")

        if distance_to_target_m <= acceptance_radius_m:
            print("Waypoint reached.")
            return

        elapsed_seconds = asyncio.get_running_loop().time() - start_time

        if elapsed_seconds > timeout_seconds:
            print("Waypoint timeout reached. Continuing mission safely.")
            return

        await asyncio.sleep(1)


async def telemetry_logger(
    drone: System,
    output_file: Path,
    log_interval_seconds: float,
    stop_event: asyncio.Event,
    base_absolute_altitude_m: float,
    target_latitude_deg: float,
    target_longitude_deg: float,
) -> None:
    latest: dict[str, Any] = {
        "latitude_deg": None,
        "longitude_deg": None,
        "absolute_altitude_m": None,
        "relative_altitude_m": None,
        "mission_altitude_m": None,
        "distance_to_waypoint_m": None,
        "battery_remaining_percent": None,
        "battery_voltage_v": None,
        "flight_mode": None,
        "is_in_air": None,
    }

    async def update_position() -> None:
        async for position in drone.telemetry.position():
            latest["latitude_deg"] = position.latitude_deg
            latest["longitude_deg"] = position.longitude_deg
            latest["absolute_altitude_m"] = position.absolute_altitude_m
            latest["relative_altitude_m"] = position.relative_altitude_m
            latest["mission_altitude_m"] = (
                position.absolute_altitude_m - base_absolute_altitude_m
            )
            latest["distance_to_waypoint_m"] = haversine_distance_m(
                latitude_1_deg=position.latitude_deg,
                longitude_1_deg=position.longitude_deg,
                latitude_2_deg=target_latitude_deg,
                longitude_2_deg=target_longitude_deg,
            )

    async def update_battery() -> None:
        async for battery in drone.telemetry.battery():
            latest["battery_remaining_percent"] = battery.remaining_percent
            latest["battery_voltage_v"] = getattr(battery, "voltage_v", None)

    async def update_flight_mode() -> None:
        async for flight_mode in drone.telemetry.flight_mode():
            latest["flight_mode"] = str(flight_mode)

    async def update_in_air() -> None:
        async for is_in_air in drone.telemetry.in_air():
            latest["is_in_air"] = is_in_air

    telemetry_tasks = [
        asyncio.create_task(update_position()),
        asyncio.create_task(update_battery()),
        asyncio.create_task(update_flight_mode()),
        asyncio.create_task(update_in_air()),
    ]

    fieldnames = [
        "timestamp_utc",
        "latitude_deg",
        "longitude_deg",
        "absolute_altitude_m",
        "relative_altitude_m",
        "mission_altitude_m",
        "distance_to_waypoint_m",
        "battery_remaining_percent",
        "battery_voltage_v",
        "flight_mode",
        "is_in_air",
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Saving telemetry to: {output_file}")

    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        while not stop_event.is_set():
            row = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **latest,
            }

            writer.writerow(row)
            csv_file.flush()

            print(
                "Telemetry | "
                f"mission_alt={latest['mission_altitude_m']} m | "
                f"distance={latest['distance_to_waypoint_m']} m | "
                f"battery={latest['battery_remaining_percent']} | "
                f"mode={latest['flight_mode']} | "
                f"in_air={latest['is_in_air']}"
            )

            await asyncio.sleep(log_interval_seconds)

    for task in telemetry_tasks:
        task.cancel()

    await asyncio.gather(*telemetry_tasks, return_exceptions=True)

    print("Telemetry logging stopped.")


async def run_mission(config: dict[str, Any]) -> None:
    system_address = config["connection"]["system_address"]

    takeoff_altitude_m = float(config["mission"]["takeoff_altitude_m"])
    waypoint_hold_seconds = int(config["mission"]["waypoint_hold_seconds"])
    landing_hold_seconds = int(config["mission"]["landing_hold_seconds"])

    north_m = float(config["waypoint"]["north_m"])
    east_m = float(config["waypoint"]["east_m"])
    waypoint_altitude_m = float(config["waypoint"]["altitude_m"])
    yaw_deg = float(config["waypoint"]["yaw_deg"])
    acceptance_radius_m = float(config["waypoint"]["acceptance_radius_m"])
    goto_timeout_seconds = int(config["waypoint"]["goto_timeout_seconds"])

    log_interval_seconds = float(config["telemetry"]["log_interval_seconds"])
    output_dir = config["telemetry"]["output_dir"]

    require_global_position = bool(config["safety"]["require_global_position"])
    require_home_position = bool(config["safety"]["require_home_position"])
    allow_autonomous_engagement = bool(config["safety"]["allow_autonomous_engagement"])

    if allow_autonomous_engagement:
        raise ValueError("Unsafe config: allow_autonomous_engagement must remain false.")

    drone = System()

    print(f"Connecting using address: {system_address}")
    await drone.connect(system_address=system_address)

    await wait_for_connection(drone)

    await wait_for_health(
        drone=drone,
        require_global_position=require_global_position,
        require_home_position=require_home_position,
    )

    start_position = await get_current_position(drone)

    base_latitude_deg = start_position.latitude_deg
    base_longitude_deg = start_position.longitude_deg
    base_absolute_altitude_m = start_position.absolute_altitude_m

    target_latitude_deg, target_longitude_deg = calculate_target_gps(
        start_latitude_deg=base_latitude_deg,
        start_longitude_deg=base_longitude_deg,
        north_m=north_m,
        east_m=east_m,
    )

    target_absolute_altitude_m = base_absolute_altitude_m + waypoint_altitude_m

    print("Mission start position:")
    print(f"  latitude: {base_latitude_deg}")
    print(f"  longitude: {base_longitude_deg}")
    print(f"  absolute altitude: {base_absolute_altitude_m}")

    print("Calculated target waypoint:")
    print(f"  target latitude: {target_latitude_deg}")
    print(f"  target longitude: {target_longitude_deg}")
    print(f"  target absolute altitude: {target_absolute_altitude_m}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(output_dir) / f"waypoint_navigation_{timestamp}.csv"

    stop_event = asyncio.Event()

    logger_task = asyncio.create_task(
        telemetry_logger(
            drone=drone,
            output_file=output_file,
            log_interval_seconds=log_interval_seconds,
            stop_event=stop_event,
            base_absolute_altitude_m=base_absolute_altitude_m,
            target_latitude_deg=target_latitude_deg,
            target_longitude_deg=target_longitude_deg,
        )
    )

    print(f"Setting takeoff altitude to {takeoff_altitude_m} meters...")
    await drone.action.set_takeoff_altitude(takeoff_altitude_m)

    print("Arming drone...")
    await drone.action.arm()

    print("Taking off...")
    await drone.action.takeoff()

    print("Waiting for takeoff climb...")
    await asyncio.sleep(8)

    print("Going to waypoint...")
    await drone.action.goto_location(
        target_latitude_deg,
        target_longitude_deg,
        target_absolute_altitude_m,
        yaw_deg,
    )

    await wait_until_waypoint_reached(
        drone=drone,
        target_latitude_deg=target_latitude_deg,
        target_longitude_deg=target_longitude_deg,
        acceptance_radius_m=acceptance_radius_m,
        timeout_seconds=goto_timeout_seconds,
    )

    print(f"Holding near waypoint for {waypoint_hold_seconds} seconds...")
    await asyncio.sleep(waypoint_hold_seconds)

    print("Landing...")
    await drone.action.land()

    await asyncio.sleep(landing_hold_seconds)

    await wait_until_landed(drone)

    stop_event.set()
    await logger_task

    print("Waypoint mission completed successfully.")
    print(f"Telemetry CSV saved at: {output_file}")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    validate_config(config)

    asyncio.run(run_mission(config))


if __name__ == "__main__":
    main()