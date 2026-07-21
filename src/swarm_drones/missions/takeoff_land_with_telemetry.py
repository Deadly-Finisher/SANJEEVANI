import argparse
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mavsdk import System


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PX4 SITL takeoff, telemetry logging, and landing mission."
    )

    parser.add_argument(
        "--system-address",
        required=True,
        help="MAVSDK connection address, example: udpin://:14540",
    )

    parser.add_argument(
        "--takeoff-altitude",
        required=True,
        type=float,
        help="Target takeoff altitude in meters.",
    )

    parser.add_argument(
        "--hold-seconds",
        required=True,
        type=int,
        help="Number of seconds to hold in air before landing.",
    )

    parser.add_argument(
        "--log-interval-seconds",
        required=True,
        type=float,
        help="Telemetry logging interval in seconds.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where telemetry CSV file will be saved.",
    )

    return parser.parse_args()


async def wait_for_connection(drone: System) -> None:
    print("Waiting for drone connection...")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Drone connected.")
            return


async def wait_for_health(drone: System) -> None:
    print("Waiting for global position and home position...")

    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("Global position and home position are OK.")
            return


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
                f"alt={latest['relative_altitude_m']} m | "
                f"battery={latest['battery_remaining_percent']} | "
                f"mode={latest['flight_mode']} | "
                f"in_air={latest['is_in_air']}"
            )

            await asyncio.sleep(log_interval_seconds)

    for task in telemetry_tasks:
        task.cancel()

    await asyncio.gather(*telemetry_tasks, return_exceptions=True)

    print("Telemetry logging stopped.")


async def run_mission(
    system_address: str,
    takeoff_altitude: float,
    hold_seconds: int,
    log_interval_seconds: float,
    output_dir: str,
) -> None:
    drone = System()

    print(f"Connecting using address: {system_address}")
    await drone.connect(system_address=system_address)

    await wait_for_connection(drone)
    await wait_for_health(drone)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(output_dir) / f"takeoff_land_telemetry_{timestamp}.csv"

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

    asyncio.run(
        run_mission(
            system_address=args.system_address,
            takeoff_altitude=args.takeoff_altitude,
            hold_seconds=args.hold_seconds,
            log_interval_seconds=args.log_interval_seconds,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
