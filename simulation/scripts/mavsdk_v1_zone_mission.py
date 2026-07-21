import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw


CONFIG_PATH = Path("configs/missions/v1_single_drone_zone_mission.yaml")


def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r") as file:
        return yaml.safe_load(file)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def wait_for_connection(drone: System) -> None:
    print("Waiting for drone connection...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Drone connected.")
            return


async def wait_for_position_estimate(drone: System) -> None:
    print("Waiting for position estimate...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("Position estimate OK.")
            return


async def telemetry_logger(
    drone: System,
    csv_path: Path,
    sample_interval_s: float,
    mission_state: Dict[str, str],
    stop_event: asyncio.Event,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "timestamp_utc",
        "mission_name",
        "mission_phase",
        "zone_name",
        "north_m",
        "east_m",
        "down_m",
        "velocity_north_m_s",
        "velocity_east_m_s",
        "velocity_down_m_s",
    ]

    with open(csv_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        while not stop_event.is_set():
            try:
                position_velocity = await drone.telemetry.position_velocity_ned().__anext__()
                position = position_velocity.position
                velocity = position_velocity.velocity

                writer.writerow(
                    {
                        "timestamp_utc": utc_now(),
                        "mission_name": mission_state.get("mission_name", ""),
                        "mission_phase": mission_state.get("mission_phase", ""),
                        "zone_name": mission_state.get("zone_name", ""),
                        "north_m": position.north_m,
                        "east_m": position.east_m,
                        "down_m": position.down_m,
                        "velocity_north_m_s": velocity.north_m_s,
                        "velocity_east_m_s": velocity.east_m_s,
                        "velocity_down_m_s": velocity.down_m_s,
                    }
                )
                file.flush()

            except Exception as exc:
                print(f"Telemetry logging warning: {exc}")

            await asyncio.sleep(sample_interval_s)


async def send_position_setpoint_repeated(
    drone: System,
    north_m: float,
    east_m: float,
    altitude_m: float,
    yaw_deg: float,
    duration_s: float,
    interval_s: float,
) -> None:
    down_m = -abs(altitude_m)
    steps = max(1, int(duration_s / interval_s))

    for _ in range(steps):
        await drone.offboard.set_position_ned(
            PositionNedYaw(
                north_m=north_m,
                east_m=east_m,
                down_m=down_m,
                yaw_deg=yaw_deg,
            )
        )
        await asyncio.sleep(interval_s)


async def main() -> None:
    config = load_config()

    system_address = config["connection"]["system_address"]
    mission_name = config["mission"]["mission_name"]
    takeoff_altitude_m = float(config["mission"]["takeoff_altitude_m"])
    takeoff_wait_s = float(config["mission"]["takeoff_wait_s"])
    waypoint_command_interval_s = float(config["mission"]["waypoint_command_interval_s"])
    landing_wait_s = float(config["mission"]["landing_wait_s"])

    telemetry_csv_path = Path(config["logging"]["telemetry_csv_path"])
    sample_interval_s = float(config["logging"]["sample_interval_s"])
    waypoints = config["waypoints"]

    drone = System()
    await drone.connect(system_address=system_address)

    await wait_for_connection(drone)
    await wait_for_position_estimate(drone)

    mission_state = {
        "mission_name": mission_name,
        "mission_phase": "preflight",
        "zone_name": "none",
    }

    stop_event = asyncio.Event()
    telemetry_task = asyncio.create_task(
        telemetry_logger(
            drone=drone,
            csv_path=telemetry_csv_path,
            sample_interval_s=sample_interval_s,
            mission_state=mission_state,
            stop_event=stop_event,
        )
    )

    try:
        print("Setting takeoff altitude...")
        await drone.action.set_takeoff_altitude(takeoff_altitude_m)

        mission_state["mission_phase"] = "arming"
        print("Arming...")
        await drone.action.arm()

        mission_state["mission_phase"] = "takeoff"
        print("Taking off...")
        await drone.action.takeoff()
        await asyncio.sleep(takeoff_wait_s)

        mission_state["mission_phase"] = "offboard_prepare"
        print("Preparing Offboard mode...")

        for _ in range(20):
            await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
            await asyncio.sleep(0.1)

        print("Starting Offboard mode...")
        await drone.offboard.start()

        for waypoint in waypoints:
            zone_name = waypoint["zone_name"]
            north_m = float(waypoint["north_m"])
            east_m = float(waypoint["east_m"])
            altitude_m = float(waypoint["altitude_m"])
            yaw_deg = float(waypoint["yaw_deg"])
            hold_s = float(waypoint["hold_s"])

            mission_state["mission_phase"] = "zone_navigation"
            mission_state["zone_name"] = zone_name

            print(
                f"Going to {zone_name}: "
                f"N={north_m:.1f}, E={east_m:.1f}, Alt={altitude_m:.1f}, Yaw={yaw_deg:.1f}"
            )

            travel_time_s = max(12.0, hold_s)

            await send_position_setpoint_repeated(
                drone=drone,
                north_m=north_m,
                east_m=east_m,
                altitude_m=altitude_m,
                yaw_deg=yaw_deg,
                duration_s=travel_time_s,
                interval_s=waypoint_command_interval_s,
            )

            mission_state["mission_phase"] = "zone_hold"
            print(f"Holding at {zone_name} for {hold_s:.1f}s")

            await send_position_setpoint_repeated(
                drone=drone,
                north_m=north_m,
                east_m=east_m,
                altitude_m=altitude_m,
                yaw_deg=yaw_deg,
                duration_s=hold_s,
                interval_s=waypoint_command_interval_s,
            )

        mission_state["mission_phase"] = "landing"
        mission_state["zone_name"] = "return_landing_zone"

        print("Stopping Offboard mode...")
        try:
            await drone.offboard.stop()
        except OffboardError as exc:
            print(f"Offboard stop warning: {exc}")

        print("Landing...")
        await drone.action.land()
        await asyncio.sleep(landing_wait_s)

        mission_state["mission_phase"] = "completed"
        print("V1 zone mission completed.")
        print("Telemetry saved to:", telemetry_csv_path.resolve())

    finally:
        stop_event.set()
        await telemetry_task


if __name__ == "__main__":
    asyncio.run(main())
