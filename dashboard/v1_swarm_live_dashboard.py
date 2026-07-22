from pathlib import Path
import json
import streamlit as st


ROOT = Path.home() / "Programs" / "SWARM_DRONES"
LIVE_STATE = ROOT / "outputs/live/swarm_live_state.json"

st.set_page_config(
    page_title="V1 Swarm Live Operator Dashboard",
    page_icon="🛰️",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1rem;
            padding-left: 1.5rem;
            padding-right: 1.5rem;
            max-width: 100% !important;
        }
        .feed-card {
            border: 1px solid #333;
            border-radius: 12px;
            padding: 10px;
            background: #0f1117;
            min-height: 470px;
        }
        .feed-title {
            font-size: 19px;
            font-weight: 800;
            margin-bottom: 8px;
            color: white;
        }
        .feed-img {
            width: 100%;
            height: 390px;
            object-fit: contain;
            background: black;
            border-radius: 10px;
            border: 1px solid #222;
        }
        .feed-url {
            font-size: 11px;
            color: #aaa;
            margin-top: 6px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛰️ V1 Swarm Live Operator Dashboard")
st.caption("Live feeds + mission telemetry + safety information")


def load_state() -> dict:
    if not LIVE_STATE.exists():
        return {}
    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "error": str(exc),
            "mission": {
                "status": "ERROR",
                "phase": "live_state_read_failed",
            },
            "drones": {},
            "safety": {},
            "operator_notes": [],
        }


state = load_state()
mission = state.get("mission", {})
drones = state.get("drones", {})
safety = state.get("safety", {})

with st.sidebar:
    st.header("Controls")
    st.write("Live dashboard: http://127.0.0.1:8502")
    st.write("Results dashboard: http://127.0.0.1:8503")
    st.divider()
    st.write("Drone feeds:")
    st.write("Drone 1 → 5011")
    st.write("Drone 2 → 5012")
    st.write("Drone 3 → 5013")
    st.divider()
    if st.button("Refresh telemetry now"):
        st.rerun()

st.subheader("📷 Live Camera Feeds")

feeds = [
    {
        "title": "Drone 1 — x500_mono_cam_1",
        "url": "http://127.0.0.1:5011/video_feed",
    },
    {
        "title": "Drone 2 — x500_mono_cam_2",
        "url": "http://127.0.0.1:5012/video_feed",
    },
    {
        "title": "Drone 3 — x500_mono_cam_3",
        "url": "http://127.0.0.1:5013/video_feed",
    },
]

cols = st.columns(3)

for col, feed in zip(cols, feeds):
    with col:
        st.markdown(
            f"""
            <div class="feed-card">
                <div class="feed-title">{feed["title"]}</div>
                <img class="feed-img" src="{feed["url"]}">
                <div class="feed-url">{feed["url"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

st.subheader("📡 Mission Status")

mission_row = [
    {
        "status": mission.get("status"),
        "phase": mission.get("phase"),
        "tick": mission.get("tick"),
        "total_ticks": mission.get("total_ticks"),
        "elapsed_s": mission.get("elapsed_s"),
        "updated_at_utc": mission.get("updated_at_utc"),
    }
]

st.table(mission_row)

st.subheader("🛩️ Drone Telemetry")

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
            "z": data.get("z"),
            "target_x": data.get("target_x"),
            "target_y": data.get("target_y"),
            "target_z": data.get("target_z"),
            "assigned_altitude_m": data.get("assigned_altitude_m"),
        }
    )

if drone_rows:
    st.table(drone_rows)
else:
    st.warning("No drone telemetry yet. Start the patrol script.")

st.subheader("🛡️ Swarm Safety")

safety_row = [
    {
        "status": safety.get("status"),
        "minimum_3d_separation_m": safety.get("minimum_3d_separation_m"),
        "closest_pair": safety.get("closest_pair"),
        "altitude_separation_enabled": safety.get("altitude_separation_enabled"),
        "continuous_motion_enabled": safety.get("continuous_motion_enabled"),
        "overlapping_search_enabled": safety.get("overlapping_search_enabled"),
        "gazebo_safe_low_load_mode": safety.get("gazebo_safe_low_load_mode"),
    }
]

st.table(safety_row)

pairwise = safety.get("pairwise_distances_m", {})
if pairwise:
    st.markdown("### Pairwise Drone Distances")
    st.table(
        [
            {
                "pair": key,
                "distance_m": value,
            }
            for key, value in pairwise.items()
        ]
    )

st.subheader("🧠 Operator Notes")

notes = state.get("operator_notes", [])

if notes:
    for note in notes:
        st.info(note)
else:
    st.info("No operator notes yet.")

with st.expander("Raw Live State JSON"):
    st.json(state)
