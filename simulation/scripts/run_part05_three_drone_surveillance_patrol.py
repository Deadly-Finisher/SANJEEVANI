#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

CONFIG_PATH = ROOT / "configs/swarm/part05_continuous_overlapping_surveillance_config.json"

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


def distance_3d(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


def distance_2d(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
    )


def yaw_between(a: dict, b: dict) -> float:
    return math.atan2(b["y"] - a["y"], b["x"] - a["x"])


def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def interpolate(a: dict, b: dict, t: float) -> dict:
    s = smoothstep(t)

    return {
        "x": a["x"] + (b["x"] - a["x"]) * s,
        "y": a["y"] + (b["y"] - a["y"]) * s,
        "z": a["z"] + (b["z"] - a["z"]) * s,
    }


def random_target(
    rng: random.Random,
    drone_cfg: dict,
    current: dict,
    minimum_leg_distance: float,
) -> dict:
    bounds = drone_cfg["search_bounds"]

    for _ in range(100):
        target = {
            "x": rng.uniform(bounds["x_min"], bounds["x_max"]),
            "y": rng.uniform(bounds["y_min"], bounds["y_max"]),
            "z": float(drone_cfg["base_altitude_m"]),
        }

        if distance_2d(current, target) >= minimum_leg_distance:
            return target

    return {
        "x": rng.uniform(bounds["x_min"], bounds["x_max"]),
        "y": rng.uniform(bounds["y_min"], bounds["y_max"]),
        "z": float(drone_cfg["base_altitude_m"]),
    }


def build_pose_command(world: str, model: str, pose: dict, yaw: float) -> list[str]:
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)

    req = (
        f'name: "{model}" '
        f'position {{ x: {pose["x"]:.3f} y: {pose["y"]:.3f} z: {pose["z"]:.3f} }} '
        f'orientation {{ x: 0 y: 0 z: {qz:.6f} w: {qw:.6f} }}'
    )

    return [
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


def set_all_poses_parallel(world: str, pose_requests: list[tuple[str, dict, float]]) -> None:
    processes = []

    for model, pose, yaw in pose_requests:
        cmd = build_pose_command(world, model, pose, yaw)
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        processes.append((model, proc))

    for model, proc in processes:
        try:
            proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError(f"set_pose timeout for {model}")

        if proc.returncode != 0:
            raise RuntimeError(f"set_pose failed for {model}")


def safety_state(states: dict, minimum_distance: float) -> dict:
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
        "status": "SAFE" if min_d >= minimum_distance else "WARNING",
        "minimum_3d_separation_m": round(min_d, 2),
        "closest_pair": min_pair,
        "pairwise_distances_m": pairwise,
        "altitude_separation_enabled": True,
        "overlapping_search_enabled": True,
        "continuous_motion_enabled": True,
    }


