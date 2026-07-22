from pathlib import Path
import csv
import json
import streamlit as st


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

CONFIG_PATH = ROOT / "configs/dashboard/part10_results_dashboard_config.json"


st.set_page_config(
    page_title="V1 Swarm Final Results Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 V1 Swarm Final Results Dashboard")
st.caption("Battlefield Intelligence using Drone Swarms")


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


def load_csv(path: Path):
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


config = load_json(CONFIG_PATH, {"inputs": {}})
inputs = config.get("inputs", {})

part05 = load_json(ROOT / inputs.get("part05_summary", ""), {})
part06 = load_json(ROOT / inputs.get("part06_summary", ""), {})
part08 = load_json(ROOT / inputs.get("part08_summary", ""), {})
part09 = load_json(ROOT / inputs.get("part09_summary", ""), {})
fused = load_json(ROOT / inputs.get("part09_fused_intelligence", ""), {})
live_state = load_json(ROOT / inputs.get("live_state", ""), {})
comparison = load_json(ROOT / inputs.get("main_comparison", ""), {})
threat_table = load_csv(ROOT / inputs.get("part09_threat_table", ""))

part11 = load_json(ROOT / inputs.get("part11_summary", ""), {})
part11_plan = load_json(ROOT / inputs.get("part11_recovery_plan", ""), {})
part11_state = load_json(ROOT / inputs.get("part11_recovery_state", ""), {})


st.sidebar.header("Dashboard Links")
st.sidebar.write("Live dashboard: http://127.0.0.1:8502")
st.sidebar.write("Results dashboard: http://127.0.0.1:8503")
st.sidebar.write("Drone 1 feed: http://127.0.0.1:5011/video_feed")
st.sidebar.write("Drone 2 feed: http://127.0.0.1:5012/video_feed")
st.sidebar.write("Drone 3 feed: http://127.0.0.1:5013/video_feed")

if st.sidebar.button("Refresh results"):
    st.rerun()


st.subheader("✅ Module Completion")

module_rows = [
    {
        "part": "Part 5",
        "module": "Altitude-separated surveillance patrol",
        "status": part05.get("status", "missing"),
        "result": part05.get("result", "unknown"),
    },
    {
        "part": "Part 6",
        "module": "Swarm zone assignment",
        "status": part06.get("status", "missing"),
        "result": part06.get("result", "unknown"),
    },
    {
        "part": "Part 8",
        "module": "Swarm communication and event sharing",
        "status": part08.get("status", "missing"),
        "result": part08.get("result", "unknown"),
    },
    {
        "part": "Part 9",
        "module": "Battlefield intelligence fusion",
        "status": part09.get("status", "missing"),
        "result": part09.get("result", "unknown"),
    },
    {
        "part": "Part 11",
        "module": "Failure simulation and swarm recovery",
        "status": part11.get("status", "missing"),
        "result": part11.get("result", "unknown"),
    },
]

st.table(module_rows)

st.divider()

st.subheader("🔁 Main Project End-to-End Run Comparison")

if comparison:
    st.table(
        [
            {
                "run_result": comparison.get("result"),
                "run_status": comparison.get("status"),
                "created_at_utc": comparison.get("created_at_utc"),
            }
        ]
    )

    current_run = comparison.get("current_run", {})
    if current_run:
        st.markdown("### Current Run Metrics")
        st.table(
            [
                {
                    "metric": key,
                    "value": value,
                }
                for key, value in current_run.items()
            ]
        )

    checks = comparison.get("validation_checks", {})
    if checks:
        st.markdown("### Validation Checks")
        st.table(
            [
                {
                    "check": key,
                    "status": "PASS" if value else "WARN",
                }
                for key, value in checks.items()
            ]
        )
else:
    st.warning("Main project comparison output not found yet. Run the main project comparison script once.")


st.divider()

st.subheader("🛰️ Final Mission State")

mission = live_state.get("mission", {})
safety = live_state.get("safety", {})
drones = live_state.get("drones", {})

st.table(
    [
        {
            "mission_status": mission.get("status"),
            "phase": mission.get("phase"),
            "elapsed_s": mission.get("elapsed_s"),
            "updated_at_utc": mission.get("updated_at_utc"),
            "safety_status": safety.get("status"),
            "minimum_3d_separation_m": safety.get("minimum_3d_separation_m"),
        }
    ]
)

drone_rows = []

for drone_id, data in drones.items():
    drone_rows.append(
        {
            "drone": drone_id,
            "model": data.get("model"),
            "zone": data.get("zone"),
            "status": data.get("status"),
            "x": data.get("x"),
            "y": data.get("y"),
            "altitude_m": data.get("z"),
            "assigned_altitude_m": data.get("assigned_altitude_m"),
        }
    )

