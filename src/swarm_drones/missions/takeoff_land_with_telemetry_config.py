import argparse
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from mavsdk import System


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PX4 SITL takeoff, telemetry logging, and landing mission using YAML config."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML mission config file.",
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
    required_sections = ["connection", "mission", "telemetry", "safety"]

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")

    if "system_address" not in config["connection"]:
        raise ValueError("Missing connection.system_address")

    if "takeoff_altitude_m" not in config["mission"]:
        raise ValueError("Missing mission.takeoff_altitude_m")

    if "hold_seconds" not in config["mission"]:
        raise ValueError("Missing mission.hold_seconds")

    if "log_interval_seconds" not in config["telemetry"]:
        raise ValueError("Missing telemetry.log_interval_seconds")

    if "output_dir" not in config["telemetry"]:
        raise ValueError("Missing telemetry.output_dir")


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

        if require_global_position and not global_ok:
            print("Waiting for global position...")

        if require_home_position and not home_ok:
            print("Waiting for home position...")

        global_condition = global_ok if require_global_position else True
        home_condition = home_ok if require_home_position else True

        if global_condition and home_condition:
            print("Required health checks passed.")
            return

        await asyncio.sleep(1)


async def wait_until_landed(drone: System) -> None:
    print("Waiting until drone lands...")

    async for is_in_air in drone.telemetry.in_air():
        if not is_in_air:
            print("Drone landed.")
            return


async def telemetry_logger(
    drone: System,
    output_file: Path,
    log_interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    latest: dict[str, Any] = {
        "latitude_deg": None,
        "longitude_deg": None,
        "absolute_altitude_m": None,
        "relative_altitude_m": None,
        "mission_altitude_m": None,
        "battery_remaining_percent": None,
        "battery_voltage_v": None,
        "flight_mode": None,
        "is_in_air": None,
    }

    initial_absolute_altitude: float | None = None

    async def update_position() -> None:
        nonlocal initial_absolute_altitude

        async for position in drone.telemetry.position():
            if initial_absolute_altitude is None:
                initial_absolute_altitude = position.absolute_altitude_m

            latest["latitude_deg"] = position.latitude_deg
            latest["longitude_deg"] = position.longitude_deg
            latest["absolute_altitude_m"] = position.absolute_altitude_m
            latest["relative_altitude_m"] = position.relative_altitude_m
            latest["mission_altitude_m"] = (
                position.absolute_altitude_m - initial_absolute_altitude
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
                f"abs_alt={latest['absolute_altitude_m']} m | "
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
    takeoff_altitude = float(config["mission"]["takeoff_altitude_m"])
    hold_seconds = int(config["mission"]["hold_seconds"])
    log_interval_seconds = float(config["telemetry"]["log_interval_seconds"])
    output_dir = config["telemetry"]["output_dir"]

    require_global_position = bool(config["safety"]["require_global_position"])
    require_home_position = bool(config["safety"]["require_home_position"])
    allow_autonomous_engagement = bool(config["safety"]["allow_autonomous_engagement"])

    if allow_autonomous_engagement:
        raise ValueError(
            "Unsafe config: allow_autonomous_engagement must remain false."
        )

    drone = System()

    print(f"Connecting using address: {system_address}")
    await drone.connect(system_address=system_address)

    await wait_for_connection(drone)

    await wait_for_health(
        drone=drone,
        require_global_position=require_global_position,
        require_home_position=require_home_position,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(output_dir) / f"yaml_telemetry_{timestamp}.csv"

    stop_event = asyncio.Event()

    logger_task = asyncio.create_task(
        telemetry_logger(
            drone=drone,
            output_file=output_file,
            log_interval_seconds=log_interval_seconds,
            stop_event=stop_event,
        )
    )

    print(f"Setting takeoff altitude to {takeoff_altitude} meters...")
    await drone.action.set_takeoff_altitude(takeoff_altitude)

    print("Arming drone...")
    await drone.action.arm()

    print("Taking off...")
    await drone.action.takeoff()

    print(f"Holding position for {hold_seconds} seconds...")
    await asyncio.sleep(hold_seconds)

    print("Landing...")
    await drone.action.land()

    await wait_until_landed(drone)

    stop_event.set()
    await logger_task

    print("Mission completed successfully.")
    print(f"Telemetry CSV saved at: {output_file}")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    validate_config(config)

    asyncio.run(run_mission(config))


if __name__ == "__main__":
    main()