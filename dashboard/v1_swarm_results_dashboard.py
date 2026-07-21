from pathlib import Path
import csv
import json

import streamlit as st
import streamlit.components.v1 as components


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


def card(title: str, value: str, sub: str = ""):
    components.html(
        f"""
        <div style="
            background:#111827;
            color:#ffffff;
            border:1px solid #374151;
            border-radius:14px;
            padding:16px;
            min-height:105px;
        ">
            <div style="font-size:13px;color:#9ca3af;">{title}</div>
            <div style="font-size:28px;font-weight:800;margin-top:8px;">{value}</div>
            <div style="font-size:12px;color:#9ca3af;margin-top:8px;">{sub}</div>
        </div>
        """,
        height=120,
    )


config = load_json(CONFIG_PATH, {"inputs": {}})
inputs = config.get("inputs", {})

part05 = load_json(ROOT / inputs.get("part05_summary", ""), {})
part06 = load_json(ROOT / inputs.get("part06_summary", ""), {})
part08 = load_json(ROOT / inputs.get("part08_summary", ""), {})
part09 = load_json(ROOT / inputs.get("part09_summary", ""), {})
fused = load_json(ROOT / inputs.get("part09_fused_intelligence", ""), {})
live_state = load_json(ROOT / inputs.get("live_state", ""), {})
threat_table = load_csv(ROOT / inputs.get("part09_threat_table", ""))


st.subheader("✅ Completion Overview")

overview_rows = [
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
]

st.table(overview_rows)

cols = st.columns(4)
with cols[0]:
    card(
        "Overall Risk",
        str(fused.get("overall_risk_level", "NA")),
        "From fused swarm intelligence",
    )
with cols[1]:
    card(
        "Threat Count",
        str(part09.get("threat_count", len(threat_table))),
        "Operator threat rows",
    )
with cols[2]:
    card(
        "Shared Events",
        str(part08.get("shared_event_count", "NA")),
        "Drone-to-drone shared events",
    )
with cols[3]:
    card(
        "Telemetry Samples",
        str(part09.get("patrol_telemetry_samples", "NA")),
        "Patrol telemetry records",
    )

st.divider()

st.subheader("🛰️ Drone Mission State")

mission = live_state.get("mission", {})
drones = live_state.get("drones", {})
safety = live_state.get("safety", {})

mission_rows = [
    {
        "mission_status": mission.get("status"),
        "phase": mission.get("phase"),
        "elapsed_s": mission.get("elapsed_s"),
        "loop": mission.get("loop"),
        "updated_at_utc": mission.get("updated_at_utc"),
    }
]

st.table(mission_rows)

drone_rows = []
for drone_id, data in drones.items():
    drone_rows.append(
        {
            "drone": drone_id,
            "model": data.get("model"),
            "zone": data.get("zone"),
            "status": data.get("status"),
            "phase": data.get("phase"),
            "x": data.get("x"),
            "y": data.get("y"),
            "altitude_m": data.get("z"),
            "assigned_altitude_m": data.get("assigned_altitude_m"),
            "current_waypoint": data.get("current_waypoint"),
        }
    )

if drone_rows:
    st.table(drone_rows)
else:
    st.warning("No live-state drone rows found. Run the patrol once to populate live telemetry.")

st.subheader("🛡️ Separation Safety")

st.table(
    [
        {
            "status": safety.get("status", "NA"),
            "minimum_3d_separation_m": safety.get("minimum_3d_separation_m", "NA"),
            "closest_pair": safety.get("closest_pair", "NA"),
            "altitude_separation_enabled": safety.get("altitude_separation_enabled", "NA"),
        }
    ]
)

if safety.get("pairwise_distances_m"):
    st.json(safety["pairwise_distances_m"])

st.divider()

st.subheader("🧭 Zone Assignment")

zones = part06.get("zones", {})
zone_rows = []

for zone_name, zone in zones.items():
    zone_rows.append(
        {
            "zone": zone_name,
            "assigned_drone": zone.get("assigned_drone"),
            "model": zone.get("model"),
            "role": zone.get("role"),
            "altitude_m": zone.get("altitude_m"),
            "priority": zone.get("priority"),
            "coverage": zone.get("coverage_type"),
        }
    )

if zone_rows:
    st.table(zone_rows)
else:
    st.warning("Zone assignment output not found.")

st.divider()

st.subheader("📡 Event Sharing Summary")

event_rows = [
    {
        "raw_events": part08.get("raw_event_count"),
        "shared_events": part08.get("shared_event_count"),
        "deduplicated_events": part08.get("deduplicated_event_count"),
        "communication_mode": part08.get("communication_mode"),
    }
]

st.table(event_rows)

st.divider()

st.subheader("🎯 Operator Threat Table")

if threat_table:
    st.table(threat_table)
else:
    st.warning("No threat table rows found.")

st.divider()

st.subheader("🧠 Fused Battlefield Intelligence")

risk_counts = fused.get("risk_counts", {})
st.table(
    [
        {
            "overall_risk_level": fused.get("overall_risk_level", "NA"),
            "high": risk_counts.get("high", 0),
            "medium": risk_counts.get("medium", 0),
            "low": risk_counts.get("low", 0),
            "human_review_required": fused.get("human_in_loop", {}).get("required", "NA"),
        }
    ]
)

zone_summary = fused.get("zone_summary", {})
fusion_zone_rows = []

for zone_name, zone in zone_summary.items():
    fusion_zone_rows.append(
        {
            "zone": zone_name,
            "assigned_drone": zone.get("assigned_drone"),
            "role": zone.get("role"),
            "altitude_m": zone.get("altitude_m"),
            "detected_threats": zone.get("detected_threats"),
            "highest_risk": zone.get("highest_risk"),
        }
    )

if fusion_zone_rows:
    st.table(fusion_zone_rows)

st.info(
    "Human-in-the-loop mode is enabled. "
    "This project provides battlefield intelligence and operator review support only. "
    "It does not make autonomous engagement or weapon-control decisions."
)

st.divider()

st.subheader("📁 Generated Output Files")

output_rows = [
    {
        "name": "Part 5 patrol summary",
        "path": inputs.get("part05_summary"),
    },
    {
        "name": "Part 6 zone assignment",
        "path": inputs.get("part06_summary"),
    },
    {
        "name": "Part 8 event sharing",
        "path": inputs.get("part08_summary"),
    },
    {
        "name": "Part 9 fusion summary",
        "path": inputs.get("part09_summary"),
    },
    {
        "name": "Fused intelligence JSON",
        "path": inputs.get("part09_fused_intelligence"),
    },
    {
        "name": "Operator threat table CSV",
        "path": inputs.get("part09_threat_table"),
    },
    {
        "name": "Live state JSON",
        "path": inputs.get("live_state"),
    },
]

st.table(output_rows)

with st.expander("Show raw fused intelligence JSON"):
    st.json(fused)

with st.expander("Show raw live state JSON"):
    st.json(live_state)
