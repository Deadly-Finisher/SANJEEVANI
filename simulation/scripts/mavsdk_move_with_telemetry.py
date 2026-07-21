import asyncio
import csv
from datetime import datetime
from pathlib import Path

import yaml
from mavsdk import System
from mavsdk.offboard import OffboardError, VelocityNedYaw


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


async def get_latest_telemetry(drone: System, state: dict) -> None:
    async def position_task():
        async for position in drone.telemetry.position():
            state["latitude_deg"] = position.latitude_deg
            state["longitude_deg"] = position.longitude_deg
            state["absolute_altitude_m"] = position.absolute_altitude_m
            state["relative_altitude_m"] = position.relative_altitude_m

    async def attitude_task():
        async for attitude in drone.telemetry.attitude_euler():
            state["roll_deg"] = attitude.roll_deg
            state["pitch_deg"] = attitude.pitch_deg
            state["yaw_deg"] = attitude.yaw_deg

    async def velocity_task():
        async for velocity in drone.telemetry.velocity_ned():
            state["velocity_north_m_s"] = velocity.north_m_s
            state["velocity_east_m_s"] = velocity.east_m_s
            state["velocity_down_m_s"] = velocity.down_m_s

    await asyncio.gather(
        position_task(),
        attitude_task(),
        velocity_task(),
    )


async def log_telemetry(state: dict, csv_path: Path, sample_interval_s: float) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "timestamp",
        "mission_phase",
        "latitude_deg",
        "longitude_deg",
        "absolute_altitude_m",
        "relative_altitude_m",
        "roll_deg",
        "pitch_deg",
        "yaw_deg",
        "velocity_north_m_s",
        "velocity_east_m_s",
        "velocity_down_m_s",
    ]

    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        while not state.get("stop_logging", False):
            row = {"timestamp": datetime.now().isoformat()}

            for key in fieldnames:
                if key != "timestamp":
                    row[key] = state.get(key, "")

            writer.writerow(row)
            csvfile.flush()

            await asyncio.sleep(sample_interval_s)


async def main() -> None:
    config = load_config("configs/telemetry/mavsdk_mission_logger.yaml")

    system_address = config["connection"]["system_address"]

    mission_config = config["mission"]
    logging_config = config["logging"]

    csv_path = Path(logging_config["telemetry_csv_path"])
    sample_interval_s = float(logging_config["sample_interval_s"])

    state = {
        "mission_phase": "initializing",
        "stop_logging": False,
    }

    drone = System()
    await drone.connect(system_address=system_address)

    print("Waiting for drone connection...")
    async for connection_state in drone.core.connection_state():
        if connection_state.is_connected:
            print("Drone connected.")
            break

    print("Waiting for position estimate...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("Position estimate OK.")
            break

    telemetry_reader_task = asyncio.create_task(get_latest_telemetry(drone, state))
    telemetry_logger_task = asyncio.create_task(
        log_telemetry(state, csv_path, sample_interval_s)
    )

    try:
        state["mission_phase"] = "arming"
        print("Arming...")
        await drone.action.arm()

        state["mission_phase"] = "takeoff"
        print("Taking off...")
        await drone.action.set_takeoff_altitude(float(mission_config["takeoff_altitude_m"]))
        await drone.action.takeoff()
        await asyncio.sleep(float(mission_config["takeoff_wait_s"]))

        print("Starting offboard mode...")
        await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))

        try:
            await drone.offboard.start()
        except OffboardError as error:
            print(f"Offboard start failed: {error._result.result}")
            await drone.action.land()
            return

        state["mission_phase"] = "moving_forward"
        print("Moving forward...")
        await drone.offboard.set_velocity_ned(
            VelocityNedYaw(
                float(mission_config["forward_velocity_m_s"]),
                0.0,
                0.0,
                0.0,
            )
        )
        await asyncio.sleep(float(mission_config["forward_duration_s"]))

        state["mission_phase"] = "moving_right"
        print("Moving right...")
        await drone.offboard.set_velocity_ned(
            VelocityNedYaw(
                0.0,
                float(mission_config["right_velocity_m_s"]),
                0.0,
                float(mission_config["yaw_deg"]),
            )
        )
        await asyncio.sleep(float(mission_config["right_duration_s"]))

        state["mission_phase"] = "hovering"
        print("Hovering...")
        await drone.offboard.set_velocity_ned(
            VelocityNedYaw(0.0, 0.0, 0.0, float(mission_config["yaw_deg"]))
        )
        await asyncio.sleep(float(mission_config["hover_duration_s"]))

        state["mission_phase"] = "landing"
        print("Stopping offboard and landing...")
        await drone.offboard.stop()
        await drone.action.land()

        await asyncio.sleep(5)

    finally:
        state["stop_logging"] = True

        telemetry_reader_task.cancel()
        await telemetry_logger_task

        print(f"Telemetry saved to: {csv_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())