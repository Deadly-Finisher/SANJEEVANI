#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

cd "$PROJECT_ROOT"

RUNNER="simulation/scripts/run_one_swarm_drone_mission.py"
BACKUP_DIR="backups/obstacle_avoidance"
MISSION_FILE="configs/missions/swarm/drone_1_obstacle_validation.yaml"
EXECUTION_FILE="configs/swarm/v1_swarm_obstacle_validation_execution.yaml"

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$MISSION_FILE")"
mkdir -p "$(dirname "$EXECUTION_FILE")"

cp "$RUNNER" \
  "$BACKUP_DIR/run_one_swarm_drone_mission_before_validation_fix.py"

cat > "$MISSION_FILE" <<'YAML'
connection:
  system_address: udpin://0.0.0.0:14541

mission:
  mission_name: v1_drone_1_obstacle_validation
  takeoff_altitude_m: 2.5
  takeoff_wait_s: 5.0
  waypoint_command_interval_s: 0.2
  landing_wait_s: 10.0

logging:
  telemetry_csv_path: outputs/swarm/v1_three_drone_swarm/validation/drone_1_telemetry.csv
  sample_interval_s: 0.5

waypoints:
  - zone_name: validation_takeoff
    north_m: 0.0
    east_m: 0.0
    altitude_m: 2.5
    yaw_deg: 0.0
    hold_s: 2.0

  - zone_name: forward_clearance_check
    north_m: 3.0
    east_m: 0.0
    altitude_m: 3.0
    yaw_deg: 0.0
    hold_s: 3.0

  - zone_name: lateral_clearance_check
    north_m: 3.0
    east_m: 3.0
    altitude_m: 3.0
    yaw_deg: 90.0
    hold_s: 3.0

  - zone_name: validation_return
    north_m: 0.0
    east_m: 0.0
    altitude_m: 2.5
    yaw_deg: 180.0
    hold_s: 2.0
YAML

cat > "$EXECUTION_FILE" <<'YAML'
swarm:
  name: v1_three_drone_swarm

execution:
  connection_timeout_s: 40
  health_timeout_s: 60
  position_timeout_s: 30
  command_retries: 3
  command_retry_delay_s: 2
  arrival_timeout_s: 120
  horizontal_tolerance_m: 1.5
  altitude_tolerance_m: 1.0
  arrival_check_interval_s: 0.5
  auto_land: true
  wait_for_health: false
  connection_stabilization_s: 2.0

output:
  run_log_dir: outputs/swarm/v1_three_drone_swarm/validation_runs

drones:
  - drone_id: drone_1
    mission_config: configs/missions/swarm/drone_1_obstacle_validation.yaml
    grpc_port: 50101
    startup_delay_s: 0
YAML

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

path = Path(
    "simulation/scripts/run_one_swarm_drone_mission.py"
)
text = path.read_text()

if "import inspect\n" not in text:
    if "import asyncio\n" not in text:
        raise SystemExit(
            "Could not find 'import asyncio' in mission runner."
        )

    text = text.replace(
        "import asyncio\n",
        "import asyncio\nimport inspect\n",
        1,
    )

waypoint_block = '''            summary["completed_waypoints"].append({
                "sequence_id": sequence_id,
                "zone_name": zone_name,
                "arrived_within_tolerance": arrived,
            })

            await safety_aware_wait(
'''

waypoint_replacement = '''            summary["completed_waypoints"].append({
                "sequence_id": sequence_id,
                "zone_name": zone_name,
                "arrived_within_tolerance": arrived,
            })

            if not arrived:
                summary["failed_waypoint"] = {
                    "sequence_id": sequence_id,
                    "zone_name": zone_name,
                    "reason": "arrival_timeout",
                }

                raise RuntimeError(
                    f"Waypoint {sequence_id} ({zone_name}) "
                    "was not reached within the configured tolerance "
                    "and timeout."
                )

            await safety_aware_wait(
'''

if waypoint_replacement not in text:
    if waypoint_block not in text:
        raise SystemExit(
            "Waypoint result block was not found. "
            "The runner was not modified."
        )

    text = text.replace(
        waypoint_block,
        waypoint_replacement,
        1,
    )

text = text.replace(
    'print(f"[{drone_id}] arrival timeout; continuing mission")',
    'print(f"[{drone_id}] arrival timeout; aborting mission")',
)

text = text.replace(
    'summary["status"] = "completed_with_errors"',
    'summary["status"] = "failed"',
)

helper = '''async def shutdown_mavsdk_system(drone, drone_id):
    # Stop only this mission's embedded MAVSDK server.
    if drone is None:
        return

    stop_method = getattr(
        drone,
        "_stop_mavsdk_server",
        None,
    )

    if callable(stop_method):
        try:
            result = stop_method()

            if inspect.isawaitable(result):
                await result

        except Exception as error:
            print(
                f"[{drone_id}] MAVSDK stop method warning: "
                f"{error}"
            )

    process = getattr(
        drone,
        "_mavsdk_server_process",
        None,
    )

    if (
        process is not None
        and getattr(process, "returncode", None) is None
    ):
        try:
            process.terminate()

            await asyncio.wait_for(
                process.wait(),
                timeout=3.0,
            )

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

        except ProcessLookupError:
            pass

    print(
        f"[{drone_id}] embedded MAVSDK server stopped"
    )


'''

if "async def shutdown_mavsdk_system(" not in text:
    marker = '\nif __name__ == "__main__":\n'

    if marker not in text:
        raise SystemExit(
            "Could not find the runner entry-point marker."
        )

    text = text.replace(
        marker,
        "\n" + helper + marker,
        1,
    )

cleanup_block = '''        if safety_guard is not None:
            safety_guard.close()

        summary_path.write_text(json.dumps(summary, indent=2))
'''

cleanup_replacement = '''        if safety_guard is not None:
            safety_guard.close()

        await shutdown_mavsdk_system(
            drone,
            drone_id,
        )

        summary_path.write_text(json.dumps(summary, indent=2))
'''

if cleanup_replacement not in text:
    if cleanup_block not in text:
        raise SystemExit(
            "Finally cleanup block was not found."
        )

    text = text.replace(
        cleanup_block,
        cleanup_replacement,
        1,
    )

path.write_text(text)

print("Mission timeout now aborts and reports failure.")
print("Per-mission MAVSDK shutdown was added.")
PY

mkdir -p \
  outputs/swarm/v1_three_drone_swarm/validation \
  outputs/swarm/v1_three_drone_swarm/validation_runs

"$PYTHON_BIN" -m py_compile "$RUNNER"

echo
echo "===== VALIDATION MISSION ====="
cat "$MISSION_FILE"

echo
echo "===== VALIDATION EXECUTION ====="
cat "$EXECUTION_FILE"

echo
echo "===== PATCH CHECK ====="
grep -nE \
  "arrival timeout; aborting|failed_waypoint|summary.*failed|shutdown_mavsdk_system|embedded MAVSDK server stopped" \
  "$RUNNER"

echo
echo "Validation mission and status/shutdown fix applied successfully."
