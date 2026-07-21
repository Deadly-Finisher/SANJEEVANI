#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"
CONFIG_PATH="${1:-$PROJECT_ROOT/configs/safety/v1_swarm_inter_drone_collision.yaml}"

cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/.venv/bin/activate"

PYTHONPATH="$PROJECT_ROOT" python "$PROJECT_ROOT/swarm/safety/inter_drone_collision_monitor.py" --config "$CONFIG_PATH"
