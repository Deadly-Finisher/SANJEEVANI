#!/usr/bin/env bash
set -Eeuo pipefail

WORLD_NAME="${WORLD_NAME:-battlefield_sar_world_v1_realistic}"

PID_DIR="/tmp/v1_swarm_camera_bridges"
LOG_DIR="/tmp/v1_swarm_camera_bridge_logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

set +u
source /opt/ros/humble/setup.bash
set -u


stop_old_bridges() {
    echo "Stopping old camera bridges..."

    for DRONE in 1 2 3; do
        PID_FILE="$PID_DIR/drone_${DRONE}.pid"

        if [[ -f "$PID_FILE" ]]; then
            PID="$(cat "$PID_FILE")"

            if kill -0 "$PID" 2>/dev/null; then
                kill -TERM -- "-$PID" 2>/dev/null \
                    || kill -TERM "$PID" 2>/dev/null \
                    || true
            fi
        fi
    done

    pkill -9 -f \
        "parameter_bridge.*x500_mono_cam_[123].*/sensor/camera/image" \
        2>/dev/null || true

    rm -f "$PID_DIR"/drone_*.pid

    sleep 3
}


gazebo_topic() {
    local DRONE="$1"

    echo \
"/world/${WORLD_NAME}/model/x500_mono_cam_${DRONE}/link/camera_link/sensor/camera/image"
}


wait_for_gazebo_topics() {
    echo "Waiting for all Gazebo camera topics..."

    for ATTEMPT in $(seq 1 60); do
        READY=0

        for DRONE in 1 2 3; do
            TOPIC="$(gazebo_topic "$DRONE")"

            if gz topic -l 2>/dev/null |
                grep -Fxq "$TOPIC"
            then
                READY=$((READY + 1))
            fi
        done

        printf "\rGazebo cameras ready: %s/3" "$READY"

        if [[ "$READY" -eq 3 ]]; then
            echo
            return 0
        fi

        sleep 2
    done

    echo
    echo "ERROR: all three Gazebo camera topics were not found."

    echo
    echo "Available camera topics:"

    gz topic -l 2>/dev/null |
        grep -E \
        "x500_mono_cam_[123].*/sensor/camera/image" \
        || true

    return 1
}


start_bridge() {
    local DRONE="$1"
    local TOPIC
    local LOG_FILE
    local PID_FILE

    TOPIC="$(gazebo_topic "$DRONE")"
    LOG_FILE="$LOG_DIR/drone_${DRONE}.log"
    PID_FILE="$PID_DIR/drone_${DRONE}.pid"

    rm -f "$LOG_FILE"

    echo "Starting Drone ${DRONE} camera bridge..."
    echo "Topic: $TOPIC"

    nohup setsid ros2 run ros_gz_bridge parameter_bridge \
        "${TOPIC}@sensor_msgs/msg/Image[gz.msgs.Image" \
        > "$LOG_FILE" 2>&1 < /dev/null &

    PID="$!"
    echo "$PID" > "$PID_FILE"

    for ATTEMPT in $(seq 1 30); do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "ERROR: Drone ${DRONE} bridge exited."

            cat "$LOG_FILE" || true
            return 1
        fi

        if ros2 topic list 2>/dev/null |
            grep -Fxq "$TOPIC"
        then
            echo \
"Drone ${DRONE}: ROS bridge READY | PID=$PID"
            return 0
        fi

        sleep 1
    done

    echo "ERROR: Drone ${DRONE} ROS topic did not appear."

    tail -n 80 "$LOG_FILE" || true
    return 1
}


stop_old_bridges
wait_for_gazebo_topics

for DRONE in 1 2 3; do
    start_bridge "$DRONE"
done

echo
echo "===== ROS CAMERA BRIDGE STATUS ====="

FAIL=0

for DRONE in 1 2 3; do
    TOPIC="$(gazebo_topic "$DRONE")"

    if ros2 topic list |
        grep -Fxq "$TOPIC"
    then
        echo "Drone ${DRONE}: PASS"
    else
        echo "Drone ${DRONE}: FAIL"
        FAIL=1
    fi
done

if [[ "$FAIL" -ne 0 ]]; then
    exit 1
fi

echo
echo "ALL THREE CAMERA BRIDGES ARE READY."
echo "Bridge processes are detached."
