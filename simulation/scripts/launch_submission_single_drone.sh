#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${SWARM_DRONES_ROOT:-$HOME/Programs/SWARM_DRONES}"
PX4_ROOT="${PX4_ROOT:-$HOME/Programs/PX4/PX4-Autopilot}"

PX4_BIN="$PX4_ROOT/build/px4_sitl_default/bin/px4"

WORLD_NAME="${WORLD_NAME:-battlefield_sar_world_v1_realistic}"
MODEL_NAME="${MODEL_NAME:-gz_x500_mono_cam}"
MODEL_POSE="${MODEL_POSE:--20,-35,0.3,0,0,0}"
AUTOSTART_ID="${AUTOSTART_ID:-4010}"

PX4_LOG="/tmp/px4_submission_single_drone.log"
PX4_PID_FILE="/tmp/px4_submission_single_drone.pid"

WORLD_CONTROL="/world/${WORLD_NAME}/control"

stop_old_runtime() {
    echo "Stopping old project processes..."

    pkill -9 -f \
        "run_one_swarm_drone" \
        2>/dev/null || true

    pkill -9 -f \
        "run_submission_single_drone" \
        2>/dev/null || true

    pkill -9 -f \
        "mavsdk_server" \
        2>/dev/null || true

    pkill -9 -f \
        "multi_model_yolo_ros_mjpeg_server.py" \
        2>/dev/null || true

    pkill -9 -f \
        "ros_gz_bridge" \
        2>/dev/null || true

    pkill -9 -f \
        "streamlit" \
        2>/dev/null || true

    pkill -9 -x px4 \
        2>/dev/null || true

    pkill -9 -f \
        "gz sim" \
        2>/dev/null || true

    pkill -9 -f \
        "gz gui" \
        2>/dev/null || true

    sleep 5
}

reset_instance_zero() {
    local rootfs

    rootfs="$PX4_ROOT/build/px4_sitl_default/rootfs/0"

    mkdir -p "$rootfs"

    rm -f \
        "$rootfs/parameters.bson" \
        "$rootfs/parameters_backup.bson" \
        "$rootfs/dataman"

    echo "PX4 instance 0 parameters reset."
}

build_px4() {
    echo "Building PX4 SITL..."

    cd "$PX4_ROOT"

    make px4_sitl
}

start_px4() {
    echo "Starting one PX4 drone..."

    rm -f \
        "$PX4_LOG" \
        "$PX4_PID_FILE"

    nohup setsid env \
        PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
        PX4_GZ_WORLD="$WORLD_NAME" \
        PX4_GZ_MODEL_POSE="$MODEL_POSE" \
        PX4_SIM_MODEL="$MODEL_NAME" \
        "$PX4_BIN" -i 0 \
        > "$PX4_LOG" 2>&1 < /dev/null &

    echo "$!" > "$PX4_PID_FILE"

    echo "PX4 PID: $(cat "$PX4_PID_FILE")"
}

wait_for_startup() {
    echo "Waiting for PX4 and Gazebo..."

    for attempt in $(seq 1 120); do
        local px4_ready=0
        local startup_ready=0
        local mavlink_ready=0
        local gazebo_ready=0

        if pgrep -x px4 >/dev/null 2>&1; then
            px4_ready=1
        fi

        if grep -q \
            "Startup script returned successfully" \
            "$PX4_LOG" \
            2>/dev/null
        then
            startup_ready=1
        fi

        if ss -lunH 2>/dev/null |
            awk '{print $4}' |
            grep -Eq ':14580$'
        then
            mavlink_ready=1
        fi

        if gz service -l 2>/dev/null |
            grep -Fxq "$WORLD_CONTROL"
        then
            gazebo_ready=1
        fi

        printf \
            "\rPX4=%s | startup=%s | MAVLink=%s | Gazebo=%s" \
            "$px4_ready" \
            "$startup_ready" \
            "$mavlink_ready" \
            "$gazebo_ready"

        if [[ "$px4_ready" -eq 1 ]] &&
            [[ "$startup_ready" -eq 1 ]] &&
            [[ "$mavlink_ready" -eq 1 ]] &&
            [[ "$gazebo_ready" -eq 1 ]]
        then
            echo
            return 0
        fi

        sleep 2
    done

    echo
    echo "ERROR: single-drone simulation did not become ready."

    tail -n 150 "$PX4_LOG" || true

    return 1
}

unpause_world() {
    gz service \
        -s "$WORLD_CONTROL" \
        --reqtype gz.msgs.WorldControl \
        --reptype gz.msgs.Boolean \
        --timeout 5000 \
        --req 'pause: false' \
        >/dev/null || true
}

validate_runtime() {
    echo
    echo "===== SINGLE-DRONE RUNTIME ====="

    local px4_count

    px4_count="$(
        pgrep -x px4 |
        wc -l |
        tr -d '[:space:]'
    )"

    echo "PX4 count: $px4_count"

    if [[ "$px4_count" -ne 1 ]]; then
        echo "ERROR: exactly one PX4 process is required."
        return 1
    fi

    if ! ss -lunH |
        awk '{print $4}' |
        grep -Eq ':14580$'
    then
        echo "ERROR: PX4 MAVLink port 14580 is missing."
        return 1
    fi

    echo "PX4 MAVLink 14580: PASS"

    if ! gz service -l |
        grep -Fxq "$WORLD_CONTROL"
    then
        echo "ERROR: Gazebo world service is missing."
        return 1
    fi

    echo "Gazebo world service: PASS"

    local camera_topic

    camera_topic="/world/${WORLD_NAME}/model/x500_mono_cam_0/link/camera_link/sensor/camera/image"

    if gz topic -l |
        grep -Fxq "$camera_topic"
    then
        echo "Gazebo camera topic: PASS"
    else
        echo "Gazebo camera topic: WARNING - not found yet"
    fi
}

stop_old_runtime
reset_instance_zero
build_px4
start_px4
wait_for_startup
unpause_world

echo "Waiting 20 seconds for sensors and estimator..."
sleep 20

validate_runtime

echo
echo "========================================"
echo "SINGLE-DRONE SIMULATION STARTED"
echo "========================================"
echo
echo "Model: x500_mono_cam_0"
echo "PX4 instance: 0"
echo "PX4 system ID: 1"
echo "PX4 local MAVLink port: 14580"
echo "Mission input port: 14540"
echo "Log: $PX4_LOG"
echo
echo "PX4 and Gazebo are detached."
