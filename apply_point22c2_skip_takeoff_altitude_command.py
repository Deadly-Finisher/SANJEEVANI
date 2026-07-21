#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

import yaml


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"

RUNNER_PATH = (
    PROJECT_ROOT
    / "simulation"
    / "scripts"
    / "run_one_swarm_drone_mission.py"
)

EXECUTION_CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "swarm"
    / "v1_swarm_obstacle_validation_execution.yaml"
)

BACKUP_DIR = (
    PROJECT_ROOT
    / "backups"
    / "point22c2_skip_takeoff_altitude_command"
)


def backup(path: Path) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    destination = BACKUP_DIR / path.name
    counter = 1

    while destination.exists():
        destination = (
            BACKUP_DIR
            / f"{path.stem}_{counter}{path.suffix}"
        )
        counter += 1

    shutil.copy2(path, destination)


def replace_once(
    text: str,
    old: str,
    new: str,
    description: str,
) -> str:
    if new in text:
        return text

    if old not in text:
        raise RuntimeError(
            f"Could not find marker for {description}"
        )

    return text.replace(old, new, 1)


def patch_execution_config() -> None:
    backup(EXECUTION_CONFIG_PATH)

    config = yaml.safe_load(
        EXECUTION_CONFIG_PATH.read_text()
    )

    execution = config.setdefault(
        "execution",
        {},
    )

    execution[
        "set_takeoff_altitude_before_arm"
    ] = False

    EXECUTION_CONFIG_PATH.write_text(
        yaml.safe_dump(
            config,
            sort_keys=False,
        )
    )


def patch_runner() -> None:
    backup(RUNNER_PATH)

    text = RUNNER_PATH.read_text()

    old_block = '''        await execute_with_retry(
            "set takeoff altitude",
            lambda: drone.action.set_takeoff_altitude(
                float(mission["takeoff_altitude_m"])
            ),
            retries,
            retry_delay_s,
            drone_id,
        )

'''

    new_block = '''        set_takeoff_altitude_before_arm = bool(
            execution.get(
                "set_takeoff_altitude_before_arm",
                True,
            )
        )

        summary[
            "set_takeoff_altitude_before_arm"
        ] = set_takeoff_altitude_before_arm

        if set_takeoff_altitude_before_arm:
            await execute_with_retry(
                "set takeoff altitude",
                lambda: drone.action.set_takeoff_altitude(
                    float(
                        mission[
                            "takeoff_altitude_m"
                        ]
                    )
                ),
                retries,
                retry_delay_s,
                drone_id,
            )
        else:
            print(
                f"[{drone_id}] skipping explicit "
                "set_takeoff_altitude command; "
                "mission waypoint altitude remains "
                "authoritative"
            )

'''

    text = replace_once(
        text,
        old_block,
        new_block,
        "configuration-gated takeoff altitude command",
    )

    RUNNER_PATH.write_text(text)


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(
            f"Project root not found: {PROJECT_ROOT}"
        )

    patch_execution_config()
    patch_runner()

    print(
        "Point 22C.2 takeoff-altitude command "
        "gate installed."
    )
    print(
        "Validation config now skips the unstable "
        "set_takeoff_altitude MAVSDK action."
    )
    print(
        "Waypoint altitude and Gazebo pose remain "
        "the authoritative altitude controls."
    )


if __name__ == "__main__":
    main()
