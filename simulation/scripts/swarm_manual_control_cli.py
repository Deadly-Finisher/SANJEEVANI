import asyncio
import math
from dataclasses import dataclass
from mavsdk import System
from mavsdk.offboard import OffboardError, PositionNedYaw


@dataclass
class DroneState:
    name: str
    address: str
    drone: System
    north: float = 0.0
    east: float = 0.0
    down: float = -10.0
    yaw: float = 0.0


DRONES = [
    DroneState("drone_1", "udpin://0.0.0.0:14541", System(port=50051)),
    DroneState("drone_2", "udpin://0.0.0.0:14542", System(port=50052)),
    DroneState("drone_3", "udpin://0.0.0.0:14543", System(port=50053)),
]


async def connect_drone(d: DroneState):
    print(f"[{d.name}] connecting to {d.address}")
    await d.drone.connect(system_address=d.address)

    async for state in d.drone.core.connection_state():
        if state.is_connected:
            print(f"[{d.name}] connected")
            break

    # In multi-drone SITL, global/home health can remain false if QGC is disconnected.
    # For manual local NED control, we skip the blocking health wait.
    print(f"[{d.name}] skipping health wait; using SITL local/offboard control")


async def arm_takeoff_hold(d: DroneState):
    print(f"[{d.name}] preparing offboard setpoint")
    await d.drone.offboard.set_position_ned(PositionNedYaw(d.north, d.east, d.down, d.yaw))
    await asyncio.sleep(0.5)

    print(f"[{d.name}] arming")
    await d.drone.action.arm()
    await asyncio.sleep(1.0)

    print(f"[{d.name}] starting offboard hold at ALT={-d.down:.1f} m")
    for _ in range(10):
        await d.drone.offboard.set_position_ned(PositionNedYaw(d.north, d.east, d.down, d.yaw))
        await asyncio.sleep(0.1)

    try:
        await d.drone.offboard.start()
        print(f"[{d.name}] offboard hold started")
    except OffboardError as e:
        print(f"[{d.name}] offboard start failed: {e._result.result}")
        raise

    await d.drone.offboard.set_position_ned(PositionNedYaw(d.north, d.east, d.down, d.yaw))


async def send_target(d: DroneState):
    await d.drone.offboard.set_position_ned(PositionNedYaw(d.north, d.east, d.down, d.yaw))
    alt = -d.down
    print(f"[{d.name}] target N={d.north:.1f}, E={d.east:.1f}, ALT={alt:.1f}, YAW={d.yaw:.1f}")


async def land_drone(d: DroneState):
    print(f"[{d.name}] landing")
    try:
        await d.drone.offboard.stop()
    except Exception:
        pass
    await d.drone.action.land()


def help_text():
    print("""
Commands:
  select 1 / select 2 / select 3
  n 5       -> move selected drone north 5 m
  s 5       -> move selected drone south 5 m
  e 5       -> move selected drone east 5 m
  w 5       -> move selected drone west 5 m
  up 2      -> move selected drone up 2 m
  down 2    -> move selected drone down 2 m
  yaw 45    -> set selected drone yaw to 45 deg
  status    -> print targets
  land 1    -> land drone 1
  land 2    -> land drone 2
  land 3    -> land drone 3
  land all  -> land all drones
  help
  quit
""")


async def main():
    print("Connecting all drones sequentially...")
    for d in DRONES:
        await connect_drone(d)
        await asyncio.sleep(1)

    print("Taking off all drones sequentially...")
    for d in DRONES:
        await arm_takeoff_hold(d)
        await asyncio.sleep(2)

    selected = 0
    print("All 3 drones are in air and holding position.")
    help_text()

    while True:
        cmd = await asyncio.to_thread(input, f"[selected drone_{selected + 1}]> ")
        parts = cmd.strip().split()

        if not parts:
            continue

        key = parts[0].lower()

        if key == "quit":
            print("Use 'land all' before quitting if drones are still flying.")
            break

        if key == "help":
            help_text()
            continue

        if key == "select" and len(parts) == 2:
            idx = int(parts[1]) - 1
            if idx in [0, 1, 2]:
                selected = idx
                print(f"Selected drone_{selected + 1}")
            continue

        if key == "status":
            for d in DRONES:
                print(f"{d.name}: N={d.north:.1f}, E={d.east:.1f}, ALT={-d.down:.1f}, YAW={d.yaw:.1f}")
            continue

        if key == "land" and len(parts) == 2:
            if parts[1].lower() == "all":
                await asyncio.gather(*(land_drone(d) for d in DRONES))
                print("Landing all drones.")
                break
            else:
                idx = int(parts[1]) - 1
                if idx in [0, 1, 2]:
                    await land_drone(DRONES[idx])
            continue

        d = DRONES[selected]

        try:
            value = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            print("Invalid value.")
            continue

        if key == "n":
            d.north += value
        elif key == "s":
            d.north -= value
        elif key == "e":
            d.east += value
        elif key == "w":
            d.east -= value
        elif key == "up":
            d.down -= value
        elif key == "down":
            d.down += value
        elif key == "yaw":
            d.yaw = value
        else:
            print("Unknown command. Type help.")
            continue

        await send_target(d)


if __name__ == "__main__":
    asyncio.run(main())
