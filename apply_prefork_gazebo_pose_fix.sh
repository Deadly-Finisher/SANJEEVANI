#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"

cd "$PROJECT_ROOT"

mkdir -p backups/obstacle_avoidance

cp simulation/scripts/run_one_swarm_drone_mission.py \
  backups/obstacle_avoidance/run_one_swarm_drone_mission_before_prefork_pose_fix.py

cp swarm/safety/gazebo_pose_tracker.py \
  backups/obstacle_avoidance/gazebo_pose_tracker_before_prefork_pose_fix.py

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

tracker_path = Path("swarm/safety/gazebo_pose_tracker.py")
tracker_text = tracker_path.read_text()

old_run = '''    async def run(
        self,
        state: dict[str, Any],
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await self._stream_once(
                    state,
                    stop_event,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(
                    f"[{self.drone_id}] Gazebo pose "
                    f"stream error: {error}"
                )

            if not stop_event.is_set():
                await asyncio.sleep(
                    self.restart_delay_s
                )
'''

new_run = '''    async def run(
        self,
        state: dict[str, Any],
        stop_event: asyncio.Event,
    ) -> None:
        try:
            await self._stream_once(
                state,
                stop_event,
            )
        except asyncio.CancelledError:
            raise

        if not stop_event.is_set():
            raise RuntimeError(
                "Gazebo pose stream ended unexpectedly; "
                "automatic restart is disabled after MAVSDK starts "
                "to avoid unsafe fork operations inside gRPC."
            )
'''

if new_run not in tracker_text:
    if old_run not in tracker_text:
        raise SystemExit(
            "GazeboPoseTracker.run block not found. No changes made."
        )

    tracker_text = tracker_text.replace(
        old_run,
        new_run,
        1,
    )

tracker_path.write_text(tracker_text)


mission_path = Path(
    "simulation/scripts/run_one_swarm_drone_mission.py"
)
mission_text = mission_path.read_text()

old_startup = '''    try:
        print(f"[{drone_id}] starting MAVSDK connection")

        await drone.connect(system_address=system_address)

        await wait_connected(
            drone,
            drone_id,
            float(execution["connection_timeout_s"]),
        )

        print(
            f"[{drone_id}] stabilizing MAVSDK connection"
        )

        await asyncio.sleep(
            float(execution["connection_stabilization_s"])
        )

        print(
            f"[{drone_id}] MAVSDK telemetry disabled; "
            "using Gazebo pose tracking"
        )

        pose_tracker = GazeboPoseTracker(
            args.pose_config,
            drone_id,
        )

        position_task = asyncio.create_task(
            pose_tracker.run(
                state,
                stop_event,
            )
        )

        await wait_for_position(
            state,
            float(execution["position_timeout_s"]),
        )

        print(
            f"[{drone_id}] initial Gazebo pose received"
        )

        safety_guard = MissionSafetyGuard(
'''

new_startup = '''    try:
        print(
            f"[{drone_id}] starting Gazebo pose tracking "
            "before MAVSDK/gRPC"
        )

        pose_tracker = GazeboPoseTracker(
            args.pose_config,
            drone_id,
        )

        position_task = asyncio.create_task(
            pose_tracker.run(
                state,
                stop_event,
            )
        )

        await wait_for_position(
            state,
            float(execution["position_timeout_s"]),
        )

        print(
            f"[{drone_id}] initial Gazebo pose received"
        )

        print(f"[{drone_id}] starting MAVSDK connection")

        await drone.connect(system_address=system_address)

        await wait_connected(
            drone,
            drone_id,
            float(execution["connection_timeout_s"]),
        )

        print(
            f"[{drone_id}] stabilizing MAVSDK connection"
        )

        await asyncio.sleep(
            float(execution["connection_stabilization_s"])
        )

        print(
            f"[{drone_id}] MAVSDK telemetry disabled; "
            "Gazebo pose tracking already active"
        )

        safety_guard = MissionSafetyGuard(
'''

if new_startup not in mission_text:
    if old_startup not in mission_text:
        raise SystemExit(
            "Mission startup block not found. No changes made."
        )

    mission_text = mission_text.replace(
        old_startup,
        new_startup,
        1,
    )

mission_path.write_text(mission_text)

print("Gazebo pose process now starts before MAVSDK/gRPC.")
print("Automatic Gazebo pose subprocess restart is disabled.")
PY

"$PYTHON_BIN" -m py_compile \
  swarm/safety/gazebo_pose_tracker.py \
  swarm/safety/mission_safety_guard.py \
  simulation/scripts/run_one_swarm_drone_mission.py

echo
echo "===== STARTUP ORDER ====="
grep -nE \
  "starting Gazebo pose tracking|initial Gazebo pose received|starting MAVSDK connection|Gazebo pose tracking already active" \
  simulation/scripts/run_one_swarm_drone_mission.py

echo
echo "===== SUBPROCESS POLICY ====="
grep -nE \
  "automatic restart is disabled|async def run" \
  swarm/safety/gazebo_pose_tracker.py

echo
echo "Pre-fork Gazebo pose fix applied successfully."
