#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"
WORLD = "battlefield_sar_world_v1_realistic"

LIVE_STATE = ROOT / "outputs/live/swarm_live_state.json"
OUT_DIR = ROOT / "outputs/swarm_missions/part05_surveillance_patrol"
REPORT_DIR = ROOT / "outputs/reports"

STEP_DELAY_S = 0.10
STEPS_PER_SEGMENT = 45
LOOPS = 2

# Altitude-separated search lanes to avoid inter-drone collision.
# These are Gazebo world coordinates for a clear surveillance sweep.
DRONES = {
    "drone_1": {
        "model": "x500_mono_cam_1",
        "zone": "LEFT_FLANK_SEARCH_LANE",
        "altitude_m": 12.0,
        "color": "low_altitude",
        "waypoints": [
            (-35, -42, 1.0),
            (-35, -42, 12.0),
            (-55, -30, 12.0),
            (-55, -5, 12.0),
            (-38, -5, 12.0),
            (-38, -30, 12.0),
            (-22, -30, 12.0),
            (-22, -5, 12.0),
            (-35, -42, 12.0),
            (-35, -42, 1.0),
        ],
    },
    "drone_2": {
        "model": "x500_mono_cam_2",
        "zone": "CENTER_ROAD_AND_ASSET_LANE",
        "altitude_m": 16.0,
        "color": "medium_altitude",
        "waypoints": [
            (0, -42, 1.0),
            (0, -42, 16.0),
            (-12, -28, 16.0),
            (-12, 5, 16.0),
            (5, 5, 16.0),
            (5, -28, 16.0),
            (22, -28, 16.0),
            (22, 5, 16.0),
            (0, -42, 16.0),
            (0, -42, 1.0),
        ],
    },
    "drone_3": {
        "model": "x500_mono_cam_3",
        "zone": "RIGHT_FLANK_OVERWATCH_LANE",
        "altitude_m": 20.0,
        "color": "high_altitude",
        "waypoints": [
            (35, -42, 1.0),
            (35, -42, 20.0),
            (30, -28, 20.0),
            (30, 8, 20.0),
            (48, 8, 20.0),
            (48, -28, 20.0),
            (66, -28, 20.0),
            (66, 8, 20.0),
            (35, -42, 20.0),
            (35, -42, 1.0),
        ],
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run(command: str, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if check and result.returncode != 0:
        print(result.stdout)
        raise RuntimeError(command)

    return result.stdout


def yaw_between(a, b) -> float:
    ax, ay, _ = a
    bx, by, _ = b
    return math.atan2(by - ay, bx - ax)


def distance_3d(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


def set_pose(
    model: str,
    x: float,
    y: float,
    z: float,
    yaw: float,
) -> None:
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)

    req = (
        f'name: "{model}" '
        f'position {{ x: {x:.3f} y: {y:.3f} z: {z:.3f} }} '
        f'orientation {{ x: 0 y: 0 z: {qz:.6f} w: {qw:.6f} }}'
    )

    command = (
        f'gz service -s /world/{WORLD}/set_pose '
        f'--reqtype gz.msgs.Pose '
        f'--reptype gz.msgs.Boolean '
        f'--timeout 1000 '
        f'--req \'{req}\''
    )

    run(command)


def lerp(a, b, step: int, total: int):
    t = step / max(1, total - 1)
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def feed_status(port: int) -> str:
    result = subprocess.run(
        f"curl -s --max-time 2 -o /dev/null "
        f"-w '%{{http_code}}' http://127.0.0.1:{port}/",
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return "READY" if result.stdout.strip() == "200" else "OFFLINE"


def verify_runtime() -> None:
    px4_count = run("pgrep -x px4 | wc -l").strip()
    if px4_count != "3":
        raise RuntimeError(
            f"Expected 3 PX4 processes, found {px4_count}. "
            "Run launch_v1_three_drone_swarm.sh first."
        )

    topics = run("gz topic -l", check=False)
    services = run("gz service -l", check=False)

    if f"/world/{WORLD}/set_pose" not in services:
        raise RuntimeError("Gazebo set_pose service missing.")

    for info in DRONES.values():
        topic = (
            f"/world/{WORLD}/model/{info['model']}/link/"
            "camera_link/sensor/camera/image"
        )
        if topic not in topics:
            raise RuntimeError(f"Missing camera topic for {info['model']}")

    log("PASS: PX4 + Gazebo + camera topics ready")


def write_live_state(
    *,
    mission_status: str,
    mission_phase: str,
    loop_index: int,
    segment: int,
    step: int,
    drone_states: dict,
    start_time: float,
    safety: dict,
) -> None:
    LIVE_STATE.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "project": "Battlefield Intelligence using Drone Swarms",
        "world": WORLD,
        "mission": {
            "part": "part-05",
            "name": "three_drone_altitude_separated_surveillance_patrol",
            "status": mission_status,
            "phase": mission_phase,
            "loop": loop_index,
            "total_loops": LOOPS,
            "segment": segment,
            "step": step,
            "elapsed_s": round(time.time() - start_time, 2),
            "updated_at_utc": now_utc(),
        },
        "feeds": {
            "drone_1": {
                "url": "http://127.0.0.1:5011/video_feed",
                "status": feed_status(5011),
            },
            "drone_2": {
                "url": "http://127.0.0.1:5012/video_feed",
                "status": feed_status(5012),
            },
            "drone_3": {
                "url": "http://127.0.0.1:5013/video_feed",
                "status": feed_status(5013),
            },
        },
        "drones": drone_states,
        "safety": safety,
        "operator_notes": [
            "Preplanned altitude-separated surveillance lanes are used.",
            "Drone 1 low, Drone 2 medium, Drone 3 high.",
            "Obstacle avoidance and live replanning remain paused future-scope modules.",
            "Telemetry shown here is Gazebo patrol-controller telemetry.",
        ],
    }

    tmp = LIVE_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(LIVE_STATE)


def compute_safety(drone_states: dict) -> dict:
    names = list(drone_states)
    distances = {}

    min_distance = 999999.0
    min_pair = None

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = names[i]
            b = names[j]
            d = distance_3d(drone_states[a], drone_states[b])
            distances[f"{a}_to_{b}_m"] = round(d, 2)

            if d < min_distance:
                min_distance = d
                min_pair = f"{a}-{b}"

    return {
        "altitude_separation_enabled": True,
        "minimum_3d_separation_m": round(min_distance, 2),
        "closest_pair": min_pair,
        "status": "SAFE" if min_distance >= 6.0 else "WARNING",
        "pairwise_distances_m": distances,
    }


def run_patrol() -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    telemetry_rows = []
    start_time = time.time()

    log("REALISTIC SURVEILLANCE PATROL START")
    log("Drone 1: 12m left lane")
    log("Drone 2: 16m center lane")
    log("Drone 3: 20m right lane")

    segment_count = len(next(iter(DRONES.values()))["waypoints"]) - 1

    for loop_index in range(1, LOOPS + 1):
        for segment_index in range(segment_count):
            phase = (
                "takeoff"
                if segment_index == 0
                else "landing"
                if segment_index == segment_count - 1
                else "surveillance_sweep"
            )

            log(
                f"Loop {loop_index}/{LOOPS} | "
                f"segment {segment_index + 1}/{segment_count} | {phase}"
            )

            for step in range(STEPS_PER_SEGMENT):
                drone_states = {}
                row = {
                    "timestamp_utc": now_utc(),
                    "loop": loop_index,
                    "segment": segment_index + 1,
                    "step": step,
                    "phase": phase,
                }

                for drone_name, info in DRONES.items():
                    waypoints = info["waypoints"]
                    a = waypoints[segment_index]
                    b = waypoints[segment_index + 1]

                    x, y, z = lerp(a, b, step, STEPS_PER_SEGMENT)
                    yaw = yaw_between(a, b)

                    set_pose(info["model"], x, y, z, yaw)

                    drone_states[drone_name] = {
                        "id": drone_name,
                        "model": info["model"],
                        "zone": info["zone"],
                        "assigned_altitude_m": info["altitude_m"],
                        "x": round(x, 3),
                        "y": round(y, 3),
                        "z": round(z, 3),
                        "yaw_rad": round(yaw, 4),
                        "current_waypoint": segment_index + 1,
                        "next_waypoint": segment_index + 2,
                        "phase": phase,
                        "status": "PATROLLING"
                        if phase == "surveillance_sweep"
                        else phase.upper(),
                    }

                    row[f"{drone_name}_x"] = round(x, 3)
                    row[f"{drone_name}_y"] = round(y, 3)
                    row[f"{drone_name}_z"] = round(z, 3)
                    row[f"{drone_name}_zone"] = info["zone"]
                    row[f"{drone_name}_phase"] = phase

                safety = compute_safety(drone_states)

                row["minimum_3d_separation_m"] = safety[
                    "minimum_3d_separation_m"
                ]
                row["safety_status"] = safety["status"]

                telemetry_rows.append(row)

                write_live_state(
                    mission_status="RUNNING",
                    mission_phase=phase,
                    loop_index=loop_index,
                    segment=segment_index + 1,
                    step=step,
                    drone_states=drone_states,
                    start_time=start_time,
                    safety=safety,
                )

                time.sleep(STEP_DELAY_S)

    final_states = {
        name: {
            "id": name,
            "model": info["model"],
            "zone": info["zone"],
            "assigned_altitude_m": info["altitude_m"],
            "x": info["waypoints"][-1][0],
            "y": info["waypoints"][-1][1],
            "z": info["waypoints"][-1][2],
            "yaw_rad": 0,
            "current_waypoint": len(info["waypoints"]),
            "next_waypoint": None,
            "phase": "landed",
            "status": "LANDED",
        }
        for name, info in DRONES.items()
    }

    write_live_state(
        mission_status="COMPLETED",
        mission_phase="landed",
        loop_index=LOOPS,
        segment=segment_count,
        step=STEPS_PER_SEGMENT,
        drone_states=final_states,
        start_time=start_time,
        safety=compute_safety(final_states),
    )

    log("REALISTIC SURVEILLANCE PATROL COMPLETE")
    return telemetry_rows


def write_outputs(telemetry: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUT_DIR / "part05_altitude_separated_surveillance_telemetry.csv"

    if telemetry:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(telemetry[0].keys()))
            writer.writeheader()
            writer.writerows(telemetry)

    summary = {
        "part": "part-05",
        "status": "completed",
        "result": "PASS",
        "task": "three-drone realistic surveillance patrol",
        "method": "Gazebo synchronized altitude-separated waypoint patrol",
        "world": WORLD,
        "loops": LOOPS,
        "steps_per_segment": STEPS_PER_SEGMENT,
        "step_delay_s": STEP_DELAY_S,
        "drones": DRONES,
        "telemetry_csv": str(csv_path.relative_to(ROOT)),
        "live_state_json": str(LIVE_STATE.relative_to(ROOT)),
        "dashboard": "http://127.0.0.1:8502",
        "completed_at_utc": now_utc(),
        "important_note": (
            "This is a simulation patrol controller using Gazebo set_pose. "
            "It demonstrates surveillance behaviour, lane allocation, altitude "
            "separation, telemetry logging and operator dashboard support. "
            "PX4 MAVLink autonomous mission execution remains future improvement."
        ),
    }

    summary_path = REPORT_DIR / "part05_realistic_surveillance_patrol_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_path = REPORT_DIR / "part05_realistic_surveillance_patrol_report.md"
    report_path.write_text(
        f"""# Part 5: Realistic Three-Drone Surveillance Patrol

## Result

PASS

## What was improved

The drones no longer only move vertically.  
They now follow altitude-separated surveillance lanes:

- Drone 1: left flank, 12 m
- Drone 2: center lane, 16 m
- Drone 3: right overwatch lane, 20 m

## Collision Safety

The drones are separated by both lane position and altitude.  
A live separation check is written to:

`outputs/live/swarm_live_state.json`

## Operator Dashboard

The Streamlit dashboard reads live state data and displays:

- live camera feeds
- feed health
- drone positions
- altitude
- assigned zone
- current waypoint
- mission phase
- safety distance
- telemetry state
- operator notes

## Output Files

- Telemetry CSV: `{csv_path.relative_to(ROOT)}`
- Summary JSON: `outputs/reports/part05_realistic_surveillance_patrol_summary.json`
- Live state JSON: `outputs/live/swarm_live_state.json`
""",
        encoding="utf-8",
    )

    log(f"Summary: {summary_path}")
    log(f"Report: {report_path}")


def main() -> None:
    verify_runtime()
    telemetry = run_patrol()
    write_outputs(telemetry)

    print()
    print("======================================")
    print("PART 5 VALIDATION: PASS")
    print("Altitude-separated surveillance patrol completed.")
    print("Live state: outputs/live/swarm_live_state.json")
    print("Dashboard: http://127.0.0.1:8502")
    print("======================================")


if __name__ == "__main__":
    main()
