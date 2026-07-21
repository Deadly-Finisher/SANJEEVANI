#!/usr/bin/env bash
set -Eeuo pipefail

cd "$HOME/Programs/SWARM_DRONES"

source .venv/bin/activate

mkdir -p /tmp/v1_swarm_logs

pkill -9 -f "streamlit run dashboard/v1_swarm_results_dashboard.py" 2>/dev/null || true

nohup setsid streamlit run dashboard/v1_swarm_results_dashboard.py \
  --server.port 8503 \
  --server.address 0.0.0.0 \
  > /tmp/v1_swarm_logs/results_dashboard.log \
  2>&1 < /dev/null &

echo $! > /tmp/v1_swarm_results_dashboard.pid

sleep 8

curl -s --max-time 5 -o /dev/null \
  -w "results dashboard: HTTP %{http_code}\n" \
  http://127.0.0.1:8503

echo "Open results dashboard: http://127.0.0.1:8503"
