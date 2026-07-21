#!/usr/bin/env bash
set -Eeuo pipefail

cd "$HOME/Programs/SWARM_DRONES"
source .venv/bin/activate

mkdir -p /tmp/v1_swarm_logs outputs/reports

echo "========================================"
echo "MAIN PROJECT RUN TILL NOW"
echo "Live dashboard starts BEFORE mission."
echo "Results dashboard starts AFTER mission."
echo "========================================"

echo
echo "===== STOP OLD DASHBOARD/CAMERA PROCESSES ====="
pkill -9 -f "multi_model_yolo_ros_mjpeg_server.py" 2>/dev/null || true
pkill -9 -f "single_drone_yolo_mjpeg_server.py" 2>/dev/null || true
pkill -9 -f "streamlit run dashboard/v1_swarm_live_dashboard.py" 2>/dev/null || true
pkill -9 -f "streamlit run dashboard/v1_swarm_results_dashboard.py" 2>/dev/null || true
pkill -9 -f "parameter_bridge.*x500_mono_cam" 2>/dev/null || true
fuser -k 8502/tcp 2>/dev/null || true
fuser -k 8503/tcp 2>/dev/null || true

echo
echo "===== LAUNCH 3-DRONE GAZEBO SIMULATION ====="
bash simulation/scripts/launch_v1_three_drone_swarm.sh

sleep 15

echo
echo "===== VERIFY SIMULATION ====="
echo "PX4 count: $(pgrep -x px4 | wc -l)"
gz model --list 2>/dev/null | grep x500 || true
gz topic -l | grep x500_mono_cam | grep camera_link | grep image || true

echo
echo "===== START CAMERA BRIDGE ====="
nohup setsid bash simulation/scripts/bridge_v1_swarm_cameras.sh \
> /tmp/v1_swarm_logs/camera_bridge.log \
2>&1 < /dev/null &

echo $! > /tmp/v1_swarm_camera_bridge.pid

sleep 10

echo
echo "===== START 3 YOLO CAMERA SERVERS ====="
find /tmp -maxdepth 3 -type f \
\( -iname "*camera*.pid" -o -iname "*yolo*.pid" -o -iname "*drone*server*.pid" \) \
-print -delete 2>/dev/null || true

bash simulation/scripts/manage_v1_three_drone_camera_servers.sh start \
|| bash simulation/scripts/manage_v1_three_drone_camera_servers.sh restart \
|| bash simulation/scripts/manage_v1_three_drone_camera_servers.sh

sleep 15

echo
echo "===== FEED CHECK BEFORE MISSION ====="
for PORT in 5011 5012 5013; do
    curl -s --max-time 5 -o /dev/null \
    -w "port ${PORT}: HTTP %{http_code}\n" \
    "http://127.0.0.1:${PORT}/"
done

echo
echo "===== START LIVE DASHBOARD BEFORE MISSION ====="
nohup setsid streamlit run dashboard/v1_swarm_live_dashboard.py \
--server.port 8502 \
--server.address 0.0.0.0 \
--server.headless true \
--server.fileWatcherType none \
--browser.gatherUsageStats false \
> /tmp/v1_swarm_logs/live_dashboard.log \
2>&1 < /dev/null &

echo $! > /tmp/v1_swarm_live_dashboard.pid

for i in $(seq 1 30); do
    CODE="$(curl -s --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8502 || true)"
    if [ "$CODE" = "200" ]; then
        echo "live dashboard: HTTP 200"
        echo "Open live dashboard now: http://127.0.0.1:8502"
        break
    fi
    sleep 2
done

echo
echo "===== IMPORTANT ====="
echo "Live dashboard is now available BEFORE mission."
echo "Keep this open while mission runs:"
echo "http://127.0.0.1:8502"
echo "Results dashboard is NOT started yet."
echo

sleep 5

echo
echo "===== RUN PART 5: SURVEILLANCE PATROL ====="
python simulation/scripts/run_part05_three_drone_surveillance_patrol.py

echo
echo "===== RUN PART 6: ZONE ASSIGNMENT ====="
python simulation/scripts/run_part06_zone_assignment.py

echo
echo "===== RUN PART 8: EVENT SHARING ====="
python simulation/scripts/run_part08_swarm_event_sharing.py

echo
echo "===== RUN PART 9: INTELLIGENCE FUSION ====="
python simulation/scripts/run_part09_battlefield_intelligence_fusion.py

echo
echo "===== CREATE MAIN RUN COMPARISON ====="
python - <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess

root = Path.home() / "Programs" / "SWARM_DRONES"

def load_json(rel, fallback):
    path = root / rel
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}

def count_csv_rows(rel):
    path = root / rel
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0

