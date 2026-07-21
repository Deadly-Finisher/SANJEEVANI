#!/usr/bin/env python3
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(
    os.environ.get(
        "PROJECT_ROOT",
        str(Path.home() / "Programs" / "SWARM_DRONES"),
    )
).expanduser().resolve()

GUARD = PROJECT_ROOT / "swarm/safety/mission_safety_guard.py"
RUNNER = PROJECT_ROOT / "simulation/scripts/run_one_swarm_drone_mission.py"
CURRENT_CONFIG = PROJECT_ROOT / "configs/safety/v1_swarm_mavsdk_safety_controller.yaml"
DRY_CONFIG = PROJECT_ROOT / "configs/safety/v1_swarm_mavsdk_safety_dry_run.yaml"
LIVE_CONFIG = PROJECT_ROOT / "configs/safety/v1_swarm_mavsdk_safety_live.yaml"
VALIDATOR = PROJECT_ROOT / "swarm/safety/validate_safety_config.py"
BACKUP_DIR = PROJECT_ROOT / "backups/obstacle_avoidance"

DRY_YAML = '''controller:
  node_name: v1_swarm_mavsdk_safety_controller
  mode: dry_run
  command_cooldown_s: 3.0
  status_timeout_s: 12.0
  connection_timeout_s: 30.0
  require_in_air_for_action: true
  decision_log_csv: outputs/swarm/v1_three_drone_swarm/safety/mavsdk_safety_decisions.csv
  startup_grace_period_s: 15.0
  telemetry_timeout_s: 10.0
  require_initial_status: true
  initial_status_timeout_s: 30.0
  safety_poll_interval_s: 0.5
  normal_speed_m_s: 0.3
  mission_event_log_template: outputs/swarm/v1_three_drone_swarm/safety/{drone_id}_mission_safety_events.csv
  status_source: csv
  obstacle_status_csv: outputs/swarm/v1_three_drone_swarm/safety/obstacle_distance_log.csv

policy:
  allowed_takeoff_states:
    - clear
  enforce_takeoff_gate_in_dry_run: false
  takeoff_wait_timeout_s: 30.0
  takeoff_poll_interval_s: 0.5
  maximum_hold_duration_s: 30.0
  resume_clear_delay_s: 2.0
  fail_on_hold_timeout: true

actions:
  clear:
    command: none
  warning:
    command: set_current_speed
    speed_m_s: 0.15
  critical:
    command: hold
  emergency_stop:
    command: hold
  no_data:
    command: hold

drones:
  - drone_id: drone_1
    status_topic: /drone_1/obstacle_status
    system_address: udpin://0.0.0.0:14541
    grpc_port: 50101
  - drone_id: drone_2
    status_topic: /drone_2/obstacle_status
    system_address: udpin://0.0.0.0:14542
    grpc_port: 50102
  - drone_id: drone_3
    status_topic: /drone_3/obstacle_status
    system_address: udpin://0.0.0.0:14543
    grpc_port: 50103
'''

LIVE_YAML = DRY_YAML.replace("mode: dry_run", "mode: live", 1).replace(
    "mavsdk_safety_decisions.csv",
    "mavsdk_safety_decisions_live.csv",
    1,
).replace(
    "{drone_id}_mission_safety_events.csv",
    "{drone_id}_mission_safety_events_live.csv",
    1,
).replace(
    "enforce_takeoff_gate_in_dry_run: false",
    "enforce_takeoff_gate_in_dry_run: true",
    1,
).replace(
    "takeoff_wait_timeout_s: 30.0",
    "takeoff_wait_timeout_s: 45.0",
    1,
)

VALIDATOR_CODE = r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

VALID_STATES = {
    "clear",
    "warning",
    "critical",
    "emergency_stop",
    "no_data",
}
VALID_MODES = {"dry_run", "live"}


def require_positive(mapping, key, errors):
    try:
        value = float(mapping[key])
    except (KeyError, TypeError, ValueError):
        errors.append(f"{key} must be numeric")
        return

    if value <= 0:
        errors.append(f"{key} must be greater than zero")


