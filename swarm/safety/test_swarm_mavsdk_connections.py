#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import yaml
from mavsdk import System


async def wait_for_connection(
    drone: System,
) -> None:
    async for state in (
        drone.core.connection_state()
    ):
        if state.is_connected:
            return


async def connect_drone(
    config: dict[str, Any],
    host: str,
    connection_timeout_s: float,
) -> bool:
    drone_id = str(
        config["drone_id"]
    )
    grpc_port = int(
        config["grpc_port"]
    )
    endpoint = str(
        config["mavlink_endpoint"]
    )

    print(
        f"{drone_id}: external server "
        f"{host}:{grpc_port} | {endpoint}"
    )

    drone = System(
        mavsdk_server_address=host,
        port=grpc_port,
    )

    await drone.connect()

    try:
        await asyncio.wait_for(
            wait_for_connection(drone),
            timeout=connection_timeout_s,
        )
    except asyncio.TimeoutError:
        print(
            f"{drone_id}: PX4 connection "
            "timed out"
        )
        return False

    print(
        f"{drone_id}: external MAVSDK "
        "and PX4 connected"
    )
    return True


async def run_test(
    config_path: Path,
) -> None:
    config = yaml.safe_load(
        config_path.read_text()
    )

    server_settings = config["servers"]
    drones = config["drones"]

    host = str(
        server_settings.get(
            "bind_host",
            "127.0.0.1",
        )
    )

    connection_timeout_s = float(
        server_settings.get(
            "px4_connection_timeout_s",
            40.0,
        )
    )

    results = await asyncio.gather(
        *(
            connect_drone(
                drone,
                host,
                connection_timeout_s,
            )
            for drone in drones
        ),
        return_exceptions=True,
    )

    successful = 0

    for drone, result in zip(
        drones,
        results,
    ):
        drone_id = drone["drone_id"]

        if isinstance(result, Exception):
            print(
                f"{drone_id}: ERROR: "
                f"{type(result).__name__}: "
                f"{result}"
            )
        elif result:
            successful += 1

    print()
    print(
        "Connected drones: "
        f"{successful}/{len(drones)}"
    )

    if successful != len(drones):
        raise SystemExit(1)

    print(
        "Three-drone external MAVSDK "
        "connection test passed."
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default=(
            "configs/mavsdk/"
            "v1_external_mavsdk_servers.yaml"
        ),
    )

    arguments = parser.parse_args()

    asyncio.run(
        run_test(
            Path(arguments.config)
        )
    )


if __name__ == "__main__":
    main()
