import argparse
import asyncio

from mavsdk import System


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PX4 SITL takeoff and landing mission using MAVSDK."
    )

    parser.add_argument(
        "--system-address",
        required=True,
        help="MAVSDK connection address, example: udp://:14540",
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


async def run_mission(
    system_address: str,
    takeoff_altitude: float,
    hold_seconds: int,
) -> None:
    drone = System()

    print(f"Connecting using address: {system_address}")
    await drone.connect(system_address=system_address)

    await wait_for_connection(drone)
    await wait_for_health(drone)

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

    print("Mission command completed. Drone is landing.")


def main() -> None:
    args = parse_arguments()

    asyncio.run(
        run_mission(
            system_address=args.system_address,
            takeoff_altitude=args.takeoff_altitude,
            hold_seconds=args.hold_seconds,
        )
    )


if __name__ == "__main__":
    main()