def validate(path: Path):
    errors = []

    try:
        config = yaml.safe_load(path.read_text())
    except Exception as error:
        return [f"Unable to load YAML: {error}"]

    if not isinstance(config, dict):
        return ["Top-level YAML value must be a mapping"]

    controller = config.get("controller", {})
    policy = config.get("policy", {})
    actions = config.get("actions", {})
    drones = config.get("drones", [])

    if controller.get("mode") not in VALID_MODES:
        errors.append(
            f"controller.mode must be one of {sorted(VALID_MODES)}"
        )

    for key in (
        "command_cooldown_s",
        "status_timeout_s",
        "initial_status_timeout_s",
        "safety_poll_interval_s",
        "normal_speed_m_s",
    ):
        require_positive(controller, key, errors)

    allowed_states = policy.get("allowed_takeoff_states", [])

    if not allowed_states:
        errors.append("policy.allowed_takeoff_states cannot be empty")
    else:
        invalid_states = set(allowed_states) - VALID_STATES

        if invalid_states:
            errors.append(
                "Invalid allowed takeoff states: "
                + ", ".join(sorted(invalid_states))
            )

    for key in (
        "takeoff_wait_timeout_s",
        "takeoff_poll_interval_s",
        "maximum_hold_duration_s",
        "resume_clear_delay_s",
    ):
        require_positive(policy, key, errors)

    for state in VALID_STATES:
        if state not in actions:
            errors.append(f"actions.{state} is required")

    try:
        normal_speed = float(controller["normal_speed_m_s"])
        warning_speed = float(actions["warning"]["speed_m_s"])

        if warning_speed >= normal_speed:
            errors.append(
                "warning speed must be lower than normal speed"
            )
    except (KeyError, TypeError, ValueError):
        errors.append(
            "warning speed and normal speed must be numeric"
        )

    if not isinstance(drones, list) or not drones:
        errors.append("At least one drone is required")
    else:
        drone_ids = [item.get("drone_id") for item in drones]
        grpc_ports = [item.get("grpc_port") for item in drones]

        if len(drone_ids) != len(set(drone_ids)):
            errors.append("Drone IDs must be unique")

        if len(grpc_ports) != len(set(grpc_ports)):
            errors.append("gRPC ports must be unique")

    if controller.get("status_source") != "csv":
        errors.append(
            "controller.status_source must currently be csv"
        )

    if not controller.get("obstacle_status_csv"):
        errors.append(
            "controller.obstacle_status_csv is required"
        )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    errors = validate(arguments.config)

    if errors:
        print(f"INVALID: {arguments.config}")

        for error in errors:
            print(f"  - {error}")

        raise SystemExit(1)

    print(f"VALID: {arguments.config}")


if __name__ == "__main__":
    main()
