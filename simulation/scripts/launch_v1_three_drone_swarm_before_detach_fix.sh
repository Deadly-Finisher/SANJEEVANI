#!/usr/bin/env bash
set -e

PX4_ROOT="$HOME/Programs/PX4/PX4-Autopilot"
WORLD_NAME="battlefield_sar_world_v1_realistic"
MODEL_NAME="gz_x500_mono_cam"
AUTOSTART_ID=4010

echo "Stopping old PX4/Gazebo/MAVSDK processes..."
pkill -9 -f "gz sim" || true
pkill -9 -f "gz gui" || true
pkill -9 -f "gz server" || true
pkill -9 -f "px4" || true
pkill -9 -f "mavsdk_server" || true

cd "$PX4_ROOT"

echo "Building PX4 SITL if needed..."
make px4_sitl

echo "Launching drone 1..."
PX4_GZ_WORLD="$WORLD_NAME" \
PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
PX4_GZ_MODEL_POSE="-20,-35,0.3,0,0,0" \
PX4_SIM_MODEL="$MODEL_NAME" \
./build/px4_sitl_default/bin/px4 -i 1 > /tmp/px4_drone_1.log 2>&1 &

sleep 8

echo "Launching drone 2..."
PX4_GZ_STANDALONE=1 \
PX4_GZ_WORLD="$WORLD_NAME" \
PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
PX4_GZ_MODEL_POSE="0,-35,0.3,0,0,0" \
PX4_SIM_MODEL="$MODEL_NAME" \
./build/px4_sitl_default/bin/px4 -i 2 > /tmp/px4_drone_2.log 2>&1 &

sleep 5

echo "Launching drone 3..."
PX4_GZ_STANDALONE=1 \
PX4_GZ_WORLD="$WORLD_NAME" \
PX4_SYS_AUTOSTART="$AUTOSTART_ID" \
PX4_GZ_MODEL_POSE="20,-35,0.3,0,0,0" \
PX4_SIM_MODEL="$MODEL_NAME" \
./build/px4_sitl_default/bin/px4 -i 3 > /tmp/px4_drone_3.log 2>&1 &

echo ""
echo "Three-drone swarm launch command completed."
echo "Logs:"
echo "  /tmp/px4_drone_1.log"
echo "  /tmp/px4_drone_2.log"
echo "  /tmp/px4_drone_3.log"
echo ""
echo "Keep this terminal open."
echo "Press Ctrl+C later when you want to stop watching logs."
echo ""

tail -f /tmp/px4_drone_1.log /tmp/px4_drone_2.log /tmp/px4_drone_3.log
