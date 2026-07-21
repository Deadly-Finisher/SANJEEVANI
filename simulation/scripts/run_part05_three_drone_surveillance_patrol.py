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

# Low-load values so Gazebo does not crash.
STEPS_PER_SEGMENT = 18
STEP_DELAY_S = 0.45
LOOPS = 1

DRONES = {
    "drone_1": {
        "model": "x500_mono_cam_1",
        "zone": "LEFT_FLANK_SURVEILLANCE",
        "altitude_m": 12.0,
        "waypoints": [
            (-30, -38, 1.0),
            (-30, -38, 12.0),
            (-48, -25, 12.0),
            (-48, 0, 12.0),
            (-28, 0, 12.0),
            (-28, -25, 12.0),
            (-30, -38, 12.0),
            (-30, -38, 1.0),
        ],
    },
    "drone_2": {
        "model": "x500_mono_cam_2",
        "zone": "CENTER_ROAD_SURVEILLANCE",
        "altitude_m": 16.0,
        "waypoints": [
            (0, -38, 1.0),
            (0, -38, 16.0),
            (-10, -22, 16.0),
            (-10, 8, 16.0),
            (14, 8, 16.0),
            (14, -22, 16.0),
            (0, -38, 16.0),
            (0, -38, 1.0),
        ],
    },
    "drone_3": {
        "model": "x500_mono_cam_3",
        "zone": "RIGHT_OVERWATCH_SURVEILLANCE",
        "altitude_m": 20.0,
        "waypoints": [
            (30, -38, 1.0),
            (30, -38, 20.0),
            (36, -22, 20.0),
            (36, 8, 20.0),
            (58, 8, 20.0),
            (58, -22, 20.0),
            (30, -38, 20.0),
            (30, -38, 1.0),
        ],
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: str, check: bool = True) -> str:
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and result.returncode != 0:
        print(result.stdout)
        raise RuntimeError(cmd)
    return result.stdout


def yaw_between(a, b) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def lerp(a, b, step: int, total: int):
    t = step / max(1, total - 1)
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def set_pose(model: str, x: float, y: float, z: float, yaw: float) -> bool:
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)

    req = (
        f'name: "{model}" '
        f'position {{ x: {x:.3f} y: {y:.3f} z: {z:.3f} }} '
        f'orientation {{ x: 0 y: 0 z: {qz:.6f} w: {qw:.6f} }}'
    )

    cmd = (
        f'gz service -s /world/{WORLD}/set_pose '
        f'--reqtype gz.msgs.Pose '
        f'--reptype gz.msgs.Boolean '
        f'--timeout 3000 '
        f'--req \'{req}\''
    )

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    return result.returncode == 0


def dist(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


def safety_state(states: dict) -> dict:
    names = list(states)
    pairwise = {}
    min_d = 99999.0
    min_pair = "NA"

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = names[i]
            b = names[j]
            d = dist(states[a], states[b])
            pairwise[f"{a}_to_{b}_m"] = round(d, 2)
            if d < min_d:
                min_d = d
                min_pair = f"{a}-{b}"

    return {
        "status": "SAFE" if min_d >= 6 else "WARNING",
        "altitude_separation_enabled": True,
        "minimum_3d_separation_m": round(min_d, 2),
        "closest_pair": min_pair,
        "pairwise_distances_m": pairwise,
    }


def write_live(
    mission_status: str,
    phase: str,
    loop_idx: int,
    segment: int,
    step: int,
    states: dict,
    start: float,
):
    LIVE_STATE.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "project": "Battlefield Intelligence using Drone Swarms",
        "world": WORLD,
        "mission": {
            "part": "part-05",
            "name": "altitude_separated_surveillance_patrol",
            "status": mission_status,
            "phase": phase,
            "loop": loop_idx,
            "total_loops": LOOPS,
            "segment": segment,
            "step": step,
            "elapsed_s": round(time.time() - start, 2),
            "updated_at_utc": now_utc(),
        },
        "feeds": {
            "drone_1": "http://127.0.0.1:5011/video_feed",
            "drone_2": "http://127.0.0.1:5012/video_feed",
            "drone_3": "http://127.0.0.1:5013/video_feed",
            "dashboard": "http://127.0.0.1:8502",
        },
        "drones": states,
        "safety": safety_state(states),
        "operator_notes": [
            "Drone 1 patrols left flank at 12m.",
            "Drone 2 patrols center road/assets at 16m.",
            "Drone 3 patrols right overwatch lane at 20m.",
            "Obstacle avoidance and live replanning are paused future-scope modules.",
        ],
    }

    tmp = LIVE_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(LIVE_STATE)


def verify_runtime():
    px4_count = run("pgrep -x px4 | wc -l").strip()
    if px4_count != "3":
        raise RuntimeError(f"Expected 3 PX4 processes, found {px4_count}")

    services = run("gz service -l", check=False)
    if f"/world/{WORLD}/set_pose" not in services:
        raise RuntimeError(
            f"Missing /world/{WORLD}/set_pose. "
            "Relaunch launch_v1_three_drone_swarm.sh."
        )

    topics = run("gz topic -l", check=False)
    for item in DRONES.values():
        topic = (
            f"/world/{WORLD}/model/{item['model']}/link/"
            "camera_link/sensor/camera/image"
        )
        if topic not in topics:
            raise RuntimeError(f"Missing camera topic for {item['model']}")

    log("PASS: Gazebo + 3 drones + set_pose ready")


