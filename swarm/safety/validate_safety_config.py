#!/usr/bin/env python3
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
