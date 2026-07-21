#!/usr/bin/env bash
set -e

DRONE_ID="${1:-1}"

cd "$HOME/Programs/SWARM_DRONES"
source /opt/ros/humble/setup.bash
source .venv/bin/activate

CAM_TOPIC=$(gz topic -l | grep "/world/battlefield_sar_world_v1_realistic/model/x500_mono_cam_${DRONE_ID}/link/camera_link/sensor/camera/image" | head -n 1)

echo "Selected drone: x500_mono_cam_${DRONE_ID}"
echo "Camera topic: $CAM_TOPIC"

if [ -z "$CAM_TOPIC" ]; then
  echo "ERROR: Camera topic is empty."
  exit 1
fi

mkdir -p "outputs/swarm/camera_tests/drone_${DRONE_ID}/annotated_frames"
rm -f "outputs/swarm/camera_tests/drone_${DRONE_ID}/detections.csv"
rm -rf "outputs/swarm/camera_tests/drone_${DRONE_ID}/annotated_frames/"*

python - <<PY
from pathlib import Path
import yaml

drone_id = "$DRONE_ID"
topic = "$CAM_TOPIC"

path = Path("configs/perception/multi_model_yolo_ros_mjpeg_server.yaml")
config = yaml.safe_load(path.read_text())

config["input"]["ros_image_topic"] = topic
config["output"]["csv_path"] = f"outputs/swarm/camera_tests/drone_{drone_id}/detections.csv"
config["output"]["annotated_frame_dir"] = f"outputs/swarm/camera_tests/drone_{drone_id}/annotated_frames"
config["output"]["save_annotated_frames"] = True
config["output"]["save_every_n_frames"] = 5

path.write_text(yaml.safe_dump(config, sort_keys=False))

print("YOLO will use:", topic)
print("Output CSV:", config["output"]["csv_path"])
PY

python perception/inference/multi_model_yolo_ros_mjpeg_server.py
