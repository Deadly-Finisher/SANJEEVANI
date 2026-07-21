#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${SWARM_DRONES_ROOT:-$HOME/Programs/SWARM_DRONES}"

PYTHON="$ROOT/.venv/bin/python"

RUNNER="$ROOT/simulation/scripts/run_one_swarm_drone_mavlink.py"

VALIDATOR="$ROOT/simulation/scripts/validate_v1_swarm_missions.py"

CONFIG="$ROOT/configs/swarm/v1_swarm_mission_execution.yaml"

RUN_DIR="$ROOT/outputs/swarm/v1_three_drone_swarm/mission_runs"

cd "$ROOT"

mkdir -p "$RUN_DIR"

MISSION_PIDS=()


cleanup() {
    for PID in "${MISSION_PIDS[@]:-}"; do
        kill "$PID" 2>/dev/null || true
    done

    pkill -9 -f \
        "mavsdk_server" \
        2>/dev/null || true
}


trap cleanup EXIT INT TERM


echo "===== PRE-OBSTACLE THREE-DRONE SWARM ====="
echo "Transport: direct Pymavlink per drone"
echo "MAVSDK backend: completely bypassed"
echo


pkill -9 -f \
    "run_one_swarm_drone_mission.py" \
    2>/dev/null || true

pkill -9 -f \
    "mavsdk_server" \
    2>/dev/null || true

sleep 3


PX4_COUNT="$(
    pgrep -x px4 2>/dev/null |
    wc -l |
    tr -d '[:space:]'
)"

PX4_COUNT="${PX4_COUNT:-0}"

echo "PX4 instances: $PX4_COUNT"

if (( PX4_COUNT != 3 )); then
    echo "ERROR: exactly three PX4 instances are required."
    exit 1
fi


CONTROL_SERVICE="$(
    gz service -l 2>/dev/null |
    grep -E '^/world/.+/control$' |
    head -n 1 ||
    true
)"

if [[ -z "$CONTROL_SERVICE" ]]; then
    echo "ERROR: Gazebo control service was not found."
    exit 1
fi


echo "Gazebo service: $CONTROL_SERVICE"

gz service \
    -s "$CONTROL_SERVICE" \
    --reqtype gz.msgs.WorldControl \
    --reptype gz.msgs.Boolean \
    --timeout 5000 \
    --req 'pause: false'


echo
echo "Waiting for PX4 sensors and EKF..."
sleep 30


if ss -ltnH 2>/dev/null |
    awk '{print $4}' |
    grep -Eq ':5010[1-3]$'
then
    echo "ERROR: MAVSDK gRPC ports are occupied."

    ss -ltnp |
    grep -E ':50101|:50102|:50103' \
    || true

    exit 1
fi


rm -f \
    "$RUN_DIR"/drone_{1,2,3}_console.log \
    "$RUN_DIR"/drone_{1,2,3}_mission_summary.json


start_mission() {
    local DRONE_ID="$1"

    echo "Starting $DRONE_ID mission..."

    PYTHONUNBUFFERED=1 \
    PYTHONPATH="$ROOT" \
    "$PYTHON" \
        "$RUNNER" \
        --execution-config "$CONFIG" \
        --drone-id "$DRONE_ID" \
        > "$RUN_DIR/${DRONE_ID}_console.log" \
        2>&1 &

    MISSION_PIDS+=("$!")
}


start_mission drone_1
start_mission drone_2
start_mission drone_3


echo
echo "Mission processes:"
echo "drone_1: ${MISSION_PIDS[0]}"
echo "drone_2: ${MISSION_PIDS[1]}"
echo "drone_3: ${MISSION_PIDS[2]}"
echo


set +e

wait "${MISSION_PIDS[0]}"
EXIT_1=$?

wait "${MISSION_PIDS[1]}"
EXIT_2=$?

wait "${MISSION_PIDS[2]}"
EXIT_3=$?

set -e


echo
echo "===== PROCESS RESULTS ====="
echo "drone_1: $EXIT_1"
echo "drone_2: $EXIT_2"
echo "drone_3: $EXIT_3"
echo


if ! "$PYTHON" "$VALIDATOR"; then
    echo

    for DRONE_ID in \
        drone_1 \
        drone_2 \
        drone_3
    do
        echo "===== ${DRONE_ID^^} LOG ====="

        tail -n 120 \
            "$RUN_DIR/${DRONE_ID}_console.log" \
            || true

        echo
    done

    echo "===== PX4 LOG TAILS ====="

    tail -n 80 \
        /tmp/px4_drone_1.log \
        /tmp/px4_drone_2.log \
        /tmp/px4_drone_3.log \
        2>/dev/null || true

    exit 1
fi


echo
echo "SUCCESS: all three drones completed every waypoint."
