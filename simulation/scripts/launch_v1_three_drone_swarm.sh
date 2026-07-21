#!/usr/bin/env bash
set -Eeuo pipefail

PX4_ROOT="${PX4_ROOT:-$HOME/Programs/PX4/PX4-Autopilot}"
PX4_BIN="$PX4_ROOT/build/px4_sitl_default/bin/px4"

WORLD_NAME="${WORLD_NAME:-battlefield_sar_world_v1_realistic}"
MODEL_NAME="${MODEL_NAME:-gz_x500_mono_cam}"
AUTOSTART_ID="${AUTOSTART_ID:-4010}"

WORLD_CONTROL="/world/${WORLD_NAME}/control"

stop_old_processes() {
    echo "Stopping old swarm processes..."

    pkill -9 -f "run_one_swarm_drone_mission.py" \
        2>/dev/null || true

    pkill -9 -x mavsdk_server \
        2>/dev/null || true

    pkill -9 -x px4 \
        2>/dev/null || true

    pkill -9 -f "gz sim" \
        2>/dev/null || true

    pkill -9 -f "gz gui" \
        2>/dev/null || true

    sleep 5

    rm -f \
        /tmp/v1_swarm_px4_1.pid \
        /tmp/v1_swarm_px4_2.pid \
        /tmp/v1_swarm_px4_3.pid
}

start_drone() {
    local INSTANCE="$1"
    local POSE="$2"
    local STANDALONE="$3"
    local LOG="/tmp/px4_drone_${INSTANCE}.log"
    local PID_FILE="/tmp/v1_swarm_px4_${INSTANCE}.pid"

    echo "Starting drone ${INSTANCE}..."

    rm -f "$LOG"

    if [[ "$STANDALONE" == "yes" ]]; then
        nohup setsid env \
            PX4_GZ_STANDALONE=1 \
            PX4_GZ_WORLD="$WORLD_NAME" \
            PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
            PX4_GZ_MODEL_POSE="$POSE" \
            PX4_SIM_MODEL="$MODEL_NAME" \
            "$PX4_BIN" -i "$INSTANCE" \
            > "$LOG" 2>&1 < /dev/null &
    else
        nohup setsid env \
            PX4_GZ_WORLD="$WORLD_NAME" \
            PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
            PX4_GZ_MODEL_POSE="$POSE" \
            PX4_SIM_MODEL="$MODEL_NAME" \
            "$PX4_BIN" -i "$INSTANCE" \
            > "$LOG" 2>&1 < /dev/null &
    fi

    echo "$!" > "$PID_FILE"

    echo \
        "Drone ${INSTANCE} PID: $(cat "$PID_FILE")"
}

wait_for_world() {
    echo "Waiting for Gazebo world service..."

    for ATTEMPT in $(seq 1 60); do
        if gz service -l 2>/dev/null |
            grep -Fxq "$WORLD_CONTROL"
        then
            echo "Gazebo world service ready."
            return 0
        fi

        sleep 2
    done

    echo "ERROR: Gazebo world did not start."

    tail -n 100 /tmp/px4_drone_1.log || true

    return 1
}

wait_for_swarm() {
    echo
    echo "Waiting for three PX4 instances..."

    for ATTEMPT in $(seq 1 90); do
        PX4_COUNT="$(
            pgrep -x px4 2>/dev/null |
            wc -l |
            tr -d '[:space:]'
        )"

        READY_LOGS=0

        for DRONE in 1 2 3; do
            if grep -q \
                "Startup script returned successfully" \
                "/tmp/px4_drone_${DRONE}.log" \
                2>/dev/null
            then
                READY_LOGS=$((READY_LOGS + 1))
            fi
        done

        PORTS_READY=0

        for PORT in 14581 14582 14583; do
            if ss -lunH 2>/dev/null |
                awk '{print $4}' |
                grep -Eq ":${PORT}$"
            then
                PORTS_READY=$((PORTS_READY + 1))
            fi
        done

        printf \
            "\rPX4=%s/3 | startup=%s/3 | MAVLink=%s/3" \
            "$PX4_COUNT" \
            "$READY_LOGS" \
            "$PORTS_READY"

        if [[ "$PX4_COUNT" == "3" ]] &&
            [[ "$READY_LOGS" == "3" ]] &&
            [[ "$PORTS_READY" == "3" ]]
        then
            echo
            return 0
        fi

        sleep 2
    done

    echo
    echo "ERROR: swarm did not become ready."

    return 1
}

show_failure_logs() {
    for DRONE in 1 2 3; do
        echo
        echo "===== DRONE ${DRONE} ====="

        tail -n 100 \
            "/tmp/px4_drone_${DRONE}.log" \
            || true
    done
}

cd "$PX4_ROOT"

stop_old_processes

echo "Building PX4 SITL..."
make px4_sitl

start_drone \
    1 \
    "-20,-35,0.3,0,0,0" \
    no

wait_for_world

sleep 5

start_drone \
    2 \
    "0,-35,0.3,0,0,0" \
    yes

sleep 5

start_drone \
    3 \
    "20,-35,0.3,0,0,0" \
    yes

if ! wait_for_swarm; then
    show_failure_logs
    exit 1
fi

gz service \
    -s "$WORLD_CONTROL" \
    --reqtype gz.msgs.WorldControl \
    --reptype gz.msgs.Boolean \
    --timeout 5000 \
    --req 'pause: false' \
    >/dev/null || true

echo
echo "========================================"
echo "THREE-DRONE SWARM SIMULATION READY"
echo "========================================"
echo
echo "PX4 and Gazebo are detached."
echo "Closing this terminal will not stop them."
echo
echo "Logs:"
echo "  /tmp/px4_drone_1.log"
echo "  /tmp/px4_drone_2.log"
echo "  /tmp/px4_drone_3.log"
