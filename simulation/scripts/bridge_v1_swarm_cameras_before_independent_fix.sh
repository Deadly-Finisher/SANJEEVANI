#!/usr/bin/env bash
set -e

source /opt/ros/humble/setup.bash

mapfile -t CAM_TOPICS < <(gz topic -l | grep "/world/battlefield_sar_world_v1_realistic/model/x500_mono_cam_" | grep "/sensor/camera/image" | sort)

echo "Found camera topics:"
printf '%s\n' "${CAM_TOPICS[@]}"

if [ "${#CAM_TOPICS[@]}" -lt 3 ]; then
  echo "ERROR: Less than 3 drone camera topics found."
  exit 1
fi

ros2 run ros_gz_bridge parameter_bridge \
"${CAM_TOPICS[0]}@sensor_msgs/msg/Image@gz.msgs.Image" \
"${CAM_TOPICS[1]}@sensor_msgs/msg/Image@gz.msgs.Image" \
"${CAM_TOPICS[2]}@sensor_msgs/msg/Image@gz.msgs.Image"
