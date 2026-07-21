#!/usr/bin/env python3
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import yaml


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"
BACKUP_DIR = PROJECT_ROOT / "backups" / "point21_mavsdk"

SERVER_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "mavsdk"
    / "v1_external_mavsdk_servers.yaml"
)

MANAGER = (
    PROJECT_ROOT
    / "swarm"
    / "mavsdk"
    / "external_server_manager.py"
)

WRAPPER = (
    PROJECT_ROOT
    / "simulation"
    / "scripts"
    / "manage_v1_mavsdk_servers.sh"
)

CONNECTION_TEST = (
    PROJECT_ROOT
    / "swarm"
    / "safety"
    / "test_swarm_mavsdk_connections.py"
)

MISSION_FILES = [
    PROJECT_ROOT
    / "configs"
    / "missions"
    / "swarm"
    / "drone_1_mission.yaml",
    PROJECT_ROOT
    / "configs"
    / "missions"
    / "swarm"
    / "drone_1_obstacle_validation.yaml",
    PROJECT_ROOT
    / "configs"
    / "missions"
    / "swarm"
    / "drone_2_mission.yaml",
    PROJECT_ROOT
    / "configs"
    / "missions"
    / "swarm"
    / "drone_3_mission.yaml",
]

SAFETY_CONFIGS = [
    PROJECT_ROOT
    / "configs"
    / "safety"
    / "v1_swarm_mavsdk_safety_controller.yaml",
    PROJECT_ROOT
    / "configs"
    / "safety"
    / "v1_swarm_mavsdk_safety_dry_run.yaml",
    PROJECT_ROOT
    / "configs"
    / "safety"
    / "v1_swarm_mavsdk_safety_live.yaml",
]


SERVER_CONFIG_TEXT = """\
servers:
  mavsdk_server_binary: auto
  bind_host: 127.0.0.1
  startup_timeout_s: 12.0
  shutdown_timeout_s: 5.0
  health_check_timeout_s: 2.0
  px4_connection_timeout_s: 40.0
  pid_dir: outputs/swarm/v1_three_drone_swarm/server_pids
  log_dir: outputs/swarm/v1_three_drone_swarm/server_logs
  state_file: outputs/swarm/v1_three_drone_swarm/server_pids/server_state.json

drones:
  - drone_id: drone_1
    grpc_port: 50101
    mavlink_endpoint: udpin://0.0.0.0:14541
    server_system_id: 245
    server_component_id: 190

  - drone_id: drone_2
    grpc_port: 50102
    mavlink_endpoint: udpin://0.0.0.0:14542
    server_system_id: 246
    server_component_id: 190

  - drone_id: drone_3
    grpc_port: 50103
    mavlink_endpoint: udpin://0.0.0.0:14543
    server_system_id: 247
    server_component_id: 190
"""


MANAGER_TEXT = r"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text())

    if not isinstance(config, dict):
        raise RuntimeError(
            "Server configuration must be a mapping"
        )

    servers = config.get("servers")
    drones = config.get("drones")

    if not isinstance(servers, dict):
        raise RuntimeError(
            "Missing servers configuration"
        )

    if not isinstance(drones, list) or not drones:
        raise RuntimeError(
            "At least one drone server is required"
        )

    drone_ids = [
        str(item["drone_id"])
        for item in drones
    ]
    grpc_ports = [
        int(item["grpc_port"])
        for item in drones
    ]
    endpoints = [
        str(item["mavlink_endpoint"])
        for item in drones
    ]

    if len(drone_ids) != len(set(drone_ids)):
        raise RuntimeError(
            "Duplicate drone_id values are not allowed"
        )

    if len(grpc_ports) != len(set(grpc_ports)):
        raise RuntimeError(
            "Duplicate gRPC ports are not allowed"
        )

    if len(endpoints) != len(set(endpoints)):
        raise RuntimeError(
            "Duplicate MAVLink endpoints are not allowed"
        )

    return config