def patrol():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    telemetry = []
    start = time.time()
    segment_count = len(next(iter(DRONES.values()))["waypoints"]) - 1

    log("STARTING LOW-LOAD REAL SURVEILLANCE PATROL")
    log("Drone 1: 12m left lane")
    log("Drone 2: 16m center lane")
    log("Drone 3: 20m right lane")

    for loop_idx in range(1, LOOPS + 1):
        for seg_idx in range(segment_count):
            phase = (
                "takeoff"
                if seg_idx == 0
                else "landing"
                if seg_idx == segment_count - 1
                else "surveillance_sweep"
            )

            log(f"Loop {loop_idx}/{LOOPS} | Segment {seg_idx + 1}/{segment_count} | {phase}")

            for step in range(STEPS_PER_SEGMENT):
                states = {}
                row = {
                    "timestamp_utc": now_utc(),
                    "loop": loop_idx,
                    "segment": seg_idx + 1,
                    "step": step,
                    "phase": phase,
                }

                for name, item in DRONES.items():
                    a = item["waypoints"][seg_idx]
                    b = item["waypoints"][seg_idx + 1]
                    x, y, z = lerp(a, b, step, STEPS_PER_SEGMENT)
                    yaw = yaw_between(a, b)

                    ok = set_pose(item["model"], x, y, z, yaw)
                    if not ok:
                        raise RuntimeError(f"set_pose failed for {item['model']}")

                    states[name] = {
                        "id": name,
                        "model": item["model"],
                        "zone": item["zone"],
                        "assigned_altitude_m": item["altitude_m"],
                        "x": round(x, 3),
                        "y": round(y, 3),
                        "z": round(z, 3),
                        "yaw_rad": round(yaw, 4),
                        "current_waypoint": seg_idx + 1,
                        "next_waypoint": seg_idx + 2,
                        "phase": phase,
                        "status": "PATROLLING" if phase == "surveillance_sweep" else phase.upper(),
                    }

                    row[f"{name}_x"] = round(x, 3)
                    row[f"{name}_y"] = round(y, 3)
                    row[f"{name}_z"] = round(z, 3)
                    row[f"{name}_zone"] = item["zone"]

                row["minimum_3d_separation_m"] = safety_state(states)[
                    "minimum_3d_separation_m"
                ]

                telemetry.append(row)
                write_live("RUNNING", phase, loop_idx, seg_idx + 1, step, states, start)

                time.sleep(STEP_DELAY_S)

    final_states = {}
    for name, item in DRONES.items():
        x, y, z = item["waypoints"][-1]
        final_states[name] = {
            "id": name,
            "model": item["model"],
            "zone": item["zone"],
            "assigned_altitude_m": item["altitude_m"],
            "x": x,
            "y": y,
            "z": z,
            "yaw_rad": 0,
            "current_waypoint": len(item["waypoints"]),
            "next_waypoint": None,
            "phase": "landed",
            "status": "LANDED",
        }

    write_live(
        "COMPLETED",
        "landed",
        LOOPS,
        segment_count,
        STEPS_PER_SEGMENT,
        final_states,
        start,
    )

    csv_path = OUT_DIR / "part05_altitude_separated_surveillance_telemetry.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(telemetry[0].keys()))
        writer.writeheader()
        writer.writerows(telemetry)

    summary = {
        "part": "part-05",
        "status": "completed",
        "result": "PASS",
        "task": "low-load altitude-separated surveillance patrol",
        "world": WORLD,
        "loops": LOOPS,
        "steps_per_segment": STEPS_PER_SEGMENT,
        "step_delay_s": STEP_DELAY_S,
        "drones": DRONES,
        "telemetry_csv": str(csv_path.relative_to(ROOT)),
        "live_state_json": str(LIVE_STATE.relative_to(ROOT)),
        "completed_at_utc": now_utc(),
    }

    summary_path = REPORT_DIR / "part05_realistic_surveillance_patrol_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_path = REPORT_DIR / "part05_realistic_surveillance_patrol_report.md"
    report_path.write_text(
        """# Part 5: Altitude-Separated Three-Drone Surveillance Patrol

## Result

PASS

## Patrol Behaviour

- Drone 1 covers the left flank at 12m.
- Drone 2 covers the center route at 16m.
- Drone 3 covers the right overwatch lane at 20m.
- The drones follow horizontal surveillance sweep paths, not only vertical motion.

## Safety

The patrol uses different lanes and different altitudes to reduce collision risk.

## Dashboard

Live telemetry is written to `outputs/live/swarm_live_state.json`.
""",
        encoding="utf-8",
    )

    log(f"Summary: {summary_path}")
    log(f"Report: {report_path}")


def main():
    verify_runtime()
    patrol()

    print()
    print("======================================")
    print("PART 5 VALIDATION: PASS")
    print("Altitude-separated surveillance patrol completed.")
    print("Dashboard: http://127.0.0.1:8502")
    print("======================================")


if __name__ == "__main__":
    main()
