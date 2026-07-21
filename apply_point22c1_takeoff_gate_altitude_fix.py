#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

import yaml


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"

MODULE_PATH = (
    PROJECT_ROOT
    / "swarm"
    / "safety"
    / "local_obstacle_replanner.py"
)

LIVE_CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "safety"
    / "v1_swarm_local_replanner_simulation_live.yaml"
)

BACKUP_DIR = (
    PROJECT_ROOT
    / "backups"
    / "point22c1_takeoff_gate_and_altitude_fix"
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


def patch_config() -> None:
    backup(LIVE_CONFIG_PATH)

    config = yaml.safe_load(
        LIVE_CONFIG_PATH.read_text()
    )

    replanner = config["replanner"]

    replanner["activation"] = {
        "excluded_zone_names": [
            "validation_takeoff",
        ],
        "minimum_altitude_m": 2.0,
    }

    temporary = replanner[
        "temporary_waypoint"
    ]
    temporary[
        "minimum_altitude_m"
    ] = 2.5

    live = replanner[
        "live_execution"
    ]
    live[
        "set_speed_before_replan"
    ] = False
    live[
        "avoidance_speed_m_s"
    ] = 0.5

    LIVE_CONFIG_PATH.write_text(
        yaml.safe_dump(
            config,
            sort_keys=False,
        )
    )


def patch_module() -> None:
    backup(MODULE_PATH)
    text = MODULE_PATH.read_text()

    text = replace_once(
        text,
        '''        self.required_safety_guard_mode = str(
            replanner.get(
                "required_safety_guard_mode",
                "dry_run",
            )
        )

        self.poll_interval_s = float(
''',
        '''        self.required_safety_guard_mode = str(
            replanner.get(
                "required_safety_guard_mode",
                "dry_run",
            )
        )

        activation = replanner.get(
            "activation",
            {},
        )
        self.excluded_zone_names = {
            str(value)
            for value in activation.get(
                "excluded_zone_names",
                [],
            )
        }
        self.minimum_activation_altitude_m = float(
            activation.get(
                "minimum_altitude_m",
                0.0,
            )
        )

        self.poll_interval_s = float(
''',
        "activation configuration",
    )

    text = replace_once(
        text,
        '''        self.altitude_offset_m = float(
            temporary["altitude_offset_m"]
        )
        self.blocked_sides_action = str(
''',
        '''        self.altitude_offset_m = float(
            temporary["altitude_offset_m"]
        )
        self.minimum_temporary_altitude_m = float(
            temporary.get(
                "minimum_altitude_m",
                0.0,
            )
        )
        self.blocked_sides_action = str(
''',
        "minimum temporary altitude",
    )

    text = replace_once(
        text,
        '''        self.avoidance_speed_m_s = float(
            live.get(
                "avoidance_speed_m_s",
                0.15,
            )
        )
        self.resume_original_waypoint = bool(
''',
        '''        self.set_speed_before_replan = bool(
            live.get(
                "set_speed_before_replan",
                False,
            )
        )
        self.avoidance_speed_m_s = float(
            live.get(
                "avoidance_speed_m_s",
                0.15,
            )
        )
        self.resume_original_waypoint = bool(
''',
        "optional speed command",
    )

    text = replace_once(
        text,
        '''        right_min_m: float | None,
        safety_state: str,
    ) -> dict[str, Any]:
''',
        '''        right_min_m: float | None,
        safety_state: str,
        target_altitude_m: float | None = None,
    ) -> dict[str, Any]:
''',
        "plan target altitude argument",
    )

    text = replace_once(
        text,
        '''            "temporary_altitude_m": (
                current_altitude_m
                + self.altitude_offset_m
            ),
        }
''',
        '''            "temporary_altitude_m": max(
                current_altitude_m
                + self.altitude_offset_m,
                self.minimum_temporary_altitude_m,
                (
                    float(target_altitude_m)
                    if target_altitude_m is not None
                    else 0.0
                ),
            ),
        }
''',
        "safe temporary altitude calculation",
    )

    text = replace_once(
        text,
        '''        speed_error = await self._command_with_retry(
            "set avoidance speed",
            lambda: drone.action.set_current_speed(
                self.avoidance_speed_m_s
            ),
        )

        temporary_goto_error = (
''',
        '''        speed_error = None

        if self.set_speed_before_replan:
            speed_error = await self._command_with_retry(
                "set avoidance speed",
                lambda: drone.action.set_current_speed(
                    self.avoidance_speed_m_s
                ),
            )

        temporary_goto_error = (
''',
        "optional speed command execution",
    )

    text = replace_once(
        text,
        '''        safety_state, status, scan_age_s = (
            safety_guard.snapshot()
        )

        if (
            safety_state
            not in self.trigger_states
        ):
''',
        '''        zone_name = str(
            waypoint.get(
                "zone_name",
                "",
            )
        )
        current_altitude_m = float(
            position.relative_altitude_m
        )

        if zone_name in self.excluded_zone_names:
            return

        if (
            current_altitude_m
            < self.minimum_activation_altitude_m
        ):
            return

        safety_state, status, scan_age_s = (
            safety_guard.snapshot()
        )

        if (
            safety_state
            not in self.trigger_states
        ):
''',
        "takeoff and altitude activation gate",
    )

    text = replace_once(
        text,
        '''            right_min_m=self._number(
                status.get("right_min_m")
            ),
            safety_state=safety_state,
        )
''',
        '''            right_min_m=self._number(
                status.get("right_min_m")
            ),
            safety_state=safety_state,
            target_altitude_m=float(
                waypoint["altitude_m"]
            ),
        )
''',
        "target altitude supplied to planner",
    )

    MODULE_PATH.write_text(text)


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(
            f"Project root not found: {PROJECT_ROOT}"
        )

    patch_config()
    patch_module()

    print(
        "Point 22C.1 takeoff gate and "
        "temporary-altitude fix installed."
    )
    print(
        "Live replanning is now disabled during "
        "validation_takeoff and below 2.0 m."
    )
    print(
        "Temporary avoidance altitude is never "
        "below 2.5 m or the original target altitude."
    )
    print(
        "The unreliable set_current_speed command "
        "is disabled for this validation."
    )


if __name__ == "__main__":
    main()