def http_code(port):
    result = subprocess.run(
        f"curl -s --max-time 5 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/",
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()

part05 = load_json("outputs/reports/part05_realistic_surveillance_patrol_summary.json", {})
part06 = load_json("outputs/reports/part06_zone_assignment_summary.json", {})
part08 = load_json("outputs/reports/part08_swarm_event_sharing_summary.json", {})
part09 = load_json("outputs/reports/part09_battlefield_intelligence_fusion_summary.json", {})
live_state = load_json("outputs/live/swarm_live_state.json", {})

current = {
    "part05_status": part05.get("status"),
    "part05_result": part05.get("result"),
    "part06_status": part06.get("status"),
    "part06_result": part06.get("result"),
    "part08_status": part08.get("status"),
    "part08_result": part08.get("result"),
    "part09_status": part09.get("status"),
    "part09_result": part09.get("result"),
    "patrol_telemetry_rows": count_csv_rows(
        "outputs/swarm_missions/part05_surveillance_patrol/part05_altitude_separated_surveillance_telemetry.csv"
    ),
    "raw_events": part08.get("raw_event_count"),
    "shared_events": part08.get("shared_event_count"),
    "deduplicated_events": part08.get("deduplicated_event_count"),
    "overall_risk": part09.get("overall_risk_level"),
    "threat_count": part09.get("threat_count"),
    "live_mission_status": live_state.get("mission", {}).get("status"),
    "live_mission_phase": live_state.get("mission", {}).get("phase"),
    "minimum_3d_separation_m": live_state.get("safety", {}).get("minimum_3d_separation_m"),
    "safety_status": live_state.get("safety", {}).get("status"),
    "feed_5011": http_code(5011),
    "feed_5012": http_code(5012),
    "feed_5013": http_code(5013),
    "live_dashboard_8502": http_code(8502),
    "results_dashboard_8503_before_start": http_code(8503),
}

checks = {
    "live_dashboard_started_before_mission": current["live_dashboard_8502"] == "200",
    "results_dashboard_not_required_before_mission": True,
    "three_feeds_ready": (
        current["feed_5011"] == "200"
        and current["feed_5012"] == "200"
        and current["feed_5013"] == "200"
    ),
    "patrol_completed": current["part05_result"] == "PASS",
    "zone_assignment_completed": current["part06_result"] == "PASS",
    "event_sharing_completed": current["part08_result"] == "PASS",
    "fusion_completed": current["part09_result"] == "PASS",
    "safety_ok": current["safety_status"] == "SAFE",
}

comparison = {
    "run_name": "main_project_till_now_end_to_end_run",
    "dashboard_flow": {
        "before_mission": "live_dashboard_only",
        "during_mission": "live_dashboard",
        "after_mission": "results_dashboard",
    },
    "status": "completed" if all(checks.values()) else "completed_with_warnings",
    "result": "PASS" if all(checks.values()) else "CHECK_WARNINGS",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "current_run": current,
    "validation_checks": checks,
    "operator_urls": {
        "live_dashboard": "http://127.0.0.1:8502",
        "results_dashboard": "http://127.0.0.1:8503",
        "drone_1_feed": "http://127.0.0.1:5011/video_feed",
        "drone_2_feed": "http://127.0.0.1:5012/video_feed",
        "drone_3_feed": "http://127.0.0.1:5013/video_feed",
    },
}

out_json = root / "outputs/reports/main_project_till_now_comparison.json"
out_md = root / "outputs/reports/main_project_till_now_comparison_report.md"

out_json.parent.mkdir(parents=True, exist_ok=True)
out_json.write_text(json.dumps(comparison, indent=2), encoding="utf-8")

lines = [
    "# Main Project End-to-End Run Comparison",
    "",
    f"- Result: {comparison['result']}",
    f"- Status: {comparison['status']}",
    f"- Created UTC: {comparison['created_at_utc']}",
    "",
    "## Dashboard Flow",
    "",
    "- Before mission: Live dashboard only",
    "- During mission: Live dashboard",
    "- After mission: Results dashboard",
    "",
    "## Current Run Metrics",
    "",
]

for key, value in current.items():
    lines.append(f"- {key}: {value}")

lines += [
    "",
    "## Validation Checks",
    "",
]

for key, value in checks.items():
    lines.append(f"- {key}: {'PASS' if value else 'WARN'}")

out_md.write_text("\n".join(lines), encoding="utf-8")

print("Comparison JSON:", out_json)
print("Comparison report:", out_md)
print("MAIN RUN RESULT:", comparison["result"])
PY

echo
echo "===== FULL MISSION DONE ====="
echo "Now starting results dashboard AFTER mission completion."

echo
echo "===== START RESULTS DASHBOARD AFTER MISSION ====="
bash simulation/scripts/run_part10_results_dashboard.sh

echo
echo "========================================"
echo "MAIN PROJECT RUN COMPLETE"
echo "Live dashboard was available before mission: http://127.0.0.1:8502"
echo "Results dashboard is available after mission: http://127.0.0.1:8503"
echo "========================================"
