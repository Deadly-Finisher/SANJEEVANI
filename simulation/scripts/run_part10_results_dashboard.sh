#!/usr/bin/env bash
set -Eeuo pipefail

cd "$HOME/Programs/SWARM_DRONES"
source .venv/bin/activate

mkdir -p /tmp/v1_swarm_logs

echo "===== STOP OLD RESULTS DASHBOARD ====="
pkill -9 -f "streamlit run dashboard/v1_swarm_results_dashboard.py" 2>/dev/null || true
fuser -k 8503/tcp 2>/dev/null || true

sleep 2

echo "===== START RESULTS DASHBOARD ON 8503 ====="

nohup setsid streamlit run dashboard/v1_swarm_results_dashboard.py \
  --server.port 8503 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false \
  > /tmp/v1_swarm_logs/results_dashboard.log \
  2>&1 < /dev/null &

echo $! > /tmp/v1_swarm_results_dashboard.pid

echo "Waiting for results dashboard..."

for i in $(seq 1 30); do
    CODE="$(curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8503 || true)"

    if [ "$CODE" = "200" ]; then
        echo "results dashboard: HTTP 200"
        echo "Open results dashboard: http://127.0.0.1:8503"
        exit 0
    fi

    sleep 2
done

echo "results dashboard: FAILED"
echo
echo "===== RESULTS DASHBOARD LOG ====="
tail -n 120 /tmp/v1_swarm_logs/results_dashboard.log || true
exit 1
