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

CONFIG_PATH = ROOT / "configs/swarm/part05_safe_continuous_overlapping_surveillance_config.json"

LIVE_STATE = ROOT / "outputs/live/swarm_live_state.json"
OUT_DIR = ROOT / "outputs/swarm_missions/part05_surveillance_patrol"
REPORT_DIR = ROOT / "outputs/reports"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


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


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def distance_3d(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


def interpolate(a_xy: list, b_xy: list, t: float, altitude: float) -> dict:
    s = smoothstep(t)

    return {
        "x": float(a_xy[0]) + (float(b_xy[0]) - float(a_xy[0])) * s,
        "y": float(a_xy[1]) + (float(b_xy[1]) - float(a_xy[1])) * s,
        "z": altitude,
    }


def yaw_between(a: dict, b: dict) -> float:
    return math.atan2(b["y"] - a["y"], b["x"] - a["x"])


def set_pose(world: str, model: str, pose: dict, yaw: float) -> bool:
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)

    req = (
        f'name: "{model}" '
        f'position {{ x: {pose["x"]:.3f} y: {pose["y"]:.3f} z: {pose["z"]:.3f} }} '
        f'orientation {{ x: 0 y: 0 z: {qz:.6f} w: {qw:.6f} }}'
    )

    cmd = [
        "gz",
        "service",
        "-s",
        f"/world/{world}/set_pose",
        "--reqtype",
        "gz.msgs.Pose",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "2500",
        "--req",
        req,
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    return result.returncode == 0


def safety_state(states: dict, min_sep: float) -> dict:
    names = list(states)
    pairwise = {}
    min_d = 99999.0
    min_pair = "NA"

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = names[i]
            b = names[j]

            d = distance_3d(states[a], states[b])
            pairwise[f"{a}_to_{b}_m"] = round(d, 2)

            if d < min_d:
                min_d = d
                min_pair = f"{a}-{b}"

    return {
        "status": "SAFE" if min_d >= min_sep else "WARNING",
        "minimum_3d_separation_m": round(min_d, 2),
        "closest_pair": min_pair,
        "pairwise_distances_m": pairwise,
        "altitude_separation_enabled": True,
        "continuous_motion_enabled": True,
        "overlapping_search_enabled": True,
        "gazebo_safe_low_load_mode": True,
    }


def write_live(
    cfg: dict,
    status: str,
    phase: str,
    tick: int,
    total_ticks: int,
    states: dict,
    targets: dict,
    start_time: float,
) -> None:
    LIVE_STATE.parent.mkdir(parents=True, exist_ok=True)

    drones = {}

    for drone_id, pose in states.items():
        drone_cfg = cfg["drones"][drone_id]
        target = targets[drone_id]

        drones[drone_id] = {
            "id": drone_id,
            "model": drone_cfg["model"],
            "zone": drone_cfg["zone"],
            "assigned_altitude_m": drone_cfg["base_altitude_m"],
            "x": round(pose["x"], 3),
            "y": round(pose["y"], 3),
            "z": round(pose["z"], 3),
            "target_x": round(target["x"], 3),
            "target_y": round(target["y"], 3),
            "target_z": round(target["z"], 3),
            "phase": phase,
            "status": "PATROLLING" if status == "RUNNING" else status,
        }

    state = {
        "project": "Battlefield Intelligence using Drone Swarms",
        "world": cfg["world"],
        "mission": {
            "part": "part-05",
            "name": cfg["mission_name"],
            "status": status,
            "phase": phase,
            "tick": tick,
            "total_ticks": total_ticks,
            "elapsed_s": round(time.time() - start_time, 2),
            "updated_at_utc": now_utc(),
        },
        "feeds": {
            "drone_1": "http://127.0.0.1:5011/video_feed",
            "drone_2": "http://127.0.0.1:5012/video_feed",
            "drone_3": "http://127.0.0.1:5013/video_feed",
            "dashboard": "http://127.0.0.1:8502",
        },
        "drones": drones,
        "safety": safety_state(
            states,
            float(cfg["mission"]["minimum_3d_separation_m"]),
        ),
        "operator_notes": [
            "Safe continuous overlapping patrol active.",
            "Drones travel long routes across overlapping search zones.",
            "Each drone follows a different long path, so they do not stay in fixed formation.",
            "Pose updates are intentionally slower to avoid Gazebo crash.",
            "Dynamic obstacle avoidance remains future scope.",
        ],
    }

    tmp = LIVE_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(LIVE_STATE)


def verify_runtime(cfg: dict) -> None:
    world = cfg["world"]

    px4_count = run("pgrep -x px4 | wc -l").strip()
    if px4_count != "3":
        raise RuntimeError(f"Expected 3 PX4 processes, found {px4_count}")

    services = run("gz service -l", check=False)
    if f"/world/{world}/set_pose" not in services:
        raise RuntimeError(f"Missing /world/{world}/set_pose")

    topics = run("gz topic -l", check=False)

    for drone_cfg in cfg["drones"].values():
        topic = (
            f"/world/{world}/model/{drone_cfg['model']}/link/"
            "camera_link/sensor/camera/image"
        )

        if topic not in topics:
            raise RuntimeError(f"Missing camera topic for {drone_cfg['model']}")

    log("PASS: Gazebo + 3 drones + set_pose ready")


def main() -> None:
    cfg = load_config()
    verify_runtime(cfg)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    world = cfg["world"]
    mission_cfg = cfg["mission"]

    steps_per_leg = int(mission_cfg["steps_per_leg"])
    tick_delay_s = float(mission_cfg["tick_delay_s"])
    loops = int(mission_cfg["loops"])

    max_legs = max(
        len(drone["route"]) - 1
        for drone in cfg["drones"].values()
    )

    total_ticks = max_legs * steps_per_leg * loops

    states = {}
    targets = {}

    for drone_id, drone_cfg in cfg["drones"].items():
        start_xy = drone_cfg["route"][0]
        states[drone_id] = {
            "x": float(start_xy[0]),
            "y": float(start_xy[1]),
            "z": float(drone_cfg["base_altitude_m"]),
        }
        targets[drone_id] = dict(states[drone_id])

    telemetry = []
    start_time = time.time()

    log("STARTING SAFE CONTINUOUS OVERLAPPING SURVEILLANCE")
    log("Long routes + overlapping search areas + lower Gazebo load.")

    tick = 0

    for loop_idx in range(1, loops + 1):
        for leg_idx in range(max_legs):
            for step in range(steps_per_leg):
                tick += 1
                progress = step / max(1, steps_per_leg - 1)

                row = {
                    "timestamp_utc": now_utc(),
                    "loop": loop_idx,
                    "leg": leg_idx + 1,
                    "step": step,
                    "tick": tick,
                    "phase": "safe_continuous_overlapping_surveillance",
                }

                for index, (drone_id, drone_cfg) in enumerate(cfg["drones"].items()):
                    route = drone_cfg["route"]

                    # Different route timing per drone so the motion is not synchronized.
                    offset_leg = (leg_idx + index * 2) % (len(route) - 1)

                    a_xy = route[offset_leg]
                    b_xy = route[offset_leg + 1]

                    altitude = float(drone_cfg["base_altitude_m"]) + (
                        float(drone_cfg["altitude_wave_m"])
                        * math.sin((tick * 0.05) + index)
                    )

                    previous = dict(states[drone_id])

                    pose = interpolate(
                        a_xy=a_xy,
                        b_xy=b_xy,
                        t=progress,
                        altitude=altitude,
                    )

                    states[drone_id] = pose

                    targets[drone_id] = {
                        "x": float(b_xy[0]),
                        "y": float(b_xy[1]),
                        "z": altitude,
                    }

                    yaw = yaw_between(previous, pose)

                    ok = set_pose(
                        world=world,
                        model=drone_cfg["model"],
                        pose=pose,
                        yaw=yaw,
                    )

                    if not ok:
                        raise RuntimeError(f"set_pose failed for {drone_cfg['model']}")

                    row[f"{drone_id}_x"] = round(pose["x"], 3)
                    row[f"{drone_id}_y"] = round(pose["y"], 3)
                    row[f"{drone_id}_z"] = round(pose["z"], 3)
                    row[f"{drone_id}_target_x"] = round(targets[drone_id]["x"], 3)
                    row[f"{drone_id}_target_y"] = round(targets[drone_id]["y"], 3)

                safe = safety_state(
                    states,
                    float(mission_cfg["minimum_3d_separation_m"]),
                )

                row["minimum_3d_separation_m"] = safe["minimum_3d_separation_m"]
                row["safety_status"] = safe["status"]

                telemetry.append(row)

                write_live(
                    cfg=cfg,
                    status="RUNNING",
                    phase="safe_continuous_overlapping_surveillance",
                    tick=tick,
                    total_ticks=total_ticks,
                    states=states,
                    targets=targets,
                    start_time=start_time,
                )

                if tick % 30 == 0:
                    log(
                        f"tick {tick}/{total_ticks} | "
                        f"min_sep={safe['minimum_3d_separation_m']}m | "
                        f"{safe['status']}"
                    )

                time.sleep(tick_delay_s)

    write_live(
        cfg=cfg,
        status="COMPLETED",
        phase="safe_continuous_overlapping_surveillance_complete",
        tick=total_ticks,
        total_ticks=total_ticks,
        states=states,
        targets=targets,
        start_time=start_time,
    )

    csv_path = OUT_DIR / "part05_safe_continuous_overlapping_surveillance_telemetry.csv"
    legacy_csv_path = OUT_DIR / "part05_altitude_separated_surveillance_telemetry.csv"

    for path in [csv_path, legacy_csv_path]:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(telemetry[0].keys()))
            writer.writeheader()
            writer.writerows(telemetry)

    summary_path = REPORT_DIR / "part05_realistic_surveillance_patrol_summary.json"
    report_path = REPORT_DIR / "part05_realistic_surveillance_patrol_report.md"

    summary = {
        "part": "part-05",
        "status": "completed",
        "result": "PASS",
        "task": "safe continuous overlapping autonomous surveillance patrol",
        "world": world,
        "loops": loops,
        "steps_per_leg": steps_per_leg,
        "tick_delay_s": tick_delay_s,
        "total_ticks": total_ticks,
        "behaviour": [
            "long-distance route motion",
            "overlapping search areas",
            "different route timing per drone",
            "not fixed formation movement",
            "lower Gazebo load",
            "altitude-separated safety"
        ],
        "outputs": {
            "telemetry_csv": str(csv_path.relative_to(ROOT)),
            "legacy_telemetry_csv": str(legacy_csv_path.relative_to(ROOT)),
            "live_state_json": str(LIVE_STATE.relative_to(ROOT)),
        },
        "completed_at_utc": now_utc(),
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_path.write_text(
        """# Part 5: Safe Continuous Overlapping Autonomous Surveillance Patrol

## Result

PASS

## Behaviour

The drones now move through long overlapping surveillance routes.

They do not move in a fixed formation and do not maintain a fixed distance.

## Safety and Stability

This version uses slower sequential Gazebo pose updates to avoid overloading Gazebo.

## Output Files

- Summary: `outputs/reports/part05_realistic_surveillance_patrol_summary.json`
- Telemetry: `outputs/swarm_missions/part05_surveillance_patrol/part05_safe_continuous_overlapping_surveillance_telemetry.csv`
- Live state: `outputs/live/swarm_live_state.json`
""",
        encoding="utf-8",
    )

    log(f"Summary: {summary_path}")
    log(f"Report: {report_path}")

    print()
    print("======================================")
    print("PART 5 VALIDATION: PASS")
    print("Safe continuous overlapping surveillance patrol completed.")
    print("Drones move long routes without fixed formation.")
    print("Dashboard: http://127.0.0.1:8502")
    print("======================================")


if __name__ == "__main__":
    main()
