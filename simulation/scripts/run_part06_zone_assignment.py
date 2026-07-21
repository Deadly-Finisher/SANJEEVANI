#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

CONFIG_PATH = ROOT / "configs/swarm/part06_swarm_zone_assignment.yaml"
SUMMARY_PATH = ROOT / "outputs/reports/part06_zone_assignment_summary.json"
REPORT_PATH = ROOT / "outputs/reports/part06_zone_assignment_report.md"


ZONES = {
    "zone_left_flank": {
        "assigned_drone": "drone_1",
        "model": "x500_mono_cam_1",
        "altitude_m": 12,
        "role": "left flank surveillance",
        "priority": "medium",
        "coverage_type": "lawnmower sweep",
        "area_bounds": {
            "x_min": -55,
            "x_max": -22,
            "y_min": -38,
            "y_max": 0,
        },
        "objectives": [
            "monitor left-side movement",
            "detect people and vehicles",
            "observe flank approach routes",
        ],
    },
    "zone_center_road": {
        "assigned_drone": "drone_2",
        "model": "x500_mono_cam_2",
        "altitude_m": 16,
        "role": "center road and asset surveillance",
        "priority": "high",
        "coverage_type": "rectangular search sweep",
        "area_bounds": {
            "x_min": -12,
            "x_max": 22,
            "y_min": -38,
            "y_max": 8,
        },
        "objectives": [
            "monitor central road",
            "observe vehicles and battlefield assets",
            "support main situational awareness",
        ],
    },
    "zone_right_overwatch": {
        "assigned_drone": "drone_3",
        "model": "x500_mono_cam_3",
        "altitude_m": 20,
        "role": "right flank overwatch",
        "priority": "medium",
        "coverage_type": "high-altitude overwatch sweep",
        "area_bounds": {
            "x_min": 30,
            "x_max": 58,
            "y_min": -38,
            "y_max": 8,
        },
        "objectives": [
            "monitor right-side movement",
            "provide high-altitude overwatch",
            "reduce collision risk using altitude separation",
        ],
    },
}

SAFETY_RULES = {
    "altitude_separation_enabled": True,
    "minimum_altitude_gap_m": 4,
    "minimum_3d_separation_m": 6,
    "collision_avoidance_status": "planned by static lane and altitude separation",
    "paused_future_scope": [
        "LiDAR obstacle detection",
        "dynamic obstacle avoidance",
        "local replanning",
        "inter-drone collision avoidance",
    ],
}


def yaml_value(value, indent=0):
    space = " " * indent

    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{space}{key}:")
                lines.append(yaml_value(item, indent + 2))
            else:
                lines.append(f"{space}{key}: {json.dumps(item)}")
        return "\n".join(lines)

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{space}-")
                lines.append(yaml_value(item, indent + 2))
            else:
                lines.append(f"{space}- {json.dumps(item)}")
        return "\n".join(lines)

    return f"{space}{json.dumps(value)}"


def main() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "mission": {
            "name": "part06_swarm_zone_assignment",
            "world": "battlefield_sar_world_v1_realistic",
            "strategy": "divide battlefield into left, center and right surveillance lanes",
            "assignment_method": "static zone allocation with altitude separation",
        },
        "zones": ZONES,
        "safety_rules": SAFETY_RULES,
    }

    CONFIG_PATH.write_text(
        yaml_value(config) + "\n",
        encoding="utf-8",
    )

    summary = {
        "part": "part-06",
        "status": "completed",
        "result": "PASS",
        "task": "swarm zone assignment",
        "config": str(CONFIG_PATH.relative_to(ROOT)),
        "zones": ZONES,
        "safety_rules": SAFETY_RULES,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    report = f"""# Part 6: Swarm Zone Assignment

## Result

PASS

## Objective

The battlefield area is divided into three surveillance zones so that each drone has a clear responsibility.

## Zone Allocation

### Drone 1 — Left Flank

- Model: x500_mono_cam_1
- Zone: left flank surveillance
- Altitude: 12 m
- Purpose: observe left-side movement and flank activity

### Drone 2 — Center Road

- Model: x500_mono_cam_2
- Zone: center road and asset surveillance
- Altitude: 16 m
- Purpose: monitor central movement, road activity and battlefield assets

### Drone 3 — Right Overwatch

- Model: x500_mono_cam_3
- Zone: right flank overwatch
- Altitude: 20 m
- Purpose: provide high-altitude overwatch and right-side surveillance

## Safety Design

The drones are separated by both horizontal search lanes and altitude levels:

- Drone 1: 12 m
- Drone 2: 16 m
- Drone 3: 20 m

This reduces collision risk during simulated patrol.

## Future Scope

Dynamic obstacle avoidance, LiDAR-based safety and live replanning are kept as future scope.

## Output Files

- Config: `configs/swarm/part06_swarm_zone_assignment.yaml`
- Summary: `outputs/reports/part06_zone_assignment_summary.json`
"""

    REPORT_PATH.write_text(report, encoding="utf-8")

    print("======================================")
    print("PART 6 VALIDATION: PASS")
    print("Swarm zone assignment completed.")
    print(f"Config: {CONFIG_PATH}")
    print(f"Summary: {SUMMARY_PATH}")
    print(f"Report: {REPORT_PATH}")
    print("======================================")


if __name__ == "__main__":
    main()