'''


def replace_once(text: str, old: str, new: str, description: str) -> str:
    if new in text:
        return text

    if old not in text:
        raise RuntimeError(f"Patch marker not found: {description}")

    return text.replace(old, new, 1)


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(f"Project root not found: {PROJECT_ROOT}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    for source, backup_name in (
        (GUARD, "mission_safety_guard_before_point20.py"),
        (RUNNER, "run_one_swarm_drone_mission_before_point20.py"),
        (
            CURRENT_CONFIG,
            "v1_swarm_mavsdk_safety_controller_before_point20.yaml",
        ),
    ):
        shutil.copy2(source, BACKUP_DIR / backup_name)

    DRY_CONFIG.write_text(DRY_YAML)
    LIVE_CONFIG.write_text(LIVE_YAML)
    CURRENT_CONFIG.write_text(DRY_YAML)
    VALIDATOR.write_text(VALIDATOR_CODE)
    VALIDATOR.chmod(0o755)

    guard = GUARD.read_text()

    guard = replace_once(
        guard,
        '''        self.actions = config["actions"]

        if not any(
''',
        '''        self.actions = config["actions"]
        policy = config["policy"]

        self.allowed_takeoff_states = set(
            policy["allowed_takeoff_states"]
        )
        self.enforce_takeoff_gate_in_dry_run = bool(
            policy["enforce_takeoff_gate_in_dry_run"]
        )
        self.takeoff_wait_timeout_s = float(
            policy["takeoff_wait_timeout_s"]
        )
        self.takeoff_poll_interval_s = float(
            policy["takeoff_poll_interval_s"]
        )
        self.maximum_hold_duration_s = float(
            policy["maximum_hold_duration_s"]
        )
        self.resume_clear_delay_s = float(
            policy["resume_clear_delay_s"]
        )
        self.fail_on_hold_timeout = bool(
            policy["fail_on_hold_timeout"]
        )

        if not any(
''',
        "policy initialization",
    )

    takeoff_method = '''    async def wait_for_takeoff_clearance(self):
        start = time.monotonic()

        while True:
            state, status, age_s = self._snapshot()

            if state in self.allowed_takeoff_states:
                print(
                    f"[{self.drone_id}] takeoff safety "
                    f"clearance granted: {state}"
                )
                return state

            if (
                self.mode != "live"
                and not self.enforce_takeoff_gate_in_dry_run
            ):
                self._record(
                    state,
                    "takeoff_gate",
                    "dry_run_bypassed",
                    status,
                    age_s,
                )
                return state

            if (
                time.monotonic() - start
                > self.takeoff_wait_timeout_s
            ):
                raise TimeoutError(
                    f"Takeoff blocked by safety state: {state}"
                )

            await asyncio.sleep(
                self.takeoff_poll_interval_s
            )

'''

    if "async def wait_for_takeoff_clearance(" not in guard:
        guard = replace_once(
            guard,
            "    def _cooldown_complete(self):\n",
            takeoff_method + "    def _cooldown_complete(self):\n",
            "takeoff method insertion",
        )

    guard = replace_once(
        guard,
        '''            self._hold_active = True
            self._last_state = state

            while True:
                await asyncio.sleep(self.poll_interval_s)

                next_state, next_status, next_age = (
''',
        '''            self._hold_active = True
            self._last_state = state
            hold_started = time.monotonic()

            while True:
                await asyncio.sleep(self.poll_interval_s)

                if (
                    time.monotonic() - hold_started
                    > self.maximum_hold_duration_s
                ):
                    self._record(
                        state,
                        "hold_timeout",
                        "maximum_hold_duration_exceeded",
                        status,
                        age_s,
                    )

                    if self.fail_on_hold_timeout:
                        raise TimeoutError(
                            "Maximum safety hold duration exceeded"
                        )

                    return state

                next_state, next_status, next_age = (
''',
        "maximum hold duration",
    )

    guard = replace_once(
        guard,
        '''                speed = self.normal_speed_m_s

                if next_state == "warning":
''',
        '''                if self.resume_clear_delay_s > 0:
                    await asyncio.sleep(
                        self.resume_clear_delay_s
                    )

                    next_state, next_status, next_age = (
                        self._snapshot()
                    )

                    if next_state not in {"clear", "warning"}:
                        continue

                speed = self.normal_speed_m_s

                if next_state == "warning":
''',
        "resume clearance delay",
    )

    GUARD.write_text(guard)

    runner = RUNNER.read_text()
    runner = replace_once(
        runner,
        '''        await safety_guard.wait_for_initial_status()

        start_position = state["position"]
''',
        '''        await safety_guard.wait_for_initial_status()
        await safety_guard.wait_for_takeoff_clearance()

        start_position = state["position"]
''',
        "runner takeoff gate",
    )
    RUNNER.write_text(runner)

    for path in (GUARD, RUNNER, VALIDATOR):
        py_compile.compile(str(path), doraise=True)

    for config_path in (DRY_CONFIG, LIVE_CONFIG, CURRENT_CONFIG):
        subprocess.run(
            [sys.executable, str(VALIDATOR), str(config_path)],
            check=True,
        )

    print()
    print("Point 20 safety configuration applied successfully.")
    print(f"Dry-run config: {DRY_CONFIG.relative_to(PROJECT_ROOT)}")
    print(f"Live config: {LIVE_CONFIG.relative_to(PROJECT_ROOT)}")
    print(f"Validator: {VALIDATOR.relative_to(PROJECT_ROOT)}")
    print("Current controller config remains mapped to dry-run mode.")


if __name__ == "__main__":
    main()
