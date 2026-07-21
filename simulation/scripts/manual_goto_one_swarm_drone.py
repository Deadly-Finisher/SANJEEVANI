import argparse
import asyncio
import math
from mavsdk import System


EARTH_RADIUS_M = 6378137.0


def offset_lat_lon(lat_deg, lon_deg, north_m, east_m):
    lat_rad = math.radians(lat_deg)
    d_lat = north_m / EARTH_RADIUS_M
    d_lon = east_m / (EARTH_RADIUS_M * math.cos(lat_rad))

    new_lat = lat_deg + math.degrees(d_lat)
    new_lon = lon_deg + math.degrees(d_lon)

    return new_lat, new_lon


async def wait_connected(drone, name):
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"[{name}] connected")
            return


async def wait_global_position(drone, name):
    print(f"[{name}] waiting for global position")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok:
            print(f"[{name}] global position ready")
            return


async def get_position(drone):
    async for pos in drone.telemetry.position():
        return pos


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
    await wait_global_position(drone, name)

    start_pos = await get_position(drone)

    home_lat = start_pos.latitude_deg
    home_lon = start_pos.longitude_deg
    home_abs_alt = start_pos.absolute_altitude_m

    north = 0.0
    east = 0.0
    rel_alt = 10.0
    yaw = 0.0

    print(f"[{name}] home lat/lon/alt: {home_lat}, {home_lon}, {home_abs_alt}")

    print(f"[{name}] setting takeoff altitude")
    await drone.action.set_takeoff_altitude(rel_alt)

    print(f"[{name}] arming")
    await drone.action.arm()

    print(f"[{name}] takeoff")
    await drone.action.takeoff()

    await asyncio.sleep(10)

    print(f"[{name}] ready.")
    print("Commands:")
    print("  n 5     -> move north 5 m")
    print("  s 5     -> move south 5 m")
    print("  e 5     -> move east 5 m")
    print("  w 5     -> move west 5 m")
    print("  up 2    -> climb 2 m")
    print("  down 2  -> descend 2 m")
    print("  yaw 90  -> set yaw")
    print("  land")
    print("  quit")

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
            rel_alt += value
        elif key == "down":
            rel_alt -= value
            if rel_alt < 3.0:
                rel_alt = 3.0
        elif key == "yaw":
            yaw = value
        else:
            print("Unknown command")
            continue

        target_lat, target_lon = offset_lat_lon(home_lat, home_lon, north, east)
        target_abs_alt = home_abs_alt + rel_alt

        print(f"[{name}] goto N={north:.1f}, E={east:.1f}, ALT={rel_alt:.1f}, YAW={yaw:.1f}")
        await drone.action.goto_location(target_lat, target_lon, target_abs_alt, yaw)


if __name__ == "__main__":
    asyncio.run(main())