if drone_rows:
    st.table(drone_rows)
else:
    st.warning("No drone live-state rows found.")


st.divider()

st.subheader("🧭 Zone Assignment")

zone_rows = []

for zone_name, zone in part06.get("zones", {}).items():
    zone_rows.append(
        {
            "zone": zone_name,
            "assigned_drone": zone.get("assigned_drone"),
            "model": zone.get("model"),
            "role": zone.get("role"),
            "altitude_m": zone.get("altitude_m"),
            "priority": zone.get("priority"),
        }
    )

if zone_rows:
    st.table(zone_rows)
else:
    st.warning("Zone assignment summary not found.")


st.divider()

st.subheader("📡 Event Sharing Summary")

st.table(
    [
        {
            "raw_events": part08.get("raw_event_count"),
            "shared_events": part08.get("shared_event_count"),
            "deduplicated_events": part08.get("deduplicated_event_count"),
            "communication_mode": part08.get("communication_mode"),
        }
    ]
)


st.divider()

st.subheader("🎯 Operator Threat Table")

if threat_table:
    st.table(threat_table)
else:
    st.warning("Threat table not found.")


st.divider()

st.subheader("🧠 Fused Battlefield Intelligence")

risk_counts = fused.get("risk_counts", {})

st.table(
    [
        {
            "overall_risk": fused.get("overall_risk_level"),
            "high": risk_counts.get("high"),
            "medium": risk_counts.get("medium"),
            "low": risk_counts.get("low"),
            "human_review_required": fused.get("human_in_loop", {}).get("required"),
        }
    ]
)

fusion_zone_rows = []

for zone_name, zone in fused.get("zone_summary", {}).items():
    fusion_zone_rows.append(
        {
            "zone": zone_name,
            "assigned_drone": zone.get("assigned_drone"),
            "role": zone.get("role"),
            "detected_threats": zone.get("detected_threats"),
            "highest_risk": zone.get("highest_risk"),
        }
    )

if fusion_zone_rows:
    st.table(fusion_zone_rows)

st.info(
    "Human-in-the-loop mode is enabled. "
    "This dashboard supports operator review and battlefield intelligence only. "
    "It does not make autonomous engagement decisions."
)


st.divider()


st.divider()

st.subheader("🚨 Failure Simulation and Swarm Recovery")

if part11:
    st.table(
        [
            {
                "failed_drone": part11.get("failed_drone"),
                "failure_type": part11.get("failure_type"),
                "affected_zone": part11.get("affected_zone"),
                "recovery_status": part11.get("recovery_status"),
                "human_approval_required": part11.get("human_approval_required"),
                "result": part11.get("result"),
            }
        ]
    )

    coverage = part11_plan.get("coverage_after_failure", {})
    recovery_rows = []

    for zone_name, zone in coverage.items():
        recovery_rows.append(
            {
                "zone": zone_name,
                "status": zone.get("status"),
                "primary_drone": zone.get("primary_drone"),
                "supporting_drones": ",".join(zone.get("supporting_drones", []))
                if isinstance(zone.get("supporting_drones"), list)
                else zone.get("supporting_drones"),
                "coverage": zone.get("coverage"),
            }
        )

    if recovery_rows:
        st.markdown("### Coverage After Failure")
        st.table(recovery_rows)

    timeline = part11_state.get("timeline", [])
    if timeline:
        st.markdown("### Failure Recovery Timeline")
        st.table(timeline)

    st.warning(
        "Part 11 is a simulated failure-recovery reasoning module. "
        "Real-time MAVLink failover and dynamic replanning are future scope."
    )
else:
    st.warning("Part 11 failure recovery output not found.")


st.subheader("📁 Output Files")

st.table(
    [
        {"name": "Part 5 summary", "path": inputs.get("part05_summary")},
        {"name": "Part 6 summary", "path": inputs.get("part06_summary")},
        {"name": "Part 8 summary", "path": inputs.get("part08_summary")},
        {"name": "Part 9 summary", "path": inputs.get("part09_summary")},
        {"name": "Fused intelligence", "path": inputs.get("part09_fused_intelligence")},
        {"name": "Threat table", "path": inputs.get("part09_threat_table")},
        {"name": "Main comparison", "path": inputs.get("main_comparison")},
        {"name": "Live state", "path": inputs.get("live_state")},
    ]
)

with st.expander("Raw fused intelligence JSON"):
    st.json(fused)

with st.expander("Raw comparison JSON"):
    st.json(comparison)

with st.expander("Raw live state JSON"):
    st.json(live_state)