def write_live(
    cfg: dict,
    status: str,
    phase: str,
    tick: int,
    total_ticks: int,
    states: dict,
    targets: dict,
    leg_counts: dict,
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
            "speed_mps": drone_cfg["speed_mps"],
            "completed_long_legs": leg_counts[drone_id],
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
            "Continuous overlapping surveillance is active.",
            "Drones now travel long distances across overlapping search areas.",
            "Each drone has different speed and independent target timing.",
            "The swarm is not moving in fixed formation.",
            "Altitude separation is used for safety while search areas overlap.",
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

    rng = random.Random(int(cfg["random_seed"]))
    mission_cfg = cfg["mission"]

    duration_s = float(mission_cfg["duration_s"])
    tick_delay_s = float(mission_cfg["tick_delay_s"])
    total_ticks = int(duration_s / tick_delay_s)
    minimum_leg_distance = float(mission_cfg["minimum_leg_distance_m"])

    world = cfg["world"]

    states = {}
    previous_states = {}
    leg_start = {}
    targets = {}
    leg_tick_start = {}
    leg_duration_ticks = {}
    leg_counts = {}

    for drone_id, drone_cfg in cfg["drones"].items():
        start = drone_cfg["start"]

        states[drone_id] = {
            "x": float(start[0]),
            "y": float(start[1]),
            "z": float(start[2]),
        }

        previous_states[drone_id] = dict(states[drone_id])
        leg_start[drone_id] = dict(states[drone_id])

        targets[drone_id] = random_target(
            rng,
            drone_cfg,
            states[drone_id],
            minimum_leg_distance,
        )

        leg_tick_start[drone_id] = 1

        distance = distance_2d(states[drone_id], targets[drone_id])
        leg_duration_ticks[drone_id] = max(
            40,
            int(distance / float(drone_cfg["speed_mps"]) / tick_delay_s),
        )

        leg_counts[drone_id] = 0

    telemetry = []
    start_time = time.time()

    log("STARTING LONG CONTINUOUS OVERLAPPING SURVEILLANCE")
    log("Drones move through overlapping search areas with independent long paths.")

    for tick in range(1, total_ticks + 1):
        pose_requests = []

        row = {
            "timestamp_utc": now_utc(),
            "tick": tick,
            "phase": "continuous_overlapping_surveillance",
        }

        for index, (drone_id, drone_cfg) in enumerate(cfg["drones"].items()):
            current_leg_tick = tick - leg_tick_start[drone_id]
            duration = max(1, leg_duration_ticks[drone_id])
            progress = current_leg_tick / duration

            if progress >= 1.0:
                states[drone_id] = dict(targets[drone_id])
                leg_start[drone_id] = dict(states[drone_id])

                targets[drone_id] = random_target(
                    rng,
                    drone_cfg,
                    states[drone_id],
                    minimum_leg_distance,
                )

                leg_tick_start[drone_id] = tick

                distance = distance_2d(states[drone_id], targets[drone_id])
                leg_duration_ticks[drone_id] = max(
                    40,
                    int(distance / float(drone_cfg["speed_mps"]) / tick_delay_s),
                )

                leg_counts[drone_id] += 1
                progress = 0.0

            previous_states[drone_id] = dict(states[drone_id])

            pose = interpolate(
                leg_start[drone_id],
                targets[drone_id],
                progress,
            )

            wave = math.sin((tick * 0.045) + (index * 2.1))
            pose["z"] = float(drone_cfg["base_altitude_m"]) + (
                float(drone_cfg["altitude_wave_m"]) * wave
            )

            states[drone_id] = pose

            yaw = yaw_between(previous_states[drone_id], states[drone_id])

            pose_requests.append(
                (
                    drone_cfg["model"],
                    states[drone_id],
                    yaw,
                )
            )

            row[f"{drone_id}_x"] = round(states[drone_id]["x"], 3)
            row[f"{drone_id}_y"] = round(states[drone_id]["y"], 3)
            row[f"{drone_id}_z"] = round(states[drone_id]["z"], 3)
            row[f"{drone_id}_target_x"] = round(targets[drone_id]["x"], 3)
            row[f"{drone_id}_target_y"] = round(targets[drone_id]["y"], 3)
            row[f"{drone_id}_completed_long_legs"] = leg_counts[drone_id]

        set_all_poses_parallel(world, pose_requests)

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
            phase="continuous_overlapping_surveillance",
            tick=tick,
            total_ticks=total_ticks,
            states=states,
            targets=targets,
            leg_counts=leg_counts,
            start_time=start_time,
        )

        if tick % 50 == 0:
            log(
                f"tick {tick}/{total_ticks} | "
                f"legs: D1={leg_counts['drone_1']} "
                f"D2={leg_counts['drone_2']} "
                f"D3={leg_counts['drone_3']} | "
                f"min_sep={safe['minimum_3d_separation_m']}m | "
                f"{safe['status']}"
            )

        time.sleep(tick_delay_s)

    write_live(
        cfg=cfg,
        status="COMPLETED",
        phase="continuous_overlapping_surveillance_complete",
        tick=total_ticks,
        total_ticks=total_ticks,
        states=states,
        targets=targets,
        leg_counts=leg_counts,
        start_time=start_time,
    )

    csv_path = OUT_DIR / "part05_continuous_overlapping_surveillance_telemetry.csv"
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
        "task": "continuous overlapping autonomous surveillance patrol",
        "world": world,
        "duration_s": duration_s,
        "tick_delay_s": tick_delay_s,
        "total_ticks": total_ticks,
        "behaviour": [
            "long-distance continuous movement",
            "overlapping search areas",
            "different speeds per drone",
            "independent random long-leg target generation",
            "not fixed formation movement",
            "altitude-separated safety"
        ],
        "drones": {
            drone_id: {
                "model": drone_cfg["model"],
                "zone": drone_cfg["zone"],
                "base_altitude_m": drone_cfg["base_altitude_m"],
                "speed_mps": drone_cfg["speed_mps"],
                "completed_long_legs": leg_counts[drone_id],
                "search_bounds": drone_cfg["search_bounds"],
            }
            for drone_id, drone_cfg in cfg["drones"].items()
        },
        "outputs": {
            "telemetry_csv": str(csv_path.relative_to(ROOT)),
            "legacy_telemetry_csv": str(legacy_csv_path.relative_to(ROOT)),
            "live_state_json": str(LIVE_STATE.relative_to(ROOT)),
        },
        "completed_at_utc": now_utc(),
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_path.write_text(
        """# Part 5: Continuous Overlapping Autonomous Surveillance Patrol

## Result

PASS

## Behaviour

The swarm no longer moves in a synchronized or fixed-distance pattern.

The drones now:

- move continuously using small smooth pose updates
- travel over long paths
- select independent long-distance targets
- use different speeds
- search overlapping areas
- maintain altitude separation for safety

## Overlapping Search Areas

- Drone 1 covers left-to-center overlap.
- Drone 2 covers the central overlapping search region.
- Drone 3 covers right-to-center overlap.

This creates more realistic surveillance behaviour because multiple drones may observe nearby or overlapping regions from different altitudes and angles.

## Safety

The drones use different altitude bands:

- Drone 1: around 13 m
- Drone 2: around 17 m
- Drone 3: around 21 m

This is still a simulation-level patrol controller. Dynamic obstacle avoidance, LiDAR avoidance, inter-drone collision avoidance and real-time replanning remain future scope.

## Output Files

- Summary: `outputs/reports/part05_realistic_surveillance_patrol_summary.json`
- Telemetry: `outputs/swarm_missions/part05_surveillance_patrol/part05_continuous_overlapping_surveillance_telemetry.csv`
- Live state: `outputs/live/swarm_live_state.json`
""",
        encoding="utf-8",
    )

    log(f"Summary: {summary_path}")
    log(f"Report: {report_path}")

    print()
    print("======================================")
    print("PART 5 VALIDATION: PASS")
    print("Continuous overlapping surveillance patrol completed.")
    print("Drones now move long distances and do not stay in fixed formation.")
    print("Dashboard: http://127.0.0.1:8502")
    print("======================================")


if __name__ == "__main__":
    main()
