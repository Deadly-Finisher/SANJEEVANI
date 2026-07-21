#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${SWARM_DRONES_ROOT:-$HOME/Programs/SWARM_DRONES}"
PORT="${SWARM_RESULTS_DASHBOARD_PORT:-8503}"

cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/.venv/bin/activate"

python -m streamlit run \
"$PROJECT_ROOT/dashboard/v1_swarm_results_dashboard.py" \
--server.port "$PORT"
