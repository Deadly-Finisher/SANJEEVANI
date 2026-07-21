#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
RUNNER="simulation/scripts/run_one_swarm_drone_mission.py"
BACKUP_DIR="backups/obstacle_avoidance"

cd "$PROJECT_ROOT"
mkdir -p "$BACKUP_DIR"

cp "$RUNNER" \
  "$BACKUP_DIR/run_one_swarm_drone_mission_before_goto_confirmation_fix.py"

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

path = Path(
    "simulation/scripts/run_one_swarm_drone_mission.py"
)
text = path.read_text()

old_goto = '''            await execute_with_retry(
                f"goto {zone_name}",
                lambda: drone.action.goto_location(
                    target_lat,
                    target_lon,
                    target_absolute_altitude,
                    float(waypoint["yaw_deg"]),
                ),
                retries,
                retry_delay_s,
                drone_id,
            )

            arrived = await wait_for_arrival(
'''

new_goto = '''            goto_command_error = None

            try:
                await execute_with_retry(
                    f"goto {zone_name}",
                    lambda: drone.action.goto_location(
                        target_lat,
                        target_lon,
                        target_absolute_altitude,
                        float(waypoint["yaw_deg"]),
                    ),
                    retries,
                    retry_delay_s,
                    drone_id,
                )
            except Exception as error:
                goto_command_error = str(error)

                print(
                    f"[{drone_id}] goto acknowledgement was "
                    f"not confirmed for {zone_name}; "
                    "checking Gazebo pose before declaring failure"
                )

            arrived = await wait_for_arrival(
'''

if new_goto not in text:
    if old_goto not in text:
        raise SystemExit(
            "Waypoint goto block was not found. No changes made."
        )

    text = text.replace(
        old_goto,
        new_goto,
        1,
    )

old_summary = '''            summary["completed_waypoints"].append({
                "sequence_id": sequence_id,
                "zone_name": zone_name,
                "arrived_within_tolerance": arrived,
            })
'''

new_summary = '''            summary["completed_waypoints"].append({
                "sequence_id": sequence_id,
                "zone_name": zone_name,
                "arrived_within_tolerance": arrived,
                "goto_command_error": goto_command_error,
            })
'''

if new_summary not in text:
    if old_summary not in text:
        raise SystemExit(
            "Waypoint summary block was not found. No changes made."
        )

    text = text.replace(
        old_summary,
        new_summary,
        1,
    )

old_failure = '''                raise RuntimeError(
                    f"Waypoint {sequence_id} ({zone_name}) "
                    "was not reached within the configured tolerance "
                    "and timeout."
                )
'''

new_failure = '''                command_context = (
                    f" Last goto error: {goto_command_error}"
                    if goto_command_error
                    else ""
                )

                raise RuntimeError(
                    f"Waypoint {sequence_id} ({zone_name}) "
                    "was not reached within the configured tolerance "
                    f"and timeout.{command_context}"
                )
'''

if new_failure not in text:
    if old_failure not in text:
        raise SystemExit(
            "Waypoint failure block was not found. No changes made."
        )

    text = text.replace(
        old_failure,
        new_failure,
        1,
    )

path.write_text(text)

print(
    "Goto RPC timeouts are now treated as unconfirmed "
    "acknowledgements and verified using Gazebo pose."
)
PY

"$PYTHON_BIN" -m py_compile "$RUNNER"

echo
echo "===== PATCH CHECK ====="
grep -nE \
  "goto_command_error|acknowledgement was|checking Gazebo pose|Last goto error" \
  "$RUNNER"

echo
echo "Goto arrival-confirmation fix applied successfully."
