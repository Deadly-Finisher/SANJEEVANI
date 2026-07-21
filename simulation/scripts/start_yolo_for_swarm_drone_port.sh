#!/usr/bin/env bash
set -eo pipefail

DRONE_NUMBER="${1:-}"

if [[ ! "$DRONE_NUMBER" =~ ^[123]$ ]]; then
    echo "Usage: $0 <1|2|3>"
    exit 1
fi

PROJECT_ROOT="${SWARM_DRONES_ROOT:-$HOME/Programs/SWARM_DRONES}"
DRONE_ID="drone_${DRONE_NUMBER}"
PORT="$((5010 + DRONE_NUMBER))"

CONFIG_PATH="$PROJECT_ROOT/configs/perception/swarm/${DRONE_ID}_camera_server.yaml"

CAMERA_TOPIC="/world/battlefield_sar_world_v1_realistic/model/x500_mono_cam_${DRONE_NUMBER}/link/camera_link/sensor/camera/image"

cd "$PROJECT_ROOT"

set +u
source /opt/ros/humble/setup.bash
source "$PROJECT_ROOT/.venv/bin/activate"
set -u

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "ERROR: Missing configuration:"
    echo "$CONFIG_PATH"
    exit 1
fi

GZ_TOPICS="$(gz topic -l)"

if ! grep -Fxq "$CAMERA_TOPIC" <<< "$GZ_TOPICS"; then
    echo "ERROR: Gazebo camera topic missing:"
    echo "$CAMERA_TOPIC"
    echo
    echo "Available drone camera topics:"
    grep -E "x500_mono_cam_[123].*/camera/image" \
        <<< "$GZ_TOPICS" || true
    exit 1
fi

mkdir -p \
"$PROJECT_ROOT/outputs/swarm/camera_tests/${DRONE_ID}/annotated_frames"

export SWARM_YOLO_CONFIG="$CONFIG_PATH"
export SWARM_YOLO_NODE_NAME="multi_model_yolo_${DRONE_ID}"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

echo "Starting ${DRONE_ID}"
echo "Topic: $CAMERA_TOPIC"
echo "Configuration: $CONFIG_PATH"
echo "Feed: http://127.0.0.1:${PORT}/video_feed"

exec nice -n 10 python \
"$PROJECT_ROOT/perception/inference/multi_model_yolo_ros_mjpeg_server.py"
