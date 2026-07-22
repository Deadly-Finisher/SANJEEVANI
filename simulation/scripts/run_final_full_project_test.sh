#!/usr/bin/env bash
set -Eeuo pipefail

cd "$HOME/Programs/SWARM_DRONES"
source .venv/bin/activate

mkdir -p outputs/reports /tmp/v1_swarm_logs

echo "========================================"
echo "FINAL FULL PROJECT TEST"
echo "========================================"

fail() {
    echo
    echo "FINAL TEST FAILED: $1"
    echo
    echo "===== LIVE DASHBOARD LOG ====="
    tail -n 80 /tmp/v1_swarm_logs/live_dashboard.log 2>/dev/null || true
    echo
    echo "===== RESULTS DASHBOARD LOG ====="
    tail -n 80 /tmp/v1_swarm_logs/results_dashboard.log 2>/dev/null || true
    exit 1
}

check_http() {
    NAME="$1"
    URL="$2"

    CODE="$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "$URL" || true)"
    echo "$NAME: HTTP $CODE"

    if [ "$CODE" != "200" ]; then
        fail "$NAME not reachable at $URL"
    fi
}

check_pass() {
    NAME="$1"
    FILE="$2"

    python - "$NAME" "$FILE" <<'PY'
import json
import sys
from pathlib import Path

name = sys.argv[1]
path = Path(sys.argv[2])

if not path.exists():
    raise SystemExit(f"{name}: missing file {path}")

data = json.loads(path.read_text(encoding="utf-8"))

if data.get("result") != "PASS":
    raise SystemExit(f"{name}: result not PASS -> {data.get('result')}")

print(f"{name}: PASS")
PY
}

echo
echo "===== 1. STOP OLD PROCESSES ====="
pkill -9 -f "multi_model_yolo_ros_mjpeg_server.py" 2>/dev/null || true
pkill -9 -f "single_drone_yolo_mjpeg_server.py" 2>/dev/null || true
pkill -9 -f "streamlit run dashboard/v1_swarm_live_dashboard.py" 2>/dev/null || true
pkill -9 -f "streamlit run dashboard/v1_swarm_results_dashboard.py" 2>/dev/null || true
pkill -9 -f "parameter_bridge.*x500_mono_cam" 2>/dev/null || true
fuser -k 8502/tcp 2>/dev/null || true
fuser -k 8503/tcp 2>/dev/null || true

echo
echo "===== 2. LAUNCH THREE-DRONE GAZEBO SIMULATION ====="
bash simulation/scripts/launch_v1_three_drone_swarm.sh

sleep 18

PX4_COUNT="$(pgrep -x px4 | wc -l)"
echo "PX4 count: $PX4_COUNT"

if [ "$PX4_COUNT" != "3" ]; then
    fail "Expected 3 PX4 processes, found $PX4_COUNT"
fi

MODEL_COUNT="$(gz model --list 2>/dev/null | grep -c "x500_mono_cam" || true)"
echo "Gazebo x500 model count: $MODEL_COUNT"

if [ "$MODEL_COUNT" -lt 3 ]; then
    fail "Expected 3 Gazebo drone models"
fi

echo
echo "===== 3. START CAMERA BRIDGE ====="
nohup setsid bash simulation/scripts/bridge_v1_swarm_cameras.sh \
> /tmp/v1_swarm_logs/camera_bridge.log \
2>&1 < /dev/null &

sleep 10

echo
echo "===== 4. START CAMERA SERVERS ====="
find /tmp -maxdepth 3 -type f \
\( -iname "*camera*.pid" -o -iname "*yolo*.pid" -o -iname "*drone*server*.pid" \) \
-print -delete 2>/dev/null || true

bash simulation/scripts/manage_v1_three_drone_camera_servers.sh start \
|| bash simulation/scripts/manage_v1_three_drone_camera_servers.sh restart \
|| bash simulation/scripts/manage_v1_three_drone_camera_servers.sh

sleep 15

echo
echo "===== 5. VERIFY CAMERA FEEDS ====="
check_http "Drone 1 feed" "http://127.0.0.1:5011/"
check_http "Drone 2 feed" "http://127.0.0.1:5012/"
check_http "Drone 3 feed" "http://127.0.0.1:5013/"

echo
echo "===== 6. START LIVE DASHBOARD BEFORE MISSION ====="
nohup setsid streamlit run dashboard/v1_swarm_live_dashboard.py \
--server.port 8502 \
--server.address 0.0.0.0 \
--server.headless true \
--server.fileWatcherType none \
--browser.gatherUsageStats false \
> /tmp/v1_swarm_logs/live_dashboard.log \
2>&1 < /dev/null &

sleep 8

check_http "Live dashboard" "http://127.0.0.1:8502"

echo
echo "Live dashboard ready before mission:"
echo "http://127.0.0.1:8502"

echo
echo "===== 7. RUN PART 5: SURVEILLANCE PATROL ====="
python simulation/scripts/run_part05_three_drone_surveillance_patrol.py

echo
echo "===== 8. RUN PART 6: ZONE ASSIGNMENT ====="
python simulation/scripts/run_part06_zone_assignment.py

echo
echo "===== 9. RUN PART 8: EVENT SHARING ====="
python simulation/scripts/run_part08_swarm_event_sharing.py

echo
echo "===== 10. RUN PART 9: INTELLIGENCE FUSION ====="
python simulation/scripts/run_part09_battlefield_intelligence_fusion.py

