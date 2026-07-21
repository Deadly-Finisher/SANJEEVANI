#!/usr/bin/env bash
set -Eeuo pipefail

cd "$HOME/Programs/SWARM_DRONES"

source /opt/ros/humble/setup.bash
source .venv/bin/activate

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

TOPIC="/world/battlefield_sar_world_v1_realistic/model/x500_mono_cam_0/link/camera_link/sensor/camera/image"

python perception/single_drone/single_drone_yolo_mjpeg_server.py \
  --topic "$TOPIC" \
  --model yolo11n.pt \
  --port 5021 \
  --output-csv outputs/single_drone/detections/part02_single_drone_detections.csv \
  --confidence 0.25 \
  --inference-every-n-frames 6 \
  --jpeg-quality 75
