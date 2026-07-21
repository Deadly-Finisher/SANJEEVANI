import argparse
import asyncio
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw


async def wait_connected(drone, name):
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"[{name}] connected")
            return


async def wait_health_or_continue(drone, name, timeout_s=25):
    print(f"[{name}] waiting briefly for position/home")
    start = asyncio.get_event_loop().time()

    async for health in drone.telemetry.health():
        if health.is_global_position_ok or health.is_local_position_ok:
            print(f"[{name}] position ready")
            return

        if asyncio.get_event_loop().time() - start > timeout_s:
            print(f"[{name}] position wait timed out; continuing")
            return


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--mavsdk-port", type=int, required=True)
    parser.add_argument("--grpc-port", type=int, required=True)
    args = parser.parse_args()

    name = args.name
    system_address = f"udpin://0.0.0.0:{args.mavsdk_port}"

    drone = System(port=args.grpc_port)

    print(f"[{name}] connecting to {system_address}")
    await drone.connect(system_address=system_address)
    await wait_connected(drone, name)
    await wait_health_or_continue(drone, name)

    north = 0.0
    east = 0.0
    down = -10.0
    yaw = 0.0

    print(f"[{name}] setting takeoff altitude")
    await drone.action.set_takeoff_altitude(10.0)

    print(f"[{name}] arming")
    await drone.action.arm()

    print(f"[{name}] takeoff")
    await drone.action.takeoff()
    await asyncio.sleep(8)

    print(f"[{name}] starting offboard hold")
    for _ in range(20):
        await drone.offboard.set_position_ned(PositionNedYaw(north, east, down, yaw))
        await asyncio.sleep(0.1)

    try:
        await drone.offboard.start()
        print(f"[{name}] offboard started")
    except OffboardError as error:
        print(f"[{name}] offboard failed: {error._result.result}")
        return

    print(f"[{name}] ready. Commands: n 5, s 5, e 5, w 5, up 2, down 2, yaw 90, land, quit")

    while True:
        cmd = await asyncio.to_thread(input, f"[{name}]> ")
        parts = cmd.strip().split()

        if not parts:
            continue

        key = parts[0].lower()

        if key == "quit":
            break

        if key == "land":
            print(f"[{name}] landing")
            try:
                await drone.offboard.stop()
            except Exception:
                pass
            await drone.action.land()
            break

        if len(parts) < 2:
            print("Give value. Example: n 5")
            continue

        try:
            value = float(parts[1])
        except ValueError:
            print("Invalid number")
            continue

        if key == "n":
            north += value
        elif key == "s":
            north -= value
        elif key == "e":
            east += value
        elif key == "w":
            east -= value
        elif key == "up":
            down -= value
        elif key == "down":
            down += value
        elif key == "yaw":
            yaw = value
        else:
            print("Unknown command")
            continue

        await drone.offboard.set_position_ned(PositionNedYaw(north, east, down, yaw))
        print(f"[{name}] target N={north:.1f}, E={east:.1f}, ALT={-down:.1f}, YAW={yaw:.1f}")


if __name__ == "__main__":
    asyncio.run(main())