def discover_server_binary(
    configured: str,
) -> Path:
    if configured != "auto":
        path = Path(configured).expanduser()

        if not path.is_file():
            raise RuntimeError(
                "Configured mavsdk_server binary "
                f"not found: {path}"
            )

        return path

    import mavsdk

    path = (
        Path(mavsdk.__file__).parent
        / "bin"
        / "mavsdk_server"
    )

    if not path.is_file():
        raise RuntimeError(
            f"Unable to find mavsdk_server at {path}"
        )

    return path


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def tcp_port_open(
    host: str,
    port: int,
    timeout_s: float,
) -> bool:
    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout_s,
        ):
            return True
    except OSError:
        return False


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None

    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def write_state(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        json.dumps(
            {
                "updated_at_epoch_s": time.time(),
                "servers": records,
            },
            indent=2,
        )
        + "\n"
    )


class ServerManager:
    def __init__(
        self,
        project_root: Path,
        config_path: Path,
    ) -> None:
        self.project_root = project_root
        self.config_path = config_path
        self.config = load_config(config_path)

        self.server_settings = (
            self.config["servers"]
        )
        self.drones = self.config["drones"]

        self.host = str(
            self.server_settings.get(
                "bind_host",
                "127.0.0.1",
            )
        )
        self.startup_timeout_s = float(
            self.server_settings[
                "startup_timeout_s"
            ]
        )
        self.shutdown_timeout_s = float(
            self.server_settings[
                "shutdown_timeout_s"
            ]
        )
        self.health_timeout_s = float(
            self.server_settings[
                "health_check_timeout_s"
            ]
        )

        self.pid_dir = (
            self.project_root
            / self.server_settings["pid_dir"]
        )
        self.log_dir = (
            self.project_root
            / self.server_settings["log_dir"]
        )
        self.state_file = (
            self.project_root
            / self.server_settings["state_file"]
        )

        self.binary = discover_server_binary(
            str(
                self.server_settings.get(
                    "mavsdk_server_binary",
                    "auto",
                )
            )
        )

        self.pid_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.log_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def selected(
        self,
        drone_id: str | None,
    ) -> list[dict[str, Any]]:
        if drone_id is None:
            return self.drones

        matches = [
            item
            for item in self.drones
            if str(item["drone_id"]) == drone_id
        ]

        if not matches:
            raise RuntimeError(
                f"Unknown drone_id: {drone_id}"
            )

        return matches

    def pid_path(
        self,
        drone_id: str,
    ) -> Path:
        return (
            self.pid_dir
            / f"{drone_id}.pid"
        )

    def log_path(
        self,
        drone_id: str,
    ) -> Path:
        return (
            self.log_dir
            / f"external_mavsdk_{drone_id}.log"
        )

    def status_record(
        self,
        drone: dict[str, Any],
    ) -> dict[str, Any]:
        drone_id = str(drone["drone_id"])
        grpc_port = int(drone["grpc_port"])
        pid = read_pid(
            self.pid_path(drone_id)
        )
        alive = bool(
            pid and process_alive(pid)
        )
        port_open = tcp_port_open(
            self.host,
            grpc_port,
            self.health_timeout_s,
        )

        return {
            "drone_id": drone_id,
            "pid": pid,
            "process_alive": alive,
            "grpc_port": grpc_port,
            "grpc_reachable": port_open,
            "mavlink_endpoint": str(
                drone["mavlink_endpoint"]
            ),
            "healthy": alive and port_open,
            "log_path": str(
                self.log_path(drone_id).relative_to(
                    self.project_root
                )
            ),
        }

    def status(
        self,
        drone_id: str | None,
    ) -> int:
        records = [
            self.status_record(drone)
            for drone in self.selected(drone_id)
        ]

        write_state(
            self.state_file,
            records,
        )

        healthy_count = 0

        for record in records:
            marker = (
                "HEALTHY"
                if record["healthy"]
                else "NOT_READY"
            )

            print(
                f"{record['drone_id']}: {marker} | "
                f"pid={record['pid']} | "
                f"process={record['process_alive']} | "
                f"grpc={record['grpc_port']} | "
                f"reachable="
                f"{record['grpc_reachable']} | "
                f"endpoint="
                f"{record['mavlink_endpoint']}"
            )

            if record["healthy"]:
                healthy_count += 1

        print(
            "Healthy MAVSDK servers: "
            f"{healthy_count}/{len(records)}"
        )

        return (
            0
            if healthy_count == len(records)
            else 1
        )

    def start_one(
        self,
        drone: dict[str, Any],
    ) -> None:
        drone_id = str(drone["drone_id"])
        grpc_port = int(drone["grpc_port"])

        pid_path = self.pid_path(drone_id)
        existing_pid = read_pid(pid_path)

        if (
            existing_pid
            and process_alive(existing_pid)
        ):
            print(
                f"{drone_id}: already running "
                f"with PID {existing_pid}"
            )
            return

        if tcp_port_open(
            self.host,
            grpc_port,
            self.health_timeout_s,
        ):
            raise RuntimeError(
                f"{drone_id}: gRPC port "
                f"{grpc_port} is already occupied "
                "by another process"
            )

        command = [
            str(self.binary),
            "-p",
            str(grpc_port),
            "--sysid",
            str(drone["server_system_id"]),
            "--compid",
            str(
                drone["server_component_id"]
            ),
            str(drone["mavlink_endpoint"]),
        ]

        log_path = self.log_path(drone_id)

        with log_path.open(
            "ab",
            buffering=0,
        ) as log_file:
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        pid_path.write_text(
            f"{process.pid}\n"
        )

        deadline = (
            time.monotonic()
            + self.startup_timeout_s
        )

        while time.monotonic() < deadline:
            if process.poll() is not None:
                pid_path.unlink(
                    missing_ok=True
                )
                raise RuntimeError(
                    f"{drone_id}: mavsdk_server "
                    f"exited with code "
                    f"{process.returncode}; "
                    f"check {log_path}"
                )

            if tcp_port_open(
                self.host,
                grpc_port,
                self.health_timeout_s,
            ):
                print(
                    f"{drone_id}: started | "
                    f"PID {process.pid} | "
                    f"gRPC {grpc_port}"
                )
                return

            time.sleep(0.25)

        self.stop_one(drone)

        raise TimeoutError(
            f"{drone_id}: gRPC port "
            f"{grpc_port} did not become reachable"
        )

    def start(
        self,
        drone_id: str | None,
    ) -> None:
        started: list[dict[str, Any]] = []

        try:
            for drone in self.selected(drone_id):
                self.start_one(drone)
                started.append(drone)
        except Exception:
            if drone_id is None:
                for drone in reversed(started):
                    self.stop_one(drone)

            raise

        if self.status(drone_id) != 0:
            raise RuntimeError(
                "One or more MAVSDK servers "
                "are not healthy"
            )

    def stop_one(
        self,
        drone: dict[str, Any],
    ) -> None:
        drone_id = str(drone["drone_id"])
        pid_path = self.pid_path(drone_id)
        pid = read_pid(pid_path)

        if pid is None:
            print(
                f"{drone_id}: no managed PID"
            )
            return

        if not process_alive(pid):
            pid_path.unlink(
                missing_ok=True
            )
            print(
                f"{drone_id}: removed stale "
                f"PID {pid}"
            )
            return

        try:
            os.killpg(
                pid,
                signal.SIGTERM,
            )
        except ProcessLookupError:
            pid_path.unlink(
                missing_ok=True
            )
            return

        deadline = (
            time.monotonic()
            + self.shutdown_timeout_s
        )

        while time.monotonic() < deadline:
            if not process_alive(pid):
                pid_path.unlink(
                    missing_ok=True
                )
                print(
                    f"{drone_id}: stopped"
                )
                return

            time.sleep(0.2)

        try:
            os.killpg(
                pid,
                signal.SIGKILL,
            )
        except ProcessLookupError:
            pass

        pid_path.unlink(
            missing_ok=True
        )
        print(
            f"{drone_id}: force-stopped"
        )

    def stop(
        self,
        drone_id: str | None,
    ) -> None:
        for drone in reversed(
            self.selected(drone_id)
        ):
            self.stop_one(drone)

    def restart(
        self,
        drone_id: str | None,
    ) -> None:
        self.stop(drone_id)
        time.sleep(1.0)
        self.start(drone_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Manage external MAVSDK "
            "servers for the swarm"
        )
    )
    parser.add_argument(
        "command",
        choices=[
            "start",
            "stop",
            "restart",
            "status",
            "health",
        ],
    )
    parser.add_argument(
        "--config",
        default=(
            "configs/mavsdk/"
            "v1_external_mavsdk_servers.yaml"
        ),
    )
    parser.add_argument(
        "--drone-id"
    )
    arguments = parser.parse_args()

    project_root = Path.cwd()
    config_path = Path(arguments.config)

    if not config_path.is_absolute():
        config_path = (
            project_root
            / config_path
        )

    manager = ServerManager(
        project_root,
        config_path,
    )

    try:
        if arguments.command == "start":
            manager.start(
                arguments.drone_id
            )
        elif arguments.command == "stop":
            manager.stop(
                arguments.drone_id
            )
        elif arguments.command == "restart":
            manager.restart(
                arguments.drone_id
            )
        else:
            code = manager.status(
                arguments.drone_id
            )
            raise SystemExit(code)
    except Exception as error:
        print(
            "ERROR: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
"""


WRAPPER_TEXT = """\
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"

cd "$PROJECT_ROOT"
source .venv/bin/activate

python \
swarm/mavsdk/external_server_manager.py \
"$@"
"""


CONNECTION_TEST_TEXT = r"""#!/usr/bin/env python3
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
"""


def backup(path: Path) -> None:
    if not path.exists():
        return

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        BACKUP_DIR
        / path.name
    )
    counter = 1

    while destination.exists():
        destination = (
            BACKUP_DIR
            / (
                f"{path.stem}_{counter}"
                f"{path.suffix}"
            )
        )
        counter += 1

    shutil.copy2(
        path,
        destination,
    )


def write_text(
    path: Path,
    content: str,
    executable: bool = False,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        textwrap.dedent(content)
    )

    if executable:
        path.chmod(0o755)


def update_mission_connection(
    path: Path,
) -> None:
    if not path.exists():
        return

    backup(path)

    data = yaml.safe_load(
        path.read_text()
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Invalid mission YAML: {path}"
        )

    connection = data.setdefault(
        "connection",
        {},
    )

    connection[
        "mavsdk_server_address"
    ] = "127.0.0.1"

    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
        )
    )


def update_safety_config(
    path: Path,
) -> None:
    if not path.exists():
        return

    backup(path)

    data = yaml.safe_load(
        path.read_text()
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            f"Invalid safety YAML: {path}"
        )

    for drone in data.get(
        "drones",
        [],
    ):
        drone[
            "mavsdk_server_address"
        ] = "127.0.0.1"

    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
        )
    )


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(
            "Project root not found: "
            f"{PROJECT_ROOT}"
        )

    for path in (
        SERVER_CONFIG,
        MANAGER,
        WRAPPER,
        CONNECTION_TEST,
    ):
        backup(path)

    write_text(
        SERVER_CONFIG,
        SERVER_CONFIG_TEXT,
    )

    write_text(
        MANAGER,
        MANAGER_TEXT,
        executable=True,
    )

    write_text(
        WRAPPER,
        WRAPPER_TEXT,
        executable=True,
    )

    write_text(
        CONNECTION_TEST,
        CONNECTION_TEST_TEXT,
        executable=True,
    )

    for mission_file in MISSION_FILES:
        update_mission_connection(
            mission_file
        )

    for safety_config in SAFETY_CONFIGS:
        update_safety_config(
            safety_config
        )

    print(
        "Point 21 external MAVSDK "
        "server manager installed."
    )
    print(
        "Server config: "
        "configs/mavsdk/"
        "v1_external_mavsdk_servers.yaml"
    )
    print(
        "Manager: "
        "swarm/mavsdk/"
        "external_server_manager.py"
    )
    print(
        "Wrapper: "
        "simulation/scripts/"
        "manage_v1_mavsdk_servers.sh"
    )
    print(
        "Mission and safety configs now use "
        "mavsdk_server_address: 127.0.0.1"
    )


if __name__ == "__main__":
    main()