echo
echo "===== 11. RUN PART 11: FAILURE RECOVERY ====="
python simulation/scripts/run_part11_failure_recovery.py

echo
echo "===== 12. RUN PART 12: RAG / VLM / HITL ====="
python simulation/scripts/run_part12_rag_vlm_hitl_analysis.py

echo
echo "===== 13. VERIFY ALL MODULES ====="
check_pass "Part 5" "outputs/reports/part05_realistic_surveillance_patrol_summary.json"
check_pass "Part 6" "outputs/reports/part06_zone_assignment_summary.json"
check_pass "Part 8" "outputs/reports/part08_swarm_event_sharing_summary.json"
check_pass "Part 9" "outputs/reports/part09_battlefield_intelligence_fusion_summary.json"
check_pass "Part 11" "outputs/reports/part11_failure_recovery_summary.json"
check_pass "Part 12" "outputs/reports/part12_rag_vlm_hitl_summary.json"

echo
echo "===== 14. START RESULTS DASHBOARD AFTER MISSION ====="
bash simulation/scripts/run_part10_results_dashboard.sh

sleep 5

check_http "Results dashboard" "http://127.0.0.1:8503"

echo
echo "===== 15. CREATE FINAL TEST SUMMARY ====="
python - <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess

root = Path.home() / "Programs" / "SWARM_DRONES"

def load_json(rel):
    return json.loads((root / rel).read_text(encoding="utf-8"))

def http_code(url):
    result = subprocess.run(
        f"curl -s --max-time 5 -o /dev/null -w '%{{http_code}}' {url}",
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()

def csv_rows(rel):
    path = root / rel
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)

part05 = load_json("outputs/reports/part05_realistic_surveillance_patrol_summary.json")
part06 = load_json("outputs/reports/part06_zone_assignment_summary.json")
part08 = load_json("outputs/reports/part08_swarm_event_sharing_summary.json")
part09 = load_json("outputs/reports/part09_battlefield_intelligence_fusion_summary.json")
part11 = load_json("outputs/reports/part11_failure_recovery_summary.json")
part12 = load_json("outputs/reports/part12_rag_vlm_hitl_summary.json")
live = load_json("outputs/live/swarm_live_state.json")

summary = {
    "test_name": "final_full_project_test",
    "status": "completed",
    "result": "PASS",
    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    "modules": {
        "part05_surveillance_patrol": part05.get("result"),
        "part06_zone_assignment": part06.get("result"),
        "part08_event_sharing": part08.get("result"),
        "part09_intelligence_fusion": part09.get("result"),
        "part11_failure_recovery": part11.get("result"),
        "part12_rag_vlm_hitl": part12.get("result")
    },
    "runtime": {
        "drone_1_feed": http_code("http://127.0.0.1:5011/"),
        "drone_2_feed": http_code("http://127.0.0.1:5012/"),
        "drone_3_feed": http_code("http://127.0.0.1:5013/"),
        "live_dashboard": http_code("http://127.0.0.1:8502/"),
        "results_dashboard": http_code("http://127.0.0.1:8503/")
    },
    "mission_outputs": {
        "patrol_telemetry_rows": csv_rows("outputs/swarm_missions/part05_surveillance_patrol/part05_altitude_separated_surveillance_telemetry.csv"),
        "raw_events": part08.get("raw_event_count"),
        "shared_events": part08.get("shared_event_count"),
        "deduplicated_events": part08.get("deduplicated_event_count"),
        "overall_risk": part09.get("overall_risk_level"),
        "failure_recovery_status": part11.get("recovery_status"),
        "uncertainty_status": part12.get("uncertainty_status"),
        "human_review_required": part12.get("human_review_required"),
        "final_mission_status": live.get("mission", {}).get("status"),
        "safety_status": live.get("safety", {}).get("status"),
        "minimum_3d_separation_m": live.get("safety", {}).get("minimum_3d_separation_m")
    },
    "operator_urls": {
        "live_dashboard": "http://127.0.0.1:8502",
        "results_dashboard": "http://127.0.0.1:8503",
        "drone_1_feed": "http://127.0.0.1:5011/video_feed",
        "drone_2_feed": "http://127.0.0.1:5012/video_feed",
        "drone_3_feed": "http://127.0.0.1:5013/video_feed"
    }
}

out_json = root / "outputs/reports/final_full_project_test_summary.json"
out_md = root / "outputs/reports/final_full_project_test_report.md"

out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

lines = [
    "# Final Full Project Test Report",
    "",
    "## Result",
    "",
    "PASS",
    "",
    "## Modules",
    "",
]

for key, value in summary["modules"].items():
    lines.append(f"- {key}: {value}")

lines += ["", "## Runtime", ""]

for key, value in summary["runtime"].items():
    lines.append(f"- {key}: HTTP {value}")

lines += ["", "## Mission Outputs", ""]

for key, value in summary["mission_outputs"].items():
    lines.append(f"- {key}: {value}")

lines += [
    "",
    "## Dashboards",
    "",
    "- Live dashboard: http://127.0.0.1:8502",
    "- Results dashboard: http://127.0.0.1:8503",
]

out_md.write_text("\n".join(lines), encoding="utf-8")

print("Final summary:", out_json)
print("Final report:", out_md)
PY

echo
echo "========================================"
echo "FINAL FULL PROJECT TEST: PASS"
echo "Live dashboard:    http://127.0.0.1:8502"
echo "Results dashboard: http://127.0.0.1:8503"
echo "========================================"
