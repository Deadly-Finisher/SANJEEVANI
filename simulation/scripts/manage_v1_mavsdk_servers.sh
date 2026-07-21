#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/Programs/SWARM_DRONES}"

cd "$PROJECT_ROOT"
source .venv/bin/activate

python swarm/mavsdk/external_server_manager.py "$@"
