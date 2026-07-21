#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = (
    Path.home()
    / "Programs"
    / "SWARM_DRONES"
)

CONFIG_PATH = (
    ROOT
    / "configs/swarm/"
    "v1_swarm_mission_execution.yaml"
)

configuration = yaml.safe_load(
    CONFIG_PATH.read_text(
        encoding="utf-8",
    )
)

run_directory = (
    ROOT
    / configuration["output"]["run_log_dir"]
)

failed = False

print(
    "===== MISSION VALIDATION ====="
)

for drone in configuration["drones"]:
    drone_id = drone["drone_id"]

    mission_path = (
        ROOT
        / drone["mission_config"]
    )

    mission = yaml.safe_load(
        mission_path.read_text(
            encoding="utf-8",
        )
    )

    expected_waypoints = len(
        mission["waypoints"]
    )

    summary_path = (
        run_directory
        / f"{drone_id}_mission_summary.json"
    )

    if not summary_path.exists():
        print(
            f"{drone_id}: FAIL | "
            "summary missing"
        )

        failed = True
        continue

    summary = json.loads(
        summary_path.read_text(
            encoding="utf-8",
        )
    )

    completed = summary.get(
        "completed_waypoints",
        [],
    )

    all_arrived = (
        len(completed) > 0
        and all(
            bool(
                waypoint.get(
                    "arrived_within_tolerance"
                )
            )
            for waypoint in completed
        )
    )

    success = (
        summary.get("status") == "completed"
        and not summary.get("error")
        and len(completed)
        == expected_waypoints
        and all_arrived
    )

    marker = (
        "PASS"
        if success
        else "FAIL"
    )

    print(
        f"{drone_id}: {marker} | "
        f"status={summary.get('status')} | "
        f"waypoints={len(completed)}/"
        f"{expected_waypoints} | "
        f"all_arrived={all_arrived} | "
        f"error={summary.get('error')}"
    )

    if not success:
        failed = True


raise SystemExit(
    1 if failed else 0
)
